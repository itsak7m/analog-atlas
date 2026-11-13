#!/usr/bin/env python3
"""geotiff_lite: a small GeoTIFF reader that uses only the Python 3.12 standard library.

Written for the Copernicus DEM GLO-90 Cloud Optimized GeoTIFFs on AWS Open Data
(s3://copernicus-dem-90m): float32, tiled, DEFLATE with the floating-point predictor
(TIFF Predictor = 3), geographic WGS84 coordinates. Used by scripts/screening_terrain.py.

Supports classic TIFF and BigTIFF, little or big endian, tiled or stripped images,
compression none (1) or DEFLATE (8, 32946), predictor none (1), horizontal (2) or
floating point (3), one sample per pixel, and float32/float64/int16/uint16/int32/uint8.
Only the first IFD (full resolution) is read; COG overviews are ignored.

No numpy and no GDAL: zlib inflates, array and struct do the rest.
"""

import array
import itertools
import operator
import struct
import sys
import zlib

TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8, 17: 8, 18: 8}
TYPE_FMT = {1: "B", 2: "s", 3: "H", 4: "I", 5: "II", 6: "b", 7: "B", 8: "h", 9: "i", 10: "ii",
            11: "f", 12: "d", 16: "Q", 17: "q", 18: "Q"}
SAMPLE_TYPES = {(3, 32): "f", (3, 64): "d", (2, 16): "h", (1, 16): "H", (2, 32): "i", (1, 8): "B"}
GEOKEY_NAMES = {1024: "GTModelTypeGeoKey", 1025: "GTRasterTypeGeoKey", 1026: "GTCitationGeoKey",
                2048: "GeographicTypeGeoKey", 2049: "GeogCitationGeoKey", 2054: "GeogAngularUnitsGeoKey",
                4096: "VerticalCSTypeGeoKey", 4097: "VerticalCitationGeoKey", 4099: "VerticalUnitsGeoKey"}
DEFLATE = (8, 32946)


class TiffError(Exception):
    """The file is not a TIFF this reader understands."""


def undo_float_predictor(raw, width, bps, nrows):
    """Undo TIFF predictor 3 (libtiff fpDiff) for nrows rows of `width` samples.

    Each encoded row holds the bytes regrouped into planes (the most significant byte of
    every sample first, then the next byte, ...), then differenced byte by byte along the
    row. Returns the rows as big-endian sample bytes.
    """
    rowbytes = width * bps
    out = bytearray(rowbytes * nrows)
    mask = itertools.repeat(255)
    for r in range(nrows):
        row = raw[r * rowbytes:(r + 1) * rowbytes]
        acc = bytes(map(operator.and_, itertools.accumulate(row), mask))
        o = r * rowbytes
        for b in range(bps):
            out[o + b:o + rowbytes:bps] = acc[b * width:(b + 1) * width]
    return out


class GeoTiff:
    """One GeoTIFF file: its tags, georeferencing and pixels (tiles are decoded on demand)."""

    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self.data = f.read()
        d = self.data
        if d[:2] == b"II":
            self.bo = "<"
        elif d[:2] == b"MM":
            self.bo = ">"
        else:
            raise TiffError("%s: not a TIFF file" % path)
        magic = struct.unpack(self.bo + "H", d[2:4])[0]
        if magic == 42:
            self.big = False
            ifd = struct.unpack(self.bo + "I", d[4:8])[0]
        elif magic == 43:
            self.big = True
            ifd = struct.unpack(self.bo + "Q", d[8:16])[0]
        else:
            raise TiffError("%s: bad TIFF magic %d" % (path, magic))
        self.tags = self._read_ifd(ifd)
        self._setup()
        self._tile_cache = {}

    # ---------------------------------------------------------------- parsing
    def _read_ifd(self, off):
        d, bo = self.data, self.bo
        if self.big:
            n = struct.unpack(bo + "Q", d[off:off + 8])[0]
            p, esize, cfmt, inline = off + 8, 20, "HHQ", 8
        else:
            n = struct.unpack(bo + "H", d[off:off + 2])[0]
            p, esize, cfmt, inline = off + 2, 12, "HHI", 4
        head = struct.calcsize(cfmt)
        tags = {}
        for i in range(n):
            e = p + i * esize
            tag, typ, count = struct.unpack(bo + cfmt, d[e:e + head])
            size = TYPE_SIZES.get(typ, 1) * count
            if size <= inline:
                raw = d[e + head:e + head + size]
            else:
                voff = struct.unpack(bo + ("Q" if self.big else "I"), d[e + head:e + head + inline])[0]
                raw = d[voff:voff + size]
            tags[tag] = self._tag_value(typ, count, raw)
        return tags

    def _tag_value(self, typ, count, raw):
        if typ == 2:
            return raw.rstrip(b"\x00").decode("latin-1")
        if typ in (5, 10):
            vals = struct.unpack(self.bo + TYPE_FMT[typ][0] * (2 * count), raw)
            return [vals[k] / vals[k + 1] for k in range(0, len(vals), 2)]
        if typ in TYPE_FMT:
            return list(struct.unpack(self.bo + TYPE_FMT[typ] * count, raw))
        return raw

    def _one(self, tag, default=None):
        v = self.tags.get(tag, default)
        if isinstance(v, list) and len(v) == 1:
            return v[0]
        return v

    def _setup(self):
        t = self.tags
        self.width = self._one(256)
        self.height = self._one(257)
        self.bits = t.get(258, [1])[0]
        self.spp = self._one(277, 1)
        if self.spp != 1:
            raise TiffError("only 1 sample per pixel is supported (got %d)" % self.spp)
        self.compression = self._one(259, 1)
        self.predictor = self._one(317, 1)
        self.sample_format = self._one(339, 1)
        key = (self.sample_format, self.bits)
        if key not in SAMPLE_TYPES:
            raise TiffError("unsupported sample format/bits %r" % (key,))
        self.typecode = SAMPLE_TYPES[key]
        self.bps = self.bits // 8
        if 322 in t:
            self.tw, self.th = self._one(322), self._one(323)
            self.offsets, self.counts = t[324], t[325]
        else:  # strips are read as full-width tiles
            self.tw = self.width
            self.th = self._one(278, self.height)
            self.offsets, self.counts = t[273], t[279]
        self.tiles_across = (self.width + self.tw - 1) // self.tw
        self.tiles_down = (self.height + self.th - 1) // self.th
        self.geokeys = self._geokeys()
        self.pixel_is_point = self.geokeys.get(1025) == 2
        self.gt = self._geotransform()
        nd = t.get(42113)
        self.nodata = float(nd) if isinstance(nd, str) and nd.strip() else None

    def _geokeys(self):
        t, keys = self.tags, {}
        if 34735 not in t:
            return keys
        gk = t[34735]
        for k in range(4, 4 + 4 * gk[3], 4):
            key_id, loc, cnt, val = gk[k:k + 4]
            if loc == 0:
                keys[key_id] = val
            elif loc in (34736, 34737):
                keys[key_id] = t[loc][val:val + cnt]
        return keys

    def _geotransform(self):
        """GDAL-style geotransform of pixel corners: (x0, sx, 0, y0, 0, -sy)."""
        t = self.tags
        if 33550 in t and 33922 in t:
            sx, sy = t[33550][0], t[33550][1]
            i, j, _, x, y, _ = t[33922][:6]
            x0 = x - i * sx
            y0 = y + j * sy
            if self.pixel_is_point:   # the tiepoint is a pixel centre: shift it to the corner
                x0 -= sx / 2.0
                y0 += sy / 2.0
            return (x0, sx, 0.0, y0, 0.0, -sy)
        if 34264 in t:
            m = t[34264]
            return (m[3], m[0], m[1], m[7], m[4], m[5])
        return None

    def info(self):
        return {
            "width": self.width, "height": self.height, "tile": [self.tw, self.th],
            "tiles": [self.tiles_across, self.tiles_down], "bits": self.bits,
            "sample_format": self.sample_format, "compression": self.compression,
            "predictor": self.predictor, "geotransform_corner": self.gt, "nodata": self.nodata,
            "geokeys": {GEOKEY_NAMES.get(k, str(k)): v for k, v in self.geokeys.items()},
            "pixel_is_point": self.pixel_is_point, "bigtiff": self.big,
            "byteorder": "little" if self.bo == "<" else "big",
            "gdal_metadata": self.tags.get(42112),
        }

    # ---------------------------------------------------------------- pixels
    def _tile(self, tx, ty):
        key = (tx, ty)
        if key not in self._tile_cache:
            self._tile_cache[key] = self._decode_tile(tx, ty)
        return self._tile_cache[key]

    def _decode_tile(self, tx, ty):
        idx = ty * self.tiles_across + tx
        off, cnt = self.offsets[idx], self.counts[idx]
        nrows = self.th
        if 322 not in self.tags:   # the last strip may be short
            nrows = min(self.th, self.height - ty * self.th)
        if cnt == 0:
            return array.array(self.typecode, [0]) * (self.tw * nrows)
        raw = self.data[off:off + cnt]
        if self.compression in DEFLATE:
            raw = zlib.decompress(raw)
        elif self.compression != 1:
            raise TiffError("unsupported compression %d" % self.compression)
        expected = self.tw * nrows * self.bps
        if len(raw) < expected:
            raise TiffError("tile %r: %d bytes, expected %d" % ((tx, ty), len(raw), expected))
        raw = raw[:expected]
        if self.predictor == 3:
            buf, big_endian = undo_float_predictor(raw, self.tw, self.bps, nrows), True
        else:
            buf, big_endian = raw, self.bo == ">"
        vals = array.array(self.typecode)
        vals.frombytes(bytes(buf))
        if big_endian != (sys.byteorder == "big"):
            vals.byteswap()
        if self.predictor == 2:
            w = self.tw
            for r in range(nrows):
                vals[r * w:(r + 1) * w] = array.array(self.typecode, itertools.accumulate(vals[r * w:(r + 1) * w]))
        return vals

    def pixel(self, row, col):
        """Value at integer pixel (row, col); None outside the image or at nodata."""
        if not (0 <= row < self.height and 0 <= col < self.width):
            return None
        tx, ty = col // self.tw, row // self.th
        v = self._tile(tx, ty)[(row - ty * self.th) * self.tw + (col - tx * self.tw)]
        if self.nodata is not None and v == self.nodata:
            return None
        return v

    # ---------------------------------------------------------------- geo helpers
    def pixel_center(self, row, col):
        """(lat, lon) of a pixel centre (north-up images only)."""
        x0, sx, _, y0, _, sy = self.gt
        return y0 + (row + 0.5) * sy, x0 + (col + 0.5) * sx
