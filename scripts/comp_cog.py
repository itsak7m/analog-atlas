"""comp_cog: stdlib-only Cloud Optimized GeoTIFF reader over HTTP range requests (or a local file).

Helper for scripts/fetch_composition.py. Ported from the no-login scout prototype (cogread.py):
HTTP Range reads of only the header and the internal tiles that are touched, several samples
per pixel (chunky or planar), DEFLATE / LZW / none, predictor 1/2/3, and projection helpers
(UTM, MODIS sinusoidal). Changes from the prototype: one kept-alive HTTPS connection per host
*per thread*, and global request / byte counters (for the manifest).

Python 3.12 standard library only.
"""
import array
import http.client
import itertools
import math
import operator
import struct
import sys
import threading
import time
import urllib.parse
import zlib

TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8, 17: 8, 18: 8}
TYPE_FMT = {1: "B", 2: "s", 3: "H", 4: "I", 5: "II", 6: "b", 7: "B", 8: "h", 9: "i", 10: "ii",
            11: "f", 12: "d", 16: "Q", 17: "q", 18: "Q"}
SAMPLE_TYPES = {(3, 32): "f", (3, 64): "d", (2, 16): "h", (1, 16): "H", (2, 32): "i", (1, 32): "I",
                (1, 8): "B", (2, 8): "b"}

# ------------------------------------------------------------------ request accounting
STATS_LOCK = threading.Lock()
STATS = {}          # host -> {"requests": n, "bytes": n, "errors": n}


def count(host, nbytes=0, error=False):
    with STATS_LOCK:
        s = STATS.setdefault(host, {"requests": 0, "bytes": 0, "errors": 0})
        s["requests"] += 1
        s["bytes"] += nbytes
        if error:
            s["errors"] += 1


# ------------------------------------------------------------------ HTTP (keep-alive per thread)
_LOCAL = threading.local()
# A tiny global throttle so that all threads together stay under MAX_RATE requests per second
# (Planetary Computer is shared with another job; keep the load modest).
MAX_RATE = 8.0
_RATE_LOCK = threading.Lock()
_next_slot = [0.0]


def _throttle():
    with _RATE_LOCK:
        now = time.monotonic()
        slot = max(now, _next_slot[0])
        _next_slot[0] = slot + 1.0 / MAX_RATE
    wait = slot - now
    if wait > 0:
        time.sleep(wait)


def http_get(url, headers=None, timeout=30, body=None, method=None):
    """GET (or POST when body is given) over a kept-alive connection per host and thread.
    Follows redirects. Raises IOError on HTTP >= 400."""
    headers = dict(headers or {})
    pool = getattr(_LOCAL, "pool", None)
    if pool is None:
        pool = _LOCAL.pool = {}
    for _ in range(5):
        u = urllib.parse.urlsplit(url)
        key = (u.scheme, u.netloc)
        conn = pool.get(key)
        if conn is None:
            cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
            conn = cls(u.netloc, timeout=timeout)
            pool[key] = conn
        conn.timeout = timeout
        if conn.sock is not None:
            conn.sock.settimeout(timeout)
        path = u.path + ("?" + u.query if u.query else "")
        _throttle()
        try:
            conn.request(method or ("POST" if body is not None else "GET"), path, body=body, headers=headers)
            r = conn.getresponse()
            data = r.read()
        except Exception:
            conn.close()
            pool.pop(key, None)
            count(u.netloc, 0, error=True)
            raise
        count(u.netloc, len(data))
        if r.status in (301, 302, 303, 307, 308):
            url = urllib.parse.urljoin(url, r.getheader("Location"))
            continue
        if r.status >= 400:
            raise IOError("HTTP %d for %s" % (r.status, u.netloc + u.path))
        return data
    raise IOError("too many redirects")


# ------------------------------------------------------------------ TIFF LZW
def lzw_decode(data):
    """TIFF LZW (MSB-first codes, early change)."""
    out = bytearray()
    table = [bytes([i]) for i in range(256)] + [b"", b""]
    bitbuf = 0
    nbits = 0
    width = 9
    prev = None
    pos = 0
    n = len(data)
    while True:
        while nbits < width and pos < n:
            bitbuf = (bitbuf << 8) | data[pos]
            pos += 1
            nbits += 8
        if nbits < width:
            break
        nbits -= width
        code = (bitbuf >> nbits) & ((1 << width) - 1)
        if code == 256:
            table = table[:258]
            width = 9
            prev = None
            continue
        if code == 257:
            break
        if prev is None:
            entry = table[code]
            out += entry
            prev = entry
            continue
        if code < len(table):
            entry = table[code]
            table.append(prev + entry[:1])
        else:
            entry = prev + prev[:1]
            table.append(entry)
        out += entry
        prev = entry
        if len(table) + 1 >= (1 << width) and width < 12:
            width += 1
    return bytes(out)


class Source:
    """Byte source: local path or URL (url_fn() returns a fresh, possibly re-signed URL)."""

    def __init__(self, path=None, url_fn=None, on_error=None, tries=8):
        self.path, self.url_fn, self.on_error, self.tries = path, url_fn, on_error, tries
        self.nbytes = 0
        self.nreq = 0
        if path:
            self.f = open(path, "rb")

    def read(self, off, n):
        if self.path:
            self.f.seek(off)
            return self.f.read(n)
        for k in range(self.tries):
            try:
                data = http_get(self.url_fn(), {"Range": "bytes=%d-%d" % (off, off + n - 1)},
                                timeout=20 if k < 3 else 60)
                self.nbytes += len(data)
                self.nreq += 1
                return data
            except Exception:
                if k == self.tries - 1:
                    raise
                if self.on_error:
                    self.on_error()
                time.sleep(1.0 + 1.5 * k)


class COG:
    def __init__(self, source, header_bytes=65536):
        self.src = source
        self.head = source.read(0, header_bytes)
        d = self.head
        self.bo = "<" if d[:2] == b"II" else ">"
        magic = struct.unpack(self.bo + "H", d[2:4])[0]
        self.big = magic == 43
        ifd = struct.unpack(self.bo + ("Q" if self.big else "I"), d[8:16] if self.big else d[4:8])[0]
        self.tags = self._read_ifd(ifd)
        self._setup()
        self._cache = {}

    def _bytes(self, off, n):
        if off + n <= len(self.head):
            return self.head[off:off + n]
        return self.src.read(off, n)

    def _read_ifd(self, off):
        bo = self.bo
        if self.big:
            n = struct.unpack(bo + "Q", self._bytes(off, 8))[0]
            p, esize, cfmt, inline = off + 8, 20, "HHQ", 8
        else:
            n = struct.unpack(bo + "H", self._bytes(off, 2))[0]
            p, esize, cfmt, inline = off + 2, 12, "HHI", 4
        blob = self._bytes(p, n * esize)
        head = struct.calcsize(cfmt)
        tags = {}
        for i in range(n):
            e = i * esize
            tag, typ, cnt = struct.unpack(bo + cfmt, blob[e:e + head])
            size = TYPE_SIZES.get(typ, 1) * cnt
            if size <= inline:
                raw = blob[e + head:e + head + size]
            else:
                voff = struct.unpack(bo + ("Q" if self.big else "I"), blob[e + head:e + head + inline])[0]
                raw = self._bytes(voff, size)
            tags[tag] = self._val(typ, cnt, raw)
        return tags

    def _val(self, typ, cnt, raw):
        if typ == 2:
            return raw.rstrip(b"\x00").decode("latin-1")
        if typ in (5, 10):
            v = struct.unpack(self.bo + TYPE_FMT[typ][0] * (2 * cnt), raw)
            return [v[k] / v[k + 1] for k in range(0, len(v), 2)]
        if typ in TYPE_FMT:
            return list(struct.unpack(self.bo + TYPE_FMT[typ] * cnt, raw))
        return raw

    def _one(self, tag, default=None):
        v = self.tags.get(tag, default)
        return v[0] if isinstance(v, list) and len(v) == 1 else v

    def _setup(self):
        t = self.tags
        self.width, self.height = self._one(256), self._one(257)
        self.bits = t.get(258, [8])[0]
        self.spp = self._one(277, 1)
        self.planar = self._one(284, 1)
        self.compression = self._one(259, 1)
        self.predictor = self._one(317, 1)
        sf = t.get(339, [1])[0]
        self.typecode = SAMPLE_TYPES[(sf, self.bits)]
        self.bps = self.bits // 8
        if 322 in t:
            self.tw, self.th = self._one(322), self._one(323)
            self.offsets, self.counts = t[324], t[325]
            self.tiled = True
        else:
            self.tw, self.th = self.width, self._one(278, self.height)
            self.offsets, self.counts = t[273], t[279]
            self.tiled = False
        self.ta = (self.width + self.tw - 1) // self.tw
        self.td = (self.height + self.th - 1) // self.th
        self.geokeys = {}
        if 34735 in t:
            gk = t[34735]
            for k in range(4, 4 + 4 * gk[3], 4):
                kid, loc, cnt, val = gk[k:k + 4]
                self.geokeys[kid] = val if loc == 0 else t[loc][val:val + cnt]
        self.epsg = self.geokeys.get(3072) or self.geokeys.get(2048)
        sx, sy = t[33550][0], t[33550][1]
        i, j, _, x, y, _ = t[33922][:6]
        x0, y0 = x - i * sx, y + j * sy
        if self.geokeys.get(1025) == 2:      # PixelIsPoint
            x0 -= sx / 2.0
            y0 += sy / 2.0
        self.gt = (x0, sx, y0, sy)
        nd = t.get(42113)
        self.nodata = float(nd) if isinstance(nd, str) and nd.strip() not in ("", "nan") else None
        self.gdal_metadata = t.get(42112)

    def block_index(self, row, col):
        return (row // self.th) * self.ta + col // self.tw

    def _decode(self, idx, nsamp):
        if idx in self._cache:
            return self._cache[idx]
        off, cnt = self.offsets[idx], self.counts[idx]
        nrows = self.th if self.tiled else min(self.th, self.height - (idx % self.td) * self.th)
        n = self.tw * nrows * nsamp
        if cnt == 0:
            vals = array.array(self.typecode, [0]) * n
        else:
            raw = self._bytes(off, cnt)
            if self.compression in (8, 32946):
                raw = zlib.decompress(raw)
            elif self.compression == 5:
                raw = lzw_decode(raw)
            elif self.compression != 1:
                raise ValueError("unsupported compression %d" % self.compression)
            raw = raw[:n * self.bps]
            if self.predictor == 3:
                rowb = self.tw * nsamp * self.bps
                outb = bytearray(len(raw))
                mask = itertools.repeat(255)
                w = self.tw * nsamp
                for r in range(nrows):
                    acc = bytes(map(operator.and_, itertools.accumulate(raw[r * rowb:(r + 1) * rowb]), mask))
                    for b in range(self.bps):
                        outb[r * rowb + b:(r + 1) * rowb:self.bps] = acc[b * w:(b + 1) * w]
                vals = array.array(self.typecode)
                vals.frombytes(bytes(outb))
                if sys.byteorder == "little":
                    vals.byteswap()
            else:
                vals = array.array(self.typecode)
                vals.frombytes(raw)
                if (self.bo == ">") != (sys.byteorder == "big"):
                    vals.byteswap()
                if self.predictor == 2:
                    w = self.tw
                    for r in range(nrows):
                        for s in range(nsamp):
                            sl = slice(r * w * nsamp + s, (r + 1) * w * nsamp, nsamp)
                            acc = list(itertools.accumulate(vals[sl]))
                            if self.typecode in "BbHhIi":
                                m = (1 << self.bits) - 1
                                acc = [a & m for a in acc]
                                if self.typecode in "bhi":
                                    half = 1 << (self.bits - 1)
                                    acc = [a - (m + 1) if a >= half else a for a in acc]
                            vals[sl] = array.array(self.typecode, acc)
        self._cache[idx] = vals
        return vals

    def block(self, idx):
        """Decoded values of internal tile idx (single-sample images only)."""
        return self._decode(idx, self.spp)

    def pixel(self, row, col):
        """Tuple of all samples at (row, col), or None outside the image."""
        if not (0 <= row < self.height and 0 <= col < self.width):
            return None
        tx, ty = col // self.tw, row // self.th
        r, c = row - ty * self.th, col - tx * self.tw
        if self.planar == 2 and self.spp > 1:
            per = self.ta * self.td
            return tuple(self._decode(s * per + ty * self.ta + tx, 1)[r * self.tw + c] for s in range(self.spp))
        v = self._decode(ty * self.ta + tx, self.spp)
        k = (r * self.tw + c) * self.spp
        return tuple(v[k:k + self.spp])

    def rowcol(self, x, y):
        x0, sx, y0, sy = self.gt
        return int(math.floor((y0 - y) / sy)), int(math.floor((x - x0) / sx))

    def window(self, x, y, half):
        """[(row, col, value-tuple)] for pixels within +-half pixels of map point (x, y)."""
        r0, c0 = self.rowcol(x, y)
        out = []
        for r in range(r0 - half, r0 + half + 1):
            for c in range(c0 - half, c0 + half + 1):
                p = self.pixel(r, c)
                if p is not None:
                    out.append((r, c, p))
        return out


# ------------------------------------------------------------------ projections
R_SIN = 6371007.181          # MODIS sinusoidal sphere radius (m)
MODIS_TILE = 1111950.5196666666
MODIS_X0, MODIS_Y0 = -20015109.354, 10007554.677


def sinusoidal(lat, lon):
    return R_SIN * math.radians(lon) * math.cos(math.radians(lat)), R_SIN * math.radians(lat)


def inv_sinusoidal(x, y):
    lat = math.degrees(y / R_SIN)
    c = math.cos(math.radians(lat))
    lon = math.degrees(x / (R_SIN * c)) if c > 1e-12 else 0.0
    return lat, lon


def modis_tile(lat, lon):
    x, y = sinusoidal(lat, lon)
    return int((x - MODIS_X0) // MODIS_TILE), int((MODIS_Y0 - y) // MODIS_TILE)


def utm(lat, lon, zone=None):
    """WGS84 lat/lon -> (easting, northing, zone, north) with the USGS series (mm accuracy)."""
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    k0 = 0.9996
    if zone is None:
        zone = int((lon + 180) // 6) + 1
    lon0 = math.radians((zone - 1) * 6 - 180 + 3)
    phi, lam = math.radians(lat), math.radians(lon)
    N = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    T = math.tan(phi) ** 2
    C = ep2 * math.cos(phi) ** 2
    A = math.cos(phi) * (lam - lon0)
    M = a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
             - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
             + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
             - (35 * e2 ** 3 / 3072) * math.sin(6 * phi))
    x = k0 * N * (A + (1 - T + C) * A ** 3 / 6 + (5 - 18 * T + T * T + 72 * C - 58 * ep2) * A ** 5 / 120) + 500000.0
    y = k0 * (M + N * math.tan(phi) * (A * A / 2 + (5 - T + 9 * C + 4 * C * C) * A ** 4 / 24
                                       + (61 - 58 * T + T * T + 600 * C - 330 * ep2) * A ** 6 / 720))
    if lat < 0:
        y += 10000000.0
    return x, y, zone, lat >= 0


def project_for(cog, lat, lon):
    """Map coordinates of (lat, lon) in the COG's CRS (UTM 326xx/327xx, EPSG 4326, or MODIS sinusoidal)."""
    e = cog.epsg
    if isinstance(e, int) and 32601 <= e <= 32660:
        x, y, _, _ = utm(lat, lon, e - 32600)
        # USGS L1T convention: southern scenes in a *north* zone code have negative northings
        return x, (y - 10000000.0 if lat < 0 else y)
    if isinstance(e, int) and 32701 <= e <= 32760:
        x, y, _, _ = utm(lat, lon, e - 32700)
        return x, y + (10000000.0 if lat >= 0 else 0)
    if e == 4326:
        return lon, lat
    return sinusoidal(lat, lon)
