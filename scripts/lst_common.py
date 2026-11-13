"""Helpers for scripts/fetch_lst.py: MODIS MOD21A2/MYD21A2 LST from Microsoft Planetary Computer.

Python 3.12 standard library only. No account, no key.

Microsoft Planetary Computer (NASA LP DAAC MODIS Collection 6.1 mirrored as Cloud Optimized GeoTIFFs):
  STAC search : POST https://planetarycomputer.microsoft.com/api/stac/v1/search
  point value : GET  https://planetarycomputer.microsoft.com/api/data/v1/item/point/{lon},{lat}
                     ?collection=<c>&item=<id>&assets=<a>&assets=<b>...
  SAS token   : GET  https://planetarycomputer.microsoft.com/api/sas/v1/token/modiseuwest/modis-061-cogs
                (the account/container form; the /token/<collection> form returns a token for the
                 HDF container, which does NOT open the COGs)
  COGs        : https://modiseuwest.blob.core.windows.net/modis-061-cogs/...  (HTTP range reads)

Every connection is a per-thread keep-alive HTTPS connection: new TCP connections to these hosts
failed often from the build machine (WinError 10060 after ~21 s), reused ones do not.
"""

import array
import http.client
import json
import math
import struct
import sys
import threading
import time
import urllib.parse
import zlib

PC_HOST = "planetarycomputer.microsoft.com"
STAC_SEARCH = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
POINT_API = "https://planetarycomputer.microsoft.com/api/data/v1/item/point/{lon},{lat}"
SAS_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/token/modiseuwest/modis-061-cogs"
COLLECTION = "modis-21A2-061"
UA = "analog-atlas-lst/1.0 (NASA Space Apps 2026 Amman; Python stdlib)"

# MODIS sinusoidal grid (MODIS Land tile grid; sphere radius as defined for the grid)
R_SIN = 6371007.181
TILE_M = 1111950.5197665233          # one tile edge = 10 degrees of arc on that sphere (m)
PIX_1KM = TILE_M / 1200.0            # 926.625433... m
PIX_500M = TILE_M / 2400.0

STATS = {"requests": 0, "bytes": 0, "retries": 0, "connects": 0, "http_errors": 0}
_STATS_LOCK = threading.Lock()
_LOCAL = threading.local()


def _count(key, n=1):
    with _STATS_LOCK:
        STATS[key] = STATS.get(key, 0) + n


def stats_snapshot():
    with _STATS_LOCK:
        return dict(STATS)


class HTTPStatusError(IOError):
    def __init__(self, status, url, body=b""):
        super().__init__("HTTP %d for %s: %s" % (status, url[:160], body[:200]))
        self.status = status


def _conn(host, timeout):
    conns = getattr(_LOCAL, "conns", None)
    if conns is None:
        conns = _LOCAL.conns = {}
    c = conns.get(host)
    if c is None:
        c = http.client.HTTPSConnection(host, timeout=timeout)
        conns[host] = c
        _count("connects")
    return c


def _drop(host):
    conns = getattr(_LOCAL, "conns", {})
    c = conns.pop(host, None)
    if c is not None:
        try:
            c.close()
        except Exception:
            pass


def request(url, body=None, headers=None, tries=8, timeout=60, ok=(200, 206)):
    """GET (or POST JSON when body is given) over the calling thread's keep-alive connection.

    Retries on connection errors, timeouts, 429 and 5xx. Returns (status, bytes)."""
    u = urllib.parse.urlsplit(url)
    path = u.path + ("?" + u.query if u.query else "")
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    delay = 1.0
    last = None
    for k in range(tries):
        c = _conn(u.netloc, timeout)
        try:
            c.request("POST" if data is not None else "GET", path, body=data, headers=h)
            r = c.getresponse()
            payload = r.read()
            if r.status in ok:
                _count("requests")
                _count("bytes", len(payload))
                if (r.getheader("Connection") or "").lower() == "close":
                    _drop(u.netloc)
                return r.status, payload
            _count("http_errors")
            last = HTTPStatusError(r.status, url, payload)
            if r.status in (429, 500, 502, 503, 504) and k < tries - 1:
                ra = r.getheader("Retry-After")
                time.sleep(float(ra) if ra and ra.isdigit() else delay)
                delay = min(delay * 2, 30)
                continue
            raise last
        except (OSError, http.client.HTTPException) as e:
            if isinstance(e, HTTPStatusError):
                raise
            last = e
            _count("retries")
            _drop(u.netloc)
            if k == tries - 1:
                break
            time.sleep(min(0.5 * (k + 1), 5))
    raise last


def get_json(url, body=None, **kw):
    return json.loads(request(url, body=body, **kw)[1])


# ----------------------------------------------------------------------------------------------
# STAC and point API

def stac_search(collection, lon, lat, start, end, limit=1000):
    """All STAC items of `collection` whose footprint contains (lon, lat) and whose time range
    overlaps [start, end]. Follows 'next' links."""
    body = {"collections": [collection],
            "intersects": {"type": "Point", "coordinates": [lon, lat]},
            "datetime": "%s/%s" % (start, end), "limit": limit}
    url, items = STAC_SEARCH, []
    while True:
        page = get_json(url, body=body)
        items.extend(page["features"])
        nxt = [l for l in page.get("links", []) if l.get("rel") == "next"]
        if not nxt:
            return items
        n = nxt[0]
        url = n["href"]
        body = n.get("body") if n.get("method", "GET").upper() == "POST" else None


def stac_search_tile(collection, h, v, start, end, assets=(), limit=1000):
    """All STAC items of `collection` for MODIS tile hXXvYY whose time range overlaps [start, end].

    Filters on the item properties modis:horizontal-tile / modis:vertical-tile (CQL2) instead of a
    point footprint: near the poles the item footprints do not always contain their own tile's
    points (Haughton's tile h15v01 is not returned for its own coordinates). The STAC 'fields'
    extension keeps the answers small (id, platform, dates, tile numbers, wanted asset hrefs)."""
    flt = {"op": "and", "args": [{"op": "=", "args": [{"property": "modis:horizontal-tile"}, h]},
                                 {"op": "=", "args": [{"property": "modis:vertical-tile"}, v]}]}
    inc = ["id", "properties.platform", "properties.start_datetime", "properties.end_datetime",
           "properties.modis:horizontal-tile", "properties.modis:vertical-tile"] + ["assets.%s.href" % a for a in assets]
    body = {"collections": [collection], "filter-lang": "cql2-json", "filter": flt,
            "datetime": "%s/%s" % (start, end), "limit": limit,
            "fields": {"include": inc, "exclude": ["links", "geometry", "bbox"] + ([] if assets else ["assets"])}}
    url, items = STAC_SEARCH, []
    while True:
        page = get_json(url, body=body)
        items.extend(page["features"])
        nxt = [l for l in page.get("links", []) if l.get("rel") == "next"]
        if not nxt:
            return items
        n = nxt[0]
        url = n["href"]
        body = n.get("body") if n.get("method", "GET").upper() == "POST" else None


def point_url(collection, item_id, lon, lat, assets):
    q = "collection=%s&item=%s&%s" % (collection, item_id, "&".join("assets=" + a for a in assets))
    return POINT_API.format(lon="%.6f" % lon, lat="%.6f" % lat) + "?" + q


def point_values(collection, item_id, lon, lat, assets):
    return get_json(point_url(collection, item_id, lon, lat, assets))


PLATFORM_BY_PRODUCT = {"MOD21A2": "terra", "MYD21A2": "aqua", "MOD09A1": "terra", "MOD13A1": "terra"}


def select_items(items, h, v, first_year, last_year):
    """Keep the items of tile hXXvYY whose composite starts in [first_year, last_year];
    when the mirror holds two productions of one composite keep the newest (id suffix).
    Returns (kept items sorted by platform and start, number of duplicates dropped)."""
    best = {}
    for it in items:
        p = it["properties"]
        # platform from the product name in the id: one Terra item (MOD21A2.A2003041.h29v11) has platform ''
        plat = PLATFORM_BY_PRODUCT.get(it["id"].split(".")[0])
        if plat and p.get("platform") != plat:
            p["platform_stac"] = p.get("platform")
            p["platform"] = plat
        if (p.get("modis:horizontal-tile"), p.get("modis:vertical-tile")) != (h, v):
            continue
        y = int(p["start_datetime"][:4])
        if not (first_year <= y <= last_year):
            continue
        key = (p["platform"], p["start_datetime"][:10])
        if key not in best or it["id"].split(".")[-1] > best[key]["id"].split(".")[-1]:
            best[key] = it
    dup = sum(1 for it in items
              if (it["properties"].get("modis:horizontal-tile"), it["properties"].get("modis:vertical-tile")) == (h, v)
              and first_year <= int(it["properties"]["start_datetime"][:4]) <= last_year) - len(best)
    return [best[k] for k in sorted(best)], dup


class SasToken:
    """SAS token for modiseuwest/modis-061-cogs, refreshed 10 minutes before it expires."""

    def __init__(self):
        self.lock = threading.Lock()
        self.token, self.expiry = None, 0.0
        self.fetches = 0

    def get(self, force=False):
        with self.lock:
            if force or self.token is None or time.time() > self.expiry - 600:
                d = get_json(SAS_URL)
                self.token = d["token"]
                exp = d.get("msft:expiry")
                try:
                    import datetime
                    self.expiry = datetime.datetime.fromisoformat(exp.replace("Z", "+00:00")).timestamp()
                except Exception:
                    self.expiry = time.time() + 1800
                self.fetches += 1
            return self.token

    def sign(self, href):
        return href + ("&" if "?" in href else "?") + self.get()


# ----------------------------------------------------------------------------------------------
# MODIS sinusoidal grid

def sinusoidal(lat, lon):
    phi, lam = math.radians(lat), math.radians(lon)
    return R_SIN * lam * math.cos(phi), R_SIN * phi


def modis_tile(lat, lon, n=1200):
    """(h, v, row, col) of the MODIS sinusoidal pixel (n x n per tile; 1200 = 1 km) holding lat/lon."""
    x, y = sinusoidal(lat, lon)
    gx = x + 18 * TILE_M
    gy = 9 * TILE_M - y
    h, v = int(gx // TILE_M), int(gy // TILE_M)
    px = TILE_M / n
    col = int((gx - h * TILE_M) // px)
    row = int((gy - v * TILE_M) // px)
    return h, v, row, col


def pixel_centre(h, v, row, col, n=1200):
    """lat, lon of the centre of pixel (row, col) of tile hXXvYY (n x n pixels per tile)."""
    px = TILE_M / n
    x = h * TILE_M + (col + 0.5) * px - 18 * TILE_M
    y = 9 * TILE_M - (v * TILE_M + (row + 0.5) * px)
    lat = math.degrees(y / R_SIN)
    lon = math.degrees(x / (R_SIN * math.cos(math.radians(lat))))
    return lat, lon


def tile_name(h, v):
    return "h%02dv%02d" % (h, v)


# ----------------------------------------------------------------------------------------------
# Cloud Optimized GeoTIFF range reader (classic little-endian TIFF, tiled, DEFLATE, predictor 1)

TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8, 17: 8, 18: 8}
TYPE_FMT = {1: "B", 3: "H", 4: "I", 6: "b", 7: "B", 8: "h", 9: "i", 11: "f", 12: "d", 16: "Q", 17: "q", 18: "Q"}


def get_range(url, a, b, sas=None):
    """Bytes a..b (inclusive) of a blob; refreshes the SAS token once on HTTP 403."""
    for attempt in range(2):
        try:
            return request(url, headers={"Range": "bytes=%d-%d" % (a, b)}, timeout=20, tries=10)[1]
        except HTTPStatusError as e:
            if e.status == 403 and sas is not None and attempt == 0:
                base = url.split("?")[0]
                url = base + "?" + sas.get(force=True)
                continue
            raise


class RemoteCOG:
    def __init__(self, href, sas, head_bytes=16384):
        self.href, self.sas = href, sas
        url = sas.sign(href)
        d = get_range(url, 0, head_bytes - 1, sas)
        if d[:2] != b"II":
            raise ValueError("expected a little-endian classic TIFF")
        magic, ifd = struct.unpack("<HI", d[2:8])
        if magic != 42:
            raise ValueError("BigTIFF is not handled")
        if ifd + 2 > len(d):
            d = d + get_range(url, len(d), ifd + 4096, sas)
        n = struct.unpack("<H", d[ifd:ifd + 2])[0]
        if ifd + 2 + 12 * n > len(d):
            d = d + get_range(url, len(d), ifd + 2 + 12 * n + 4096, sas)
        tags = {}
        for i in range(n):
            e = ifd + 2 + 12 * i
            tag, typ, cnt = struct.unpack("<HHI", d[e:e + 8])
            size = TYPE_SIZES.get(typ, 1) * cnt
            if size <= 4:
                raw = d[e + 8:e + 8 + size]
            else:
                off = struct.unpack("<I", d[e + 8:e + 12])[0]
                raw = d[off:off + size] if off + size <= len(d) else get_range(url, off, off + size - 1, sas)
            if typ == 2:
                tags[tag] = raw.rstrip(b"\0").decode("latin-1")
            elif typ in TYPE_FMT:
                tags[tag] = list(struct.unpack("<" + TYPE_FMT[typ] * cnt, raw))
        self.tags = tags
        self.w, self.h = tags[256][0], tags[257][0]
        self.tw, self.th = tags[322][0], tags[323][0]
        self.offsets, self.counts = tags[324], tags[325]
        self.bits = tags[258][0]
        self.comp = tags[259][0]
        self.pred = tags.get(317, [1])[0]
        self.across = (self.w + self.tw - 1) // self.tw
        self.tc = {8: "B", 16: "H"}[self.bits]
        self.sx = tags[33550][0]
        tp = tags[33922]
        self.x0, self.y0 = tp[3], tp[4]

    def read_tile(self, tr, tc):
        """Decoded internal tile (tr, tc) as a flat array of th*tw values (row-major)."""
        i = tr * self.across + tc
        off, cnt = self.offsets[i], self.counts[i]
        if cnt == 0:   # sparse tile: all nodata
            return array.array(self.tc, bytes(self.tw * self.th * self.bits // 8))
        raw = get_range(self.sas.sign(self.href), off, off + cnt - 1, self.sas)
        if self.comp in (8, 32946):
            raw = zlib.decompress(raw)
        elif self.comp != 1:
            raise ValueError("compression %d is not handled" % self.comp)
        if self.pred != 1:
            raise ValueError("predictor %d is not handled" % self.pred)
        a = array.array(self.tc)
        a.frombytes(raw[:self.tw * self.th * self.bits // 8])
        if sys.byteorder == "big":
            a.byteswap()
        return a

    def pixel(self, row, col):
        t = self.read_tile(row // self.th, col // self.tw)
        return t[(row % self.th) * self.tw + (col % self.tw)]

    def rowcol(self, lat, lon):
        x, y = sinusoidal(lat, lon)
        return int((self.y0 - y) // self.sx), int((x - self.x0) // self.sx)


# ----------------------------------------------------------------------------------------------
# MOD21A2 QC rule (MOD21 C6.1 user guide, Table 13: QC_Day / QC_Night of MxD21A2; bit 0 = LSB)
#   bits 1-0 mandatory QA : 00 produced, good quality; 01 produced, nominal ("other") quality;
#                           10 not produced, cloud; 11 not produced, other reasons
#   bits 3-2 data quality : 00 good L1B data; 01 missing pixel; 10 fairly calibrated; 11 poorly calibrated
#   bits 5-4 emissivity accuracy: 00 >0.02; 01 0.015-0.02; 10 0.01-0.015; 11 <0.01
#   bits 7-6 LST accuracy : 00 >2 K (poor); 01 1.5-2 K (marginal); 10 1-1.5 K (good); 11 <1 K (excellent)
# Accepted: LST not fill (0) AND bits 1-0 in {00, 01} AND bits 7-6 in {01, 10, 11} (LST error <= 2 K).
# Bits 3-2 and 5-4 are not used (as in the MOD11 'standard' rule this mirrors).

QC_RULE = ("A value is used when LST is not the fill value 0 and its QC byte (MOD21 C6.1 user guide, "
           "Table 13, bit 0 = least significant) has mandatory QA bits 1-0 = 00 (produced, good quality) "
           "or 01 (produced, nominal/other quality) AND LST accuracy bits 7-6 = 01 (1.5-2 K), 10 (1-1.5 K) "
           "or 11 (<1 K), i.e. the estimated LST error is at most 2 K; bits 7-6 = 00 (>2 K, poor) and "
           "mandatory 10 (cloud) / 11 (other) are rejected. Bits 3-2 (L1B data quality) and 5-4 "
           "(emissivity accuracy) are not used. This mirrors the MOD11 'standard' rule (good or other "
           "quality with LST error <= 2 K); note the MOD21 bits 7-6 run the other way from MOD11's.")


def qc_ok(qc):
    qc = int(qc)
    return (qc & 3) in (0, 1) and ((qc >> 6) & 3) >= 1


QC_TABLE = bytes(1 if qc_ok(q) else 0 for q in range(256))

LST_SCALE = 0.02
K0 = 273.15
VIEW_TIME_SCALE = 0.1
VIEW_TIME_FILL = 255


def lst_c(raw):
    return raw * LST_SCALE - K0
