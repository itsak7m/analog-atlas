"""emit_dmrpp: read EMIT NetCDF4/HDF5 variables with the Python standard library only.

Ported from the Analog Atlas scout prototype (emit_dmrpp_reader.py). LP DAAC publishes a DMR++
sidecar (<file>.nc.dmrpp, XML) listing, for every variable, the byte offset/size of each HDF5
chunk and its filters ("shuffle deflate"). With it, reading a variable is: HTTP Range ->
zlib.decompress -> un-shuffle -> array. No h5py/netCDF4 needed.

Supported: chunked or contiguous numeric variables of any rank, shuffle+deflate filters,
little/big endian, and string variables stored inline in the DMR++ (<dmrpp:vlsa>).
"""
import array
import sys
import xml.etree.ElementTree as ET
import zlib
from concurrent.futures import ThreadPoolExecutor

NS = {'d': 'http://xml.opendap.org/ns/DAP/4.0#', 'dmrpp': 'http://xml.opendap.org/dap/dmrpp/1.0.0#'}
TYPES = {'Float32': ('f', 4), 'Float64': ('d', 8), 'Int16': ('h', 2), 'Int32': ('i', 4), 'UInt32': ('I', 4),
         'UInt16': ('H', 2), 'Int8': ('b', 1), 'UInt8': ('B', 1), 'Byte': ('B', 1)}
D = '{%s}' % NS['d']
DM = '{%s}' % NS['dmrpp']


def unshuffle(raw, itemsize):
    if itemsize == 1:
        return raw
    n = len(raw) // itemsize
    out = bytearray(len(raw))
    for b in range(itemsize):
        out[b::itemsize] = raw[b * n:(b + 1) * n]
    return bytes(out)


class Var:
    def __init__(self, elem, path, dims):
        self.path = path
        self.kind = elem.tag.split('}')[1]
        self.dims = [d.get('name').lstrip('/') for d in elem.findall('d:Dim', NS)]
        self.shape = [dims[d] for d in self.dims]
        self.attrs = {a.get('name'): [v.text for v in a.findall('d:Value', NS)] for a in elem.findall('d:Attribute', NS)}
        self.strings = None
        if self.kind == 'String':
            vl = elem.find('dmrpp:vlsa', NS)
            if vl is not None:
                vals = []
                for v in vl.findall('dmrpp:v', NS) + vl.findall('d:v', NS) or list(vl):
                    vals.extend([v.text or ''] * int(v.get('c', '1')))
                self.strings = vals
            return
        self.typecode, self.itemsize = TYPES[self.kind]
        ch = elem.find('dmrpp:chunks', NS)
        self.filters = (ch.get('compressionType') or '').split() if ch is not None else []
        self.big_endian = ch is not None and ch.get('byteOrder') == 'BE'
        fv = self.attrs.get('_FillValue')
        self.fill = float(fv[0]) if fv and fv[0] not in (None, '') else None
        cds = ch.find('dmrpp:chunkDimensionSizes', NS) if ch is not None else None
        self.chunk_shape = [int(v) for v in cds.text.split()] if cds is not None and cds.text else list(self.shape)
        self.chunks = {}
        if ch is not None:
            for c in ch.findall('dmrpp:chunk', NS):
                pos = c.get('chunkPositionInArray')
                key = tuple(int(v) for v in pos.strip('[]').split(',')) if pos else tuple(0 for _ in self.shape)
                self.chunks[key] = (int(c.get('offset')), int(c.get('nBytes')))

    def chunk_key(self, idx):
        return tuple((i // c) * c for i, c in zip(idx, self.chunk_shape))


class Dataset:
    """One NetCDF file described by its DMR++ text; `reader(off, n) -> bytes` fetches ranges."""

    def __init__(self, dmrpp_text, reader, workers=8):
        root = ET.fromstring(dmrpp_text)
        self.reader = reader
        self.workers = workers
        self.dims = {d.get('name'): int(d.get('size')) for d in root.iter(D + 'Dimension')}
        self.attrs = {a.get('name'): [v.text for v in a.findall('d:Value', NS)] for a in root.findall('d:Attribute', NS)}
        self.vars = {}
        self._cache = {}
        self.bytes_read = 0

        def walk(node, prefix):
            for child in node:
                tag = child.tag.split('}')[1]
                if tag == 'Group':
                    walk(child, prefix + child.get('name') + '/')
                elif tag in TYPES or tag == 'String':
                    self.vars[prefix + child.get('name')] = Var(child, prefix + child.get('name'), self.dims)
        walk(root, '')

    # ---- chunk access -------------------------------------------------------------
    def _decode(self, var, raw):
        if 'deflate' in var.filters:
            raw = zlib.decompress(raw)
        if 'shuffle' in var.filters:
            raw = unshuffle(raw, var.itemsize)
        a = array.array(var.typecode)
        a.frombytes(raw[:len(raw) - len(raw) % var.itemsize])
        if var.big_endian != (sys.byteorder == 'big'):
            a.byteswap()
        return a

    def missing(self, pairs):
        return [(self, n, k) for n, k in set(pairs) if (n, k) not in self._cache and k in self.vars[n].chunks]

    def prefetch(self, pairs):
        """pairs: iterable of (var_name, chunk_key); downloads missing chunks in parallel."""
        prefetch_many(self.missing(pairs), self.workers)

    def value(self, name, *idx):
        v = self.vars[name]
        for i, s in zip(idx, v.shape):
            if not 0 <= i < s:
                return None
        key = v.chunk_key(idx)
        if (name, key) not in self._cache:
            if key not in v.chunks:
                return v.fill   # unwritten chunk = fill value
            self.prefetch([(name, key)])
        a = self._cache[(name, key)]
        # row-major offset inside the (possibly edge-padded, full-size) chunk
        off = 0
        for i, k, c in zip(idx, key, v.chunk_shape):
            off = off * c + (i - k)
        return a[off]

    def read_1d(self, name):
        v = self.vars[name]
        if v.strings is not None:
            return list(v.strings)
        return [self.value(name, i) for i in range(v.shape[0])]

    def drop_cache(self):
        self._cache.clear()

    # ---- geometry -----------------------------------------------------------------
    def geotransform(self):
        return [float(x) for x in self.attrs['geotransform']]


def prefetch_many(jobs, workers=12):
    """jobs: list of (Dataset, var_name, chunk_key) - fetched in parallel across files."""
    uniq = {}
    for d, n, k in jobs:
        uniq[(id(d), n, k)] = (d, n, k)
    jobs = list(uniq.values())
    if not jobs:
        return

    def job(j):
        d, n, k = j
        off, nb = d.vars[n].chunks[k]
        return j, d.reader(off, nb)
    with ThreadPoolExecutor(max(1, min(workers, len(jobs)))) as ex:
        for (d, n, k), raw in ex.map(job, jobs):
            d.bytes_read += len(raw)
            d._cache[(n, k)] = d._decode(d.vars[n], raw)
