"""fetch_emit.py - NASA EMIT L2B mineral identification at Analog Atlas sites and Jordan boxes.

Python 3.12 standard library only. Run from the project root:

    python -I scripts/fetch_emit.py                 # sites + all Jordan boxes
    python -I scripts/fetch_emit.py --sites-only
    python -I scripts/fetch_emit.py --box-limit 50  # sites + first 50 boxes (test)
    python -I scripts/fetch_emit.py --token-file path\\to\\my_token.txt

Needs a free NASA Earthdata Login user token (https://urs.earthdata.nasa.gov -> Generate Token)
saved in a text file (default: earthdata_token.txt in the project root, gitignored). The token is
read at run time, sent only as an 'Authorization: Bearer' header to *.earthdata.nasa.gov /
*.earthdatacloud.nasa.gov hosts, and never printed or written anywhere.

Data: EMIT L2B Estimated Mineral Identification and Band Depth and Uncertainty 60 m, V001
(10.5067/EMIT/EMITL2BMIN.001) and V002 (10.5067/EMIT/EMITL2BMIN.002), plus the matching EMIT L2A
Masks (V002 for V001-era granule names, V003 for V002 names) for cloud and water screening.
Only the HDF5 chunks under each window are fetched with HTTP Range requests, located through
the LP DAAC DMR++ sidecars (cached gzipped in data/raw/emit/dmrpp/).

Writes data/emit.json, data/screening_emit.json, data/raw/emit/manifest.json,
data/raw/emit/site_windows.json.
"""
import argparse
import datetime as dt
import gzip
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import emit_dmrpp  # noqa: E402
import emit_http  # noqa: E402
import emit_minerals  # noqa: E402

DATA = os.path.join(ROOT, 'data')
RAW = os.path.join(DATA, 'raw', 'emit')
DMRPP_CACHE = os.path.join(RAW, 'dmrpp')
MATRIX = os.path.join(RAW, 'mineral_grouping_matrix_20230503.csv')
MATRIX_URL = 'https://github.com/emit-sds/emit-sds-l2b/blob/develop/data/mineral_grouping_matrix_20230503.csv'

CMR = 'https://cmr.earthdata.nasa.gov/search/granules.json'
COLL = {'MIN001': 'C2408034484-LPCLOUD', 'MIN002': 'C4079846859-LPCLOUD',
        'MASK002': 'C3882545269-LPCLOUD', 'MASK003': 'C4279547358-LPCLOUD'}
SITE_HALF = 2        # 5 x 5 GLT cells (60 m) = 300 m
BOX_HALF = 8         # 17 x 17 GLT cells ~ 1 km
MAX_SITE_GRANULES = 5
MIN_VALID = 0.5      # a window needs >= 50 % cloud-free, in-swath cells to count
SIGMA = 2.0          # "above 2 sigma": band depth >= 2 x band depth uncertainty
MIN_SHARE = 0.2      # a granule reports a dominant mineral only if it covers >= 20 % of the valid cells
EMIT10 = set(emit_minerals.EMIT10)
# Cloud screening. The EMIT L2A Mask ATBD (emit-sds-masks, EMIT_L2A_Mask_ATBD.md, Section 3) notes the legacy
# threshold Cloud Flag gives "false positive detections above bright surface features (e.g. desert and snow)";
# the SpecTf-Cloud Flag (probability > 0.51) is the spectral model flag. So when SpecTf is in the mask file we use
# SpecTf + Cirrus (+ Spacecraft where present) and only report the legacy flag; otherwise the legacy flags.
CLOUD_BANDS = ('SpecTf-Cloud Flag', 'Cirrus Flag', 'Spacecraft Flag')
LEGACY_CLOUD_BANDS = ('Cloud Flag', 'Dilated Cloud Flag', 'Aggregate Flag')
WATER_BAND = 'Water Flag'
OUTSIDE = {'haughton', 'dry-valleys', 'holuhraun', 'mistastin'}


def log(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------------------- CMR (public)
def cmr_all(params):
    out, page = [], 1
    while True:
        q = dict(params, page_size=2000, page_num=page)
        url = CMR + '?' + urllib.parse.urlencode(q)
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=120) as r:
                    ents = json.load(r)['feed']['entry']
                break
            except OSError:
                time.sleep(3 + 5 * attempt)
        else:
            raise IOError('CMR unreachable')
        out += ents
        if len(ents) < 2000:
            return out
        page += 1


def parse_polys(e):
    polys = []
    for p in e.get('polygons') or []:
        nums = [float(v) for v in p[0].split()]
        polys.append(list(zip(nums[0::2], nums[1::2])))   # (lat, lon)
    return polys


def in_poly(lat, lon, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        y1, x1 = poly[i]
        y2, x2 = poly[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if x > lon:
                inside = not inside
    return inside


def stem_of(title):
    # EMIT_L2B_MIN_001_20220810T064957_2222205_033 -> 20220810T064957_2222205_033
    parts = title.split('_')
    return '_'.join(parts[4:])


def granule_records(params):
    """MIN V001 + V002 granules (deduplicated by acquisition time, V002 preferred) with masks."""
    recs = {}
    for key in ('MIN001', 'MIN002'):
        for e in cmr_all(dict(params, collection_concept_id=COLL[key])):
            links = [l['href'] for l in e.get('links', []) if l['href'].startswith('https://data.lpdaac')]
            mn = [u for u in links if '/EMIT_L2B_MIN_' in u and u.endswith('.nc')]
            un = [u for u in links if '/EMIT_L2B_MINUNCERT_' in u and u.endswith('.nc')]
            if not mn or not un:
                continue
            ts = stem_of(e['title'])[:15]
            r = {'title': e['title'], 'cid': e['id'], 'version': key[-3:], 'ts': ts,
                 'date': dt.datetime.strptime(ts, '%Y%m%dT%H%M%S').strftime('%Y-%m-%d'),
                 'cloud': float(e['cloud_cover']) if e.get('cloud_cover') not in (None, '') else 100.0,
                 'min': mn[0], 'unc': un[0], 'polys': parse_polys(e), 'stem': stem_of(e['title']), 'mask': None}
            if ts not in recs or r['version'] > recs[ts]['version']:
                recs[ts] = r
    masks = {}
    for key in ('MASK002', 'MASK003'):
        for e in cmr_all(dict(params, collection_concept_id=COLL[key])):
            links = [l['href'] for l in e.get('links', []) if l['href'].startswith('https://data.lpdaac')]
            nc = [u for u in links if '/EMIT_L2A_MASK_' in u and u.endswith('.nc')]
            if nc:
                masks[stem_of(e['title'])] = {'title': e['title'], 'cid': e['id'], 'url': nc[0]}
    for r in recs.values():
        r['mask'] = masks.get(r['stem'])
    return list(recs.values())


# ------------------------------------------------------------------------------- granule access
def fetch_dmrpp(url):
    name = url.rsplit('/', 1)[1] + '.dmrpp.gz'
    path = os.path.join(DMRPP_CACHE, name)
    if os.path.exists(path):
        with gzip.open(path, 'rt', encoding='latin-1') as f:
            return f.read(), 0
    for u in (url + '.dmrpp', url.replace('/lp-prod-protected/', '/lp-prod-public/') + '.dmrpp'):
        st, b = emit_http.get(u)
        if st == 200 and b:
            os.makedirs(DMRPP_CACHE, exist_ok=True)
            with gzip.open(path, 'wb', compresslevel=9) as f:
                f.write(b)
            return b.decode('latin-1'), len(b)
    raise IOError('no DMR++ for %s (HTTP %s)' % (url.rsplit('/', 1)[1], st))


class Granule:
    def __init__(self, rec, matrix):
        self.rec = rec
        self.sidecar_bytes = 0
        urls = [rec['min'], rec['unc']] + ([rec['mask']['url']] if rec['mask'] else [])

        def safe(u):
            try:
                return fetch_dmrpp(u)
            except IOError as e:
                return e
        with ThreadPoolExecutor(3) as ex:
            got = list(ex.map(safe, urls))
        for x in got[:2]:
            if isinstance(x, Exception):
                raise x
        t, n = got[0]
        self.sidecar_bytes += n
        self.m = emit_dmrpp.Dataset(t, lambda o, k, u=rec['min']: self._get(u, o, k))
        t, n = got[1]
        self.sidecar_bytes += n
        self.q = emit_dmrpp.Dataset(t, lambda o, k, u=rec['unc']: self._get(u, o, k))
        self.k = None
        self.mask_bands = {}
        self.cloud_names = []
        if rec['mask']:
            try:
                if isinstance(got[2], Exception):
                    raise got[2]
                t, n = got[2]
                self.sidecar_bytes += n
                self.k = emit_dmrpp.Dataset(t, lambda o, k, u=rec['mask']['url']: self._get(u, o, k))
                names = self.k.read_1d(next(v for v in self.k.vars if v.split('/')[-1] == 'mask_bands'))
                self.mask_bands = {nm: i for i, nm in enumerate(names)}
            except (IOError, StopIteration, KeyError) as e:
                log('   mask unavailable:', e)
                self.k = None
        self.same_swath = bool(self.k) and self.k.dims.get('downtrack') == self.m.dims.get('downtrack') and \
            self.k.dims.get('crosstrack') == self.m.dims.get('crosstrack')
        self.lut, self.lut_mismatch = emit_minerals.granule_lut(self.m, *matrix)
        self.gt = self.m.geotransform()

    @staticmethod
    def _get(u, o, k):
        st, b = emit_http.get(u, o, k)
        if st not in (200, 206):
            raise IOError('HTTP %s on range read' % st)
        return b

    def bytes_read(self):
        return self.m.bytes_read + self.q.bytes_read + (self.k.bytes_read if self.k else 0) + self.sidecar_bytes

    def close(self):
        for d in (self.m, self.q, self.k):
            if d:
                d.drop_cache()

    def cells(self, lat, lon, half):
        """GLT window centred on lat/lon -> list of (glt_row, glt_col, swath_row|None, swath_col|None)."""
        gt = self.gt
        col = int(math.floor((lon - gt[0]) / gt[1]))
        row = int(math.floor((lat - gt[3]) / gt[5]))
        ny, nx = self.m.dims['ortho_y'], self.m.dims['ortho_x']
        win = [(r, c) for r in range(row - half, row + half + 1) for c in range(col - half, col + half + 1)]
        gx = self.m.vars['location/glt_x']
        self.m.prefetch([(n, gx.chunk_key((r, c))) for r, c in win if 0 <= r < ny and 0 <= c < nx
                         for n in ('location/glt_x', 'location/glt_y')])
        out = []
        for r, c in win:
            x = self.m.value('location/glt_x', r, c)
            y = self.m.value('location/glt_y', r, c)
            if x is None or y is None or x <= 0 or y <= 0:
                out.append((r, c, None, None))
            else:
                out.append((r, c, int(y) - 1, int(x) - 1))
        return out

    def classify(self, cells):
        """Per window cell: dict with status in {'nodata','cloud','water','ok'} and group values."""
        sw = [(r, c) for _, _, r, c in cells if r is not None]
        mv = ['group_1_mineral_id', 'group_1_band_depth', 'group_2_mineral_id', 'group_2_band_depth']
        qv = ['group_1_band_depth_unc', 'group_1_fit', 'group_2_band_depth_unc', 'group_2_fit']
        jobs = self.m.missing([(n, self.m.vars[n].chunk_key(p)) for p in sw for n in mv]) + \
            self.q.missing([(n, self.q.vars[n].chunk_key(p)) for p in sw for n in qv])
        cloud_names = CLOUD_BANDS if 'SpecTf-Cloud Flag' in self.mask_bands else CLOUD_BANDS + LEGACY_CLOUD_BANDS
        self.cloud_names = [nm for nm in cloud_names if nm in self.mask_bands]
        mband = [(nm, i) for nm, i in self.mask_bands.items()
                 if nm in cloud_names or nm == WATER_BAND or nm == 'Cloud Flag']
        mask_pos = {}
        if self.k:
            for gr, gc, r, c in cells:
                if r is None:
                    continue
                if self.same_swath:
                    mask_pos[(gr, gc)] = (r, c)
                else:   # different swath geometry: use the mask file's own GLT at the cell centre
                    lat = self.gt[3] + (gr + 0.5) * self.gt[5]
                    lon = self.gt[0] + (gc + 0.5) * self.gt[1]
                    kg = self.k.geotransform()
                    kr = int(math.floor((lat - kg[3]) / kg[5]))
                    kc = int(math.floor((lon - kg[0]) / kg[1]))
                    x = self.k.value('location/glt_x', kr, kc)
                    y = self.k.value('location/glt_y', kr, kc)
                    if x and y and x > 0 and y > 0:
                        mask_pos[(gr, gc)] = (int(y) - 1, int(x) - 1)
            mvar = self.k.vars['mask']
            jobs += self.k.missing([('mask', mvar.chunk_key((p[0], p[1], i))) for p in mask_pos.values() for _, i in mband])
        emit_dmrpp.prefetch_many(jobs)
        res = []
        for gr, gc, r, c in cells:
            if r is None:
                res.append({'status': 'nodata'})
                continue
            st = 'ok'
            if (gr, gc) in mask_pos:
                p = mask_pos[(gr, gc)]
                flags = {nm: self.k.value('mask', p[0], p[1], i) for nm, i in mband}
                if (flags.get(WATER_BAND) or 0) >= 0.5:
                    st = 'water'
                elif any((flags.get(nm) or 0) >= 0.5 for nm in self.cloud_names):
                    st = 'cloud'
                legacy = (flags.get('Cloud Flag') or 0) >= 0.5
            else:
                legacy = False
            d = {'status': st, 'legacyCloud': legacy}
            for g in (1, 2):
                mid = self.m.value('group_%d_mineral_id' % g, r, c)
                bd = self.m.value('group_%d_band_depth' % g, r, c)
                un = self.q.value('group_%d_band_depth_unc' % g, r, c)
                ft = self.q.value('group_%d_fit' % g, r, c)
                if mid is None or mid == -9999 or bd is None or bd == -9999 or bd != bd:
                    d['g%d' % g] = None          # fill: no data for this group
                else:
                    d['g%d' % g] = (int(mid), float(bd),
                                    None if un is None or un == -9999 or un != un else float(un),
                                    None if ft is None or ft == -9999 or ft != ft else float(ft))
            if st == 'ok' and d['g1'] is None and d['g2'] is None:
                d['status'] = 'nodata'
            res.append(d)
        return res


# ------------------------------------------------------------------------------- statistics
def rnd(x, n):
    return None if x is None else round(x, n)


def group_stats(cls, lut, g):
    valid = [d['g%d' % g] for d in cls if d['status'] == 'ok' and d['g%d' % g] is not None]
    nvalid = len(valid)
    out = {'validCells': nvalid}
    if not nvalid:
        out.update({'mineral': None})
        return out, Counter()
    det = [v for v in valid if v[0] > 0]
    fam = defaultdict(list)
    for v in det:
        info = lut.get(v[0])
        fam[info['family'] if info else 'id%d' % v[0]].append(v)
    ids = Counter(v[0] for v in det)
    out['noDetectionShare'] = rnd((nvalid - len(det)) / nvalid, 2)
    if not det:
        out['mineral'] = None
        return out, ids
    best = max(fam, key=lambda f: (len(fam[f]), sum(v[1] for v in fam[f])))
    core = [f for f in fam if f in EMIT10]
    if core:
        cb = max(core, key=lambda f: (len(fam[f]), sum(v[1] for v in fam[f])))
        if len(fam[cb]) / nvalid >= MIN_SHARE:
            out['coreMineral'] = cb
            out['coreShare'] = rnd(len(fam[cb]) / nvalid, 2)
    if len(fam[best]) / nvalid < MIN_SHARE:
        # scattered detections only: no dominant mineral, keep the largest one for transparency
        out['mineral'] = None
        out['sparse'] = [[f, rnd(len(v) / nvalid, 2)] for f, v in sorted(fam.items(), key=lambda kv: -len(kv[1]))][:3]
        return out, ids
    vs = fam[best]
    uns = [v[2] for v in vs if v[2] is not None]
    fts = [v[3] for v in vs if v[3] is not None]
    lib = Counter(v[0] for v in vs).most_common(1)[0][0]
    info = lut.get(lib, {})
    strong = [v for v in vs if v[2] is not None and v[1] >= SIGMA * v[2]]
    out.update({
        'mineral': best, 'class': info.get('class'),
        'share': rnd(len(vs) / nvalid, 2),
        'meanBandDepth': rnd(sum(v[1] for v in vs) / len(vs), 4),
        'meanBandDepthUnc': rnd(sum(uns) / len(uns), 4) if uns else None,
        'meanFit': rnd(sum(fts) / len(fts), 3) if fts else None,
        'above2Sigma': rnd(len(strong) / len(vs), 2),
        'library': info.get('sample'),
        'others': [[f, rnd(len(v) / nvalid, 2)] for f, v in sorted(fam.items(), key=lambda kv: -len(kv[1]))
                   if f != best and len(v) / nvalid >= 0.05][:3],
    })
    return out, ids


def window_summary(gran, lat, lon, half):
    cells = gran.cells(lat, lon, half)
    cls = gran.classify(cells)
    n = len(cls)
    st = Counter(d['status'] for d in cls)
    g1, ids1 = group_stats(cls, gran.lut, 1)
    g2, ids2 = group_stats(cls, gran.lut, 2)
    veg = sum(1 for d in cls if d['status'] == 'ok' and d['g2'] and d['g2'][0] > 0 and
              gran.lut.get(d['g2'][0], {}).get('class') == 'vegetation')
    return {'cells': n, 'validShare': rnd(st['ok'] / n, 2), 'cloudShare': rnd(st['cloud'] / n, 2),
            'legacyCloudFlagShare': rnd(sum(1 for d in cls if d.get('legacyCloud')) / n, 2),
            'cloudFlagsUsed': list(getattr(gran, 'cloud_names', [])),
            'waterShare': rnd(st['water'] / n, 2), 'noDataShare': rnd(st['nodata'] / n, 2),
            'dryVegShare': rnd(veg / max(1, st['ok']), 2), 'g1': g1, 'g2': g2,
            'maskUsed': bool(gran.k)}, {'g1': dict(ids1), 'g2': dict(ids2)}


# ------------------------------------------------------------------------------- selection
def season(ts, lat):
    m = int(ts[4:6])
    s = {12: 'DJF', 1: 'DJF', 2: 'DJF', 3: 'MAM', 4: 'MAM', 5: 'MAM', 6: 'JJA', 7: 'JJA', 8: 'JJA'}.get(m, 'SON')
    return s


def order_candidates(cands, lat):
    """Lowest CMR cloud first, but spread over seasons/dates (penalty for repeats)."""
    left = sorted(cands, key=lambda r: (r['cloud'], -int(r['version']), r['ts']))
    picked = []
    while left:
        def score(r):
            same_season = sum(1 for p in picked if season(p['ts'], lat) == season(r['ts'], lat))
            same_day = sum(1 for p in picked if p['ts'][:8] == r['ts'][:8])
            return r['cloud'] + 25 * same_season + 100 * same_day
        b = min(left, key=score)
        picked.append(b)
        left.remove(b)
    return picked


# ------------------------------------------------------------------------------- site run
def load_json(name):
    with open(os.path.join(DATA, name), encoding='utf-8') as f:
        return json.load(f)


def site_summary(granules):
    usable = [g for g in granules if g['validShare'] >= MIN_VALID]
    m = len(usable)
    summ = {'granulesUsed': m}
    for key in ('g1', 'g2'):
        dom = Counter(g[key]['mineral'] for g in usable if g[key].get('mineral'))
        present = Counter()
        for g in usable:
            fams = {g[key]['mineral']} | {o[0] for o in g[key].get('others', [])} if g[key].get('mineral') else set()
            for f in fams:
                present[f] += 1
        core = Counter(g[key]['coreMineral'] for g in usable if g[key].get('coreMineral'))
        core_s = None
        if core:
            cb = max(core, key=lambda f: (core[f], sum(g[key].get('coreShare', 0) for g in usable if g[key].get('coreMineral') == f)))
            core_s = {'mineral': cb, 'agree': '%d of %d granules' % (core[cb], m)}
        if not dom:
            summ[key] = {'mineral': None, 'agree': ('no dominant mineral (>= %d %% of valid cells) in %d of %d granules'
                                                    % (MIN_SHARE * 100, m, m)) if m else 'no usable granule'}
            if core_s:
                summ[key]['core'] = core_s
            continue
        best = max(dom, key=lambda f: (dom[f], sum(g[key]['share'] for g in usable if g[key].get('mineral') == f)))
        mine = [g[key] for g in usable if g[key].get('mineral') == best]
        a2 = [x['above2Sigma'] for x in mine if x.get('above2Sigma') is not None]
        summ[key] = {'mineral': best, 'class': mine[0].get('class'),
                     'agree': '%d of %d granules' % (dom[best], m), 'nDominant': dom[best],
                     'meanShare': rnd(sum(x['share'] for x in mine) / len(mine), 2),
                     'meanBandDepth': rnd(sum(x['meanBandDepth'] for x in mine) / len(mine), 4),
                     'above2Sigma': rnd(sum(a2) / len(a2), 2) if a2 else None,
                     'strength': ('clear' if a2 and sum(a2) / len(a2) >= 0.5 else 'weak'),
                     'seen': {f: c for f, c in dom.most_common()},
                     'presentIn': {f: c for f, c in present.most_common(6)}}
        if core_s:
            summ[key]['core'] = core_s
    return summ


def site_flags(granules, summ):
    fl = []
    if summ['granulesUsed'] == 0:
        fl.append('noUsableGranule')
    elif summ['granulesUsed'] < 3:
        fl.append('fewGranules')
    if any(g['waterShare'] >= 0.2 for g in granules):
        fl.append('water')
    if any(g['cloudShare'] > 0 for g in granules):
        fl.append('cloudPixelsRemoved')
    if any(g['dryVegShare'] >= 0.2 for g in granules if g['validShare'] >= MIN_VALID):
        fl.append('dryVegetation')
    for key in ('g1', 'g2'):
        s = summ.get(key, {})
        if s.get('mineral') and s.get('strength') == 'weak':
            fl.append(key + 'Weak')
        if s.get('class') == 'artificial':
            fl.append(key + 'ManMade')
    if len({g['version'] for g in granules}) > 1:
        fl.append('mixedVersions')
    if any(not g['maskUsed'] for g in granules):
        fl.append('someGranulesWithoutMask')
    return fl


def run_sites(matrix, manifest, windows_raw, mineral_seen, only=None):
    meta = load_json('sites_meta.json')['sites']
    places = {}
    for s in meta:
        sid = s['id']
        if sid in OUTSIDE or abs(s['lat']) > 52 or (only and sid not in only):
            continue
        lat, lon = s['lat'], s['lon']
        log('[site] %s (%.3f, %.3f)' % (sid, lat, lon))
        recs = granule_records({'point': '%s,%s' % (lon, lat)})
        recs = [r for r in recs if any(in_poly(lat, lon, p) for p in r['polys'])] or recs
        cands = order_candidates(recs, lat)
        log('   %d candidate acquisitions (V002 for %d)' % (len(cands), sum(1 for r in cands if r['version'] == '002')))
        out, skipped, tried = [], [], 0
        for r in cands:
            if len(out) >= MAX_SITE_GRANULES or tried >= 12:
                break
            tried += 1
            t0 = time.time()
            try:
                g = Granule(r, matrix)
                w, raw_ids = window_summary(g, lat, lon, SITE_HALF)
            except (IOError, KeyError, ValueError) as e:
                log('   ! %s: %s' % (r['title'], e))
                skipped.append({'id': r['title'], 'reason': 'read error: %s' % type(e).__name__})
                continue
            nb = g.bytes_read()
            for i in set(raw_ids['g1']) | set(raw_ids['g2']):
                mineral_seen[r['version']][i] = g.lut.get(i)
            manifest.append({'granule': r['title'], 'conceptId': r['cid'], 'version': r['version'], 'use': 'site:' + sid,
                             'min': r['min'], 'unc': r['unc'], 'mask': r['mask']['title'] if r['mask'] else None,
                             'maskSameSwath': g.same_swath, 'bytes': nb, 'seconds': round(time.time() - t0, 1),
                             'libraryNameMismatches': g.lut_mismatch})
            g.close()
            rec = {'id': r['title'], 'version': r['version'], 'date': r['date'], 'cloudPct': r['cloud']}
            rec.update(w)
            log('   %s cloud=%s valid=%.2f g1=%s g2=%s (%.1f MB, %.0fs)' % (
                r['title'], r['cloud'], w['validShare'], w['g1'].get('mineral'), w['g2'].get('mineral'), nb / 1e6, time.time() - t0))
            windows_raw.setdefault(sid, []).append({'granule': r['title'], 'idCounts': raw_ids})
            if w['validShare'] < MIN_VALID:
                skipped.append({'id': r['title'], 'date': r['date'], 'reason': 'validShare %.2f < %.2f (cloud %.2f, water %.2f, no data %.2f)' % (
                    w['validShare'], MIN_VALID, w['cloudShare'], w['waterShare'], w['noDataShare'])})
                if w['waterShare'] >= MIN_VALID:   # a water site stays water: keep the record
                    out.append(rec)
                continue
            out.append(rec)
        summ = site_summary(out)
        places[sid] = {'name': s.get('name'), 'lat': lat, 'lon': lon, 'rockType': s['geology'].get('primary'),
                       'candidates': len(cands), 'granules': out, 'skipped': skipped, 'summary': summ}
        places[sid]['flags'] = site_flags(out, summ)
    return places


# ------------------------------------------------------------------------------- boxes
def run_boxes(matrix, manifest, limit, mineral_seen, deadline):
    scr = load_json('screening_jordan.json')
    boxes = scr['boxes'][:limit] if limit else scr['boxes']
    g = scr['grid']
    log('[boxes] %d boxes; CMR search over the Jordan grid' % len(boxes))
    recs = granule_records({'bounding_box': '%s,%s,%s,%s' % (g['west'], g['south'], g['east'], g['north'])})
    log('   %d acquisitions over Jordan (V002 for %d)' % (len(recs), sum(1 for r in recs if r['version'] == '002')))
    cover = {b['id']: sorted([r for r in recs if any(in_poly(b['lat'], b['lon'], p) for p in r['polys'])],
                             key=lambda r: (r['cloud'], -int(r['version']), r['ts'])) for b in boxes}
    results, tried = {}, defaultdict(set)
    byid = {b['id']: b for b in boxes}

    def good(w):
        return w['validShare'] >= MIN_VALID or w['waterShare'] >= MIN_VALID

    for rnd_i in range(3):
        need = [bid for bid in byid if not (bid in results and good(results[bid]))
                and any(r['title'] not in tried[bid] for r in cover[bid])]
        if not need:
            break
        # assign each box to its clearest untried granule; among equally clear ones (within 2 %
        # CMR cloud) prefer the granule that serves the most boxes, to limit downloads
        options = {}
        for bid in need:
            c = [r for r in cover[bid] if r['title'] not in tried[bid]]
            lo = c[0]['cloud']
            options[bid] = [r for r in c if r['cloud'] <= lo + 2]
        pop = Counter(r['title'] for opts in options.values() for r in opts)
        assign = defaultdict(list)
        recmap = {}
        for bid, opts in options.items():
            r = max(opts, key=lambda r: (pop[r['title']], int(r['version']), -r['cloud']))
            assign[r['title']].append(bid)
            recmap[r['title']] = r
        log('   round %d: %d boxes over %d granules' % (rnd_i + 1, len(need), len(assign)))
        for k, (title, bids) in enumerate(sorted(assign.items(), key=lambda kv: -len(kv[1]))):
            if time.time() > deadline:
                log('   time budget reached; stopping box processing')
                return results, boxes, recs
            r = recmap[title]
            t0 = time.time()
            for bid in bids:
                tried[bid].add(title)
            try:
                gr = Granule(r, matrix)
            except (IOError, KeyError, ValueError) as e:
                log('   ! %s: %s' % (title, e))
                continue
            for bid in bids:
                b = byid[bid]
                try:
                    w, raw_ids = window_summary(gr, b['lat'], b['lon'], BOX_HALF)
                except (IOError, KeyError, ValueError) as e:
                    log('   ! box %s: %s' % (bid, e))
                    continue
                for i in set(raw_ids['g1']) | set(raw_ids['g2']):
                    mineral_seen[r['version']][i] = gr.lut.get(i)
                w.update({'granule': title, 'version': r['version'], 'date': r['date'], 'cloudPct': r['cloud']})
                if bid not in results or good(w) or w['validShare'] > results[bid]['validShare']:
                    results[bid] = w
            nb = gr.bytes_read()
            gr.close()
            manifest.append({'granule': title, 'conceptId': r['cid'], 'version': r['version'], 'use': 'boxes:%d' % len(bids),
                             'min': r['min'], 'unc': r['unc'], 'mask': r['mask']['title'] if r['mask'] else None,
                             'maskSameSwath': gr.same_swath, 'bytes': nb, 'seconds': round(time.time() - t0, 1),
                             'libraryNameMismatches': gr.lut_mismatch})
            log('   [%d/%d] %s: %d boxes, %.1f MB, %.0fs' % (k + 1, len(assign), title, len(bids), nb / 1e6, time.time() - t0))
    return results, boxes, recs


# ------------------------------------------------------------------------------- checks
EXPECT = {
    'sandstone': ('g1', {'Hematite', 'Goethite'}, 'red sandstone: ferric iron oxide coatings (hematite/goethite) expected in the 1 um group'),
    'evaporite': ('g2', {'Gypsum', 'Calcite', 'Aragonite', 'Dolomite'}, 'evaporite/marl: gypsum or carbonates (calcite/aragonite) expected in the 2 um group'),
    'carbonate': ('g2', {'Calcite', 'Dolomite'}, 'limestone/chalk: calcite or dolomite expected in the 2 um group'),
    'mudstone': ('g2', {'Kaolinite', 'Montmorillonite', 'Illite+Muscovite', 'Chlorite', 'Calcite', 'Gypsum'},
                 'mudflat/mudstone: clays, often with calcite or gypsum, expected in the 2 um group'),
    'basalt': ('any', {'Hematite', 'Goethite', 'Pyroxene', 'Olivine', None},
               'dark basalt: weak signatures expected; at most iron (Fe3+ weathering, Fe2+ pyroxene) in the 1 um group'),
}


def compare(place, rock):
    if rock not in EXPECT:
        return {'verdict': 'n/a', 'why': 'no expectation defined for %s' % rock}
    grp, exp, why = EXPECT[rock]
    s = place['summary']
    if s['granulesUsed'] == 0:
        return {'verdict': 'no data', 'expected': why}
    if rock == 'basalt':
        g1, g2 = s['g1'], s['g2']
        weak = (g1.get('mineral') is None or g1.get('strength') == 'weak' or g1.get('meanShare', 0) < 0.5) and \
               (g2.get('mineral') is None or g2.get('strength') == 'weak' or g2.get('meanShare', 0) < 0.5)
        iron = g1.get('mineral') in exp
        if weak or iron:
            v = 'agree' if weak and (iron or g1.get('mineral') is None) else 'partly'
        else:
            v = 'differ'
        return {'verdict': v, 'expected': why,
                'found': 'g1 %s (%s, %s), g2 %s (%s, %s)' % (g1.get('mineral'), g1.get('agree'), g1.get('strength'),
                                                          g2.get('mineral'), g2.get('agree'), g2.get('strength'))}
    sm = s[grp]
    found = sm.get('mineral')
    seen = set(sm.get('presentIn', {})) | ({sm['core']['mineral']} if sm.get('core') else set())
    if found in exp:
        v = 'agree' if sm['nDominant'] * 2 > s['granulesUsed'] else 'partly'
    elif seen & exp:
        v = 'partly'
    else:
        v = 'differ'
    return {'verdict': v, 'expected': why,
            'found': '%s dominant in %s (strength %s, mean share %s); present in granules: %s; main EMIT-10 mineral: %s' % (
                found, sm.get('agree'), sm.get('strength'), sm.get('meanShare'),
                ', '.join('%s x%d' % (f, c) for f, c in sm.get('presentIn', {}).items()) or '-',
                ('%s (%s)' % (sm['core']['mineral'], sm['core']['agree'])) if sm.get('core') else '-')}


def has_nan(o):
    if isinstance(o, float):
        return o != o or o in (float('inf'), float('-inf'))
    if isinstance(o, dict):
        return any(has_nan(v) for v in o.values())
    if isinstance(o, list):
        return any(has_nan(v) for v in o)
    return False


# ------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--token-file', default=os.path.join(ROOT, 'earthdata_token.txt'))
    ap.add_argument('--sites-only', action='store_true')
    ap.add_argument('--boxes-only', action='store_true', help='reuse sites from the existing data/emit.json')
    ap.add_argument('--box-limit', type=int, default=0)
    ap.add_argument('--site', action='append', help='only these site ids (testing)')
    ap.add_argument('--box-minutes', type=float, default=110.0)
    a = ap.parse_args()
    t_start = time.time()
    if not emit_http.load_token(a.token_file):
        log('token file missing or empty:', a.token_file)
        return 2
    probe = 'https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/EMITL2BMIN.001/' \
            'EMIT_L2B_MIN_001_20220902T060456_2224504_006/EMIT_L2B_MIN_001_20220902T060456_2224504_006.nc'
    st, _ = emit_http.get(probe, 0, 8)
    log('token check: HTTP', st)
    if st not in (200, 206):
        log('Earthdata access refused. Check the token (not expired) and that LP DAAC data access is '
            'authorised on your Earthdata Login profile, then rerun.')
        return 3
    matrix = emit_minerals.load_matrix(MATRIX)
    manifest, windows_raw = [], {}
    mineral_seen = {'001': {}, '002': {}}

    prev_run = {}
    if a.boxes_only:
        old = load_json('emit.json')
        places = old['places']
        with open(os.path.join(RAW, 'manifest.json'), encoding='utf-8') as f:
            oldman = json.load(f)
        manifest = [m for m in oldman['granules'] if m['use'].startswith('site:')]
        prev_run = oldman.get('runSeconds', {})
        with open(os.path.join(RAW, 'site_windows.json'), encoding='utf-8') as f:
            windows_raw = json.load(f)['sites']
        for ver, ent in old['mineralTable']['entries'].items():
            for i, v in ent.items():
                mineral_seen[ver[1:]][int(i)] = {'sample': v['name'], 'file': v['libraryFile'], 'group': v['group'],
                                                 'family': v['mineral'], 'class': v['class'],
                                                 'emit10': v['emit10Weights'], 'matrix': v['inGroupingMatrix']}
        t_sites = prev_run.get('sites', 0)
    else:
        places = run_sites(matrix, manifest, windows_raw, mineral_seen, a.site)
        t_sites = time.time() - t_start
    meta = {s['id']: s for s in load_json('sites_meta.json')['sites']}
    checks = {'tokenStatus': st, 'sites': len(places), 'sitesWithData': sum(1 for p in places.values() if p['summary']['granulesUsed']),
              'granulesUsed': sum(p['summary']['granulesUsed'] for p in places.values()), 'jordan': {}}
    for sid, p in places.items():
        if meta[sid].get('jordan'):
            checks['jordan'][sid] = dict(compare(p, meta[sid]['geology']['primary']), rockType=meta[sid]['geology']['primary'])

    box_results, boxes, box_recs = {}, [], []
    t_boxes = 0
    if not a.sites_only:
        tb = time.time()
        box_results, boxes, box_recs = run_boxes(matrix, manifest, a.box_limit, mineral_seen, tb + a.box_minutes * 60)
        t_boxes = time.time() - tb

    # mineral table: ids actually seen in this run, per product version
    table = {}
    for ver, ids in mineral_seen.items():
        if ids:
            table['V' + ver] = {str(i): {'name': v['sample'], 'libraryFile': v['file'], 'group': v['group'],
                                         'mineral': v['family'], 'class': v['class'],
                                         'emit10Weights': v['emit10'], 'inGroupingMatrix': v['matrix']}
                                for i, v in sorted(ids.items()) if v}
    now = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    rules = {
        'window': 'Sites: 5 x 5 cells (300 m) of the granule\'s own geometry lookup table (GLT, 60 m north-up WGS-84 grid; '
                  'location/glt_x, glt_y + the geotransform attribute) centred on the cell holding the site point; each '
                  'GLT cell points to one swath pixel (nearest neighbour), so the window is the orthorectified map view. '
                  'Jordan boxes: 17 x 17 cells (~1 km) at the box centre.',
        'granules': 'Granules from NASA CMR whose footprint contains the point. V002 is used where an acquisition was '
                    'reprocessed, otherwise V001. Sorted by the granule cloud cover in CMR, spread over seasons and '
                    'dates (penalty for the same season/day); up to 5 accepted per site (max 12 tried).',
        'invalid': 'Left out: GLT cells without a swath pixel; pixels with fill value -9999 in mineral id or band depth '
                   '(ATBD 4.2.1: -9999 = no data); pixels flagged in the matching EMIT L2A Mask granule: water flag = 1 -> water; '
                   'SpecTf-Cloud flag (model probability > 0.51) or dense-cirrus flag (or spacecraft flag, where present) = 1 -> '
                   'cloud. The legacy threshold Cloud/Dilated Cloud/Aggregate flags are NOT used for screening because the EMIT '
                   'L2A Mask ATBD reports false positives over bright desert surfaces (they are reported as '
                   'legacyCloudFlagShare); they are used only if a mask file has no SpecTf band. '
                   'A granule window counts only when >= 50 % of its cells are valid.',
        'detection': 'Mineral id 0 = no detection (ATBD 4.2.1). Ids > 0 are Tetracorder matches that already passed the '
                     'expert-system fit/depth requirements (ATBD 4.2.1); no extra fit threshold is applied because the '
                     'guide/ATBD give none. Band-depth uncertainty (1 sigma, L2B MINUNCERT) is used to report '
                     '"above2Sigma" = share of the dominant mineral\'s pixels with band depth >= 2 x uncertainty; a '
                     'summary is "weak" when that share is below 0.5.',
        'mineral': 'Each library spectrum is named by its main EMIT-10 mineral using the EMIT grouping matrix weights '
                   '(e.g. "Calcite.33+Kaol.33+Musc.33" -> Calcite, tie broken by name order); other spectra by a '
                   'keyword rule or their first word. Group 1 = 1 um electronic features (iron oxides), group 2 = '
                   '2-2.5 um vibrational features (clays, carbonates, sulfates).',
        'perGranule': 'Dominant mineral = the most frequent mineral among valid cells with a detection, reported only '
                      'if it covers >= 20 % of the valid cells (otherwise mineral = null and the scattered detections '
                      'are listed under "sparse"); share = its cells / valid cells; meanBandDepth, meanBandDepthUnc and '
                      'meanFit (r^2) over those cells. coreMineral = the most frequent of the ten EMIT core minerals '
                      '(LP DAAC: the validated focus of the product), same 20 % rule.',
        'perSite': 'summary.gX.mineral = the mineral dominant in most usable granules (tie: larger summed share); '
                   'agree = in how many of the usable granules it was dominant; presentIn counts granules where it is '
                   'dominant or a >= 5 % secondary; core = the same vote over coreMineral (EMIT-10 only).',
        'vegetationWater': 'Water comes from the L2A water flag. The L2B guide has no vegetation mask; dryVegShare is the '
                           'share of valid cells whose group-2 match is a dry-vegetation spectrum (grouping matrix '
                           '"Vegetation" column). Green vegetation is not identified by this product.',
    }
    product = {
        'names': ['EMIT L2B Estimated Mineral Identification and Band Depth and Uncertainty 60 m V001',
                  'EMIT L2B Estimated Mineral Identification and Band Depth and Uncertainty 60 m V002',
                  'EMIT L2A Masks 60 m V002 / V003 (cloud and water screening)'],
        'shortNames': ['EMITL2BMIN', 'EMITL2AMASK'], 'versions': ['V001', 'V002', 'mask V002/V003'],
        'dois': ['10.5067/EMIT/EMITL2BMIN.001', '10.5067/EMIT/EMITL2BMIN.002', '10.5067/EMIT/EMITL2AMASK.002',
                 '10.5067/EMIT/EMITL2AMASK.003'],
        'citation': ['Green, R. (2023). EMIT L2B Estimated Mineral Identification and Band Depth and Uncertainty 60 m V001 '
                     '[Data set]. NASA Land Processes Distributed Active Archive Center. https://doi.org/10.5067/EMIT/EMITL2BMIN.001',
                     'Brodrick, P., Clark, R., Swayze, G., Kokaly, R., Meyer, J., Montgomery, J., Chadwick, D., Leach, J., '
                     'Ehlman, B., Keebler, A., Olson-Duvall, W., Lundeen, S., Thompson, D., & Green, R. (2026). EMIT L2B '
                     'Estimated Mineral Identification and Band Depth and Uncertainty 60 m V002 [Data set]. NASA Land '
                     'Processes Distributed Active Archive Center. https://doi.org/10.5067/EMIT/EMITL2BMIN.002',
                     'Brodrick, P., Lee, J., Kiper, M., Chlus, A., Olson-Duvall, W., Lundeen, S., Thompson, D., & Green, R. '
                     '(2026). EMIT L2A Masks 60 m V003 [Data set]. NASA Land Processes Distributed Active Archive Center. '
                     'https://doi.org/10.5067/EMIT/EMITL2AMASK.003'],
        'citationSource': ['https://www.earthdata.nasa.gov/data/catalog/lpcloud-emitl2bmin-001',
                           'https://www.earthdata.nasa.gov/data/catalog/lpcloud-emitl2bmin-002',
                           'https://www.earthdata.nasa.gov/data/catalog/lpcloud-emitl2amask-003'],
        'licence': 'NASA Earth science data are openly shared without restriction; NASA-led mission data are released '
                   'under CC0 (NASA Earthdata data use guidance). LP DAAC: "This dataset is openly shared, without '
                   'restriction, in accordance with the EOSDIS Data Use and Citation Guidance."',
        'licenceUrl': 'https://www.earthdata.nasa.gov/engage/open-data-services-software-policies/data-use-guidance',
        'docs': ['https://lpdaac.usgs.gov/documents/1660/EMITL2BMIN_User_Guide_V1.pdf',
                 'https://lpdaac.usgs.gov/documents/1659/EMITL2B_ATBD_v1.pdf'],
        'caveats': ['LP DAAC: the ten EMIT core minerals are the focus; other minerals need further validation.',
                    'Separating fine-grained goethite from hematite is an active research area.',
                    'Band depth is the strength of the best-matching absorption, not an abundance or weight percent.',
                    'No EMIT data were acquired 13 Sep 2022 - 6 Jan 2023.'],
    }
    emit = {
        'about': 'Surface minerals seen from orbit by NASA EMIT (imaging spectrometer on the ISS, 60 m pixels, '
                 '+/-52 deg latitude). Per site: up to 5 clear acquisitions, the dominant 1 um (iron oxide) and 2 um '
                 '(clay/carbonate/sulfate) mineral in a 300 m window, and how many acquisitions agree. Real measured '
                 'data, no values invented. Sites outside EMIT coverage: ' + ', '.join(sorted(OUTSIDE)) + '.',
        'product': product, 'rules': rules,
        'mineralTable': {'source': 'Each granule\'s own mineral_metadata group (index, name/sample_name, group); EMIT-10 '
                                   'weights from the EMIT SDS mineral grouping matrix 20230503 (Apache-2.0)',
                         'sourceUrl': MATRIX_URL, 'entries': table},
        'generated': now,
        'places': places,
        'checks': checks,
    }
    with open(os.path.join(DATA, 'emit.json'), 'w', encoding='utf-8') as f:
        json.dump(emit, f, ensure_ascii=False, separators=(',', ':'))

    if box_results:
        gl = sorted({v['granule'] for v in box_results.values()})
        gi = {t: i for i, t in enumerate(gl)}
        rows = {}
        for b in boxes:
            v = box_results.get(b['id'])
            if not v:
                continue
            g1, g2 = v['g1'], v['g2']
            rows[b['id']] = [g1.get('mineral'), g1.get('share'), g1.get('meanBandDepth'), g1.get('above2Sigma'),
                             g2.get('mineral'), g2.get('share'), g2.get('meanBandDepth'), g2.get('above2Sigma'),
                             v['validShare'], v['waterShare'], gi[v['granule']]]
        cross = defaultdict(Counter)
        for b in boxes:
            v = box_results.get(b['id'])
            if v and v['validShare'] >= MIN_VALID:
                rock = (b.get('geology') or {}).get('primary') or 'none'
                cross[rock][v['g2'].get('mineral') or 'none'] += 1
        scr = {'format': 'emit-screening-v1', 'generated': now,
               'about': 'EMIT L2B dominant minerals per Jordan 10 km box: 17 x 17 pixel (~1 km) window at the box centre in '
                        'the clearest acquisition covering it (V002 where available). Same rules and citation as data/emit.json.',
               'fields': ['g1Mineral', 'g1Share', 'g1BandDepth', 'g1Above2Sigma', 'g2Mineral', 'g2Share', 'g2BandDepth',
                          'g2Above2Sigma', 'validShare', 'waterShare', 'granule'],
               'granules': [[t, box_results[next(k for k in box_results if box_results[k]['granule'] == t)]['date']] for t in gl],
               'boxes': rows,
               'counts': {'boxes': len(boxes), 'withResult': len(rows),
                          'usable': sum(1 for r in rows.values() if r[8] >= MIN_VALID),
                          'g1': dict(Counter(r[0] for r in rows.values() if r[8] >= MIN_VALID).most_common()),
                          'g2': dict(Counter(r[4] for r in rows.values() if r[8] >= MIN_VALID).most_common())},
               'rockVsG2': {k: dict(v.most_common(6)) for k, v in cross.items()},
               'sourceDoc': 'data/emit.json'}
        with open(os.path.join(DATA, 'screening_emit.json'), 'w', encoding='utf-8') as f:
            json.dump(scr, f, ensure_ascii=False, separators=(',', ':'))
        checks['boxes'] = scr['counts']
        checks['boxesRockVsG2'] = scr['rockVsG2']

    total_bytes = sum(m['bytes'] for m in manifest)
    man = {'generated': now, 'note': 'Granules read with HTTP Range requests (only the chunks needed). No token stored.',
           'runSeconds': {'sites': round(t_sites), 'boxes': round(t_boxes), 'total': round(time.time() - t_start)},
           'http': dict(emit_http.STATS), 'totalBytes': total_bytes, 'granules': manifest}
    os.makedirs(RAW, exist_ok=True)
    with open(os.path.join(RAW, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(man, f, indent=1)
    with open(os.path.join(RAW, 'site_windows.json'), 'w', encoding='utf-8') as f:
        json.dump({'about': 'Raw mineral-id counts (valid + invalid cells with id > 0) per site window and granule; '
                            'ids index each granule\'s mineral_metadata.', 'sites': windows_raw}, f, separators=(',', ':'))

    # ---- printed checks
    log('\n==== checks ====')
    log('token check: HTTP', st)
    log('sites inside coverage: %d, with usable data: %d, granule windows used: %d' % (
        checks['sites'], checks['sitesWithData'], checks['granulesUsed']))
    log('NaN/inf in emit.json:', has_nan(emit), '| in screening_emit.json:', has_nan(box_results) if box_results else 'n/a')
    log('bytes read: %.1f MB in %d requests (%d retries); run %.0f s' % (total_bytes / 1e6, emit_http.STATS['requests'],
                                                                          emit_http.STATS['retries'], time.time() - t_start))
    log('\n%-22s %-5s %-22s %-14s %-6s %-22s %-14s %-6s flags' % ('site', 'used', 'g1', 'agree', 'str', 'g2', 'agree', 'str'))
    for sid, p in places.items():
        s = p['summary']
        log('%-22s %-5s %-22s %-14s %-6s %-22s %-14s %-6s %s' % (
            sid, s['granulesUsed'], s['g1'].get('mineral'), s['g1'].get('agree', '')[:14], s['g1'].get('strength', ''),
            s['g2'].get('mineral'), s['g2'].get('agree', '')[:14], s['g2'].get('strength', ''), ','.join(p['flags'])))
    log('\nJordan sites vs app rock type:')
    for sid, c in checks['jordan'].items():
        log('  %-16s %-10s %-8s %s' % (sid, c['rockType'], c['verdict'], c.get('found', '')))
    if box_results:
        log('\nboxes:', json.dumps(checks['boxes']))
        log('rock vs g2:', json.dumps(checks['boxesRockVsG2']))
    with open(os.path.join(DATA, 'emit.json'), 'w', encoding='utf-8') as f:
        json.dump(emit, f, ensure_ascii=False, separators=(',', ':'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
