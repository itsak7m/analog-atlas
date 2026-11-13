"""emit_minerals: map EMIT L2B MIN mineral ids to a readable mineral name ("family") and class.

Sources (in order of use):
1. The granule's own /mineral_metadata group (index, group, name / sample_name). This is the
   authoritative id -> library spectrum table for that file (V001: 294 entries, V002: 312).
2. EMIT SDS mineral grouping matrix 20230503 (emit-sds/emit-sds-l2b, Apache-2.0, copied to
   data/raw/emit/mineral_grouping_matrix_20230503.csv). Its EMIT-10 columns give the weight of
   calcite, chlorite, dolomite, goethite, gypsum, hematite, illite+muscovite, kaolinite,
   montmorillonite, vermiculite in each library spectrum, plus class columns. V001 ids are its
   Index column (the V001 history attribute names this exact file). V002 entries are matched by
   library file name (V002 'name' = file name, V001/CSV 'Filename' = group.Xum/<file name>).
3. If a spectrum has no EMIT-10 weight, a keyword rule on the sample name (documented below).

family = the EMIT-10 mineral with the largest weight in the spectrum (ties: the one named first in
the sample name). Spectra not in the matrix (new in V002): keyword rule on the sample name (e.g.
"Nanohematite" -> Hematite). Spectra in the matrix with no EMIT-10 weight are never relabelled as an
EMIT-10 mineral: they keep a non-EMIT-10 keyword (e.g. Jarosite) or the first word of the name
(e.g. "Beidellite+Montmor GDS123" -> Beidellite).
"""
import csv
import re

EMIT10 = ['Calcite', 'Chlorite', 'Dolomite', 'Goethite', 'Gypsum', 'Hematite', 'Illite+Muscovite',
          'Kaolinite', 'Montmorillonite', 'Vermiculite']
CLASS_COLS = ['Iron Oxide', 'Clay', 'Carbonate', 'Sulfate', 'Sulfide', 'Artifical Materials', 'Vegetation',
              'Coating', 'Biotite']
# keyword (lower-case, searched in the sample name) -> family; earliest match in the name wins
KEYWORDS = [('hemat', 'Hematite'), ('goeth', 'Goethite'), ('calcite', 'Calcite'), ('dolom', 'Dolomite'),
            ('gypsum', 'Gypsum'), ('kaol', 'Kaolinite'), ('montmor', 'Montmorillonite'), ('muscov', 'Illite+Muscovite'),
            ('illite', 'Illite+Muscovite'), ('chlorite', 'Chlorite'), ('clinochl', 'Chlorite'), ('vermic', 'Vermiculite'),
            ('aragon', 'Aragonite'), ('jarosite', 'Jarosite'), ('alunite', 'Alunite'), ('ferrihyd', 'Ferrihydrite'),
            ('lepidocroc', 'Lepidocrocite'), ('schwertm', 'Schwertmannite'), ('magnetite', 'Magnetite'),
            ('pyroxene', 'Pyroxene'), ('olivine', 'Olivine')]
FAMILY_CLASS = {'Hematite': 'iron oxide', 'Goethite': 'iron oxide', 'Ferrihydrite': 'iron oxide',
                'Lepidocrocite': 'iron oxide', 'Magnetite': 'iron oxide',
                'Calcite': 'carbonate', 'Dolomite': 'carbonate', 'Aragonite': 'carbonate',
                'Gypsum': 'sulfate', 'Jarosite': 'sulfate', 'Alunite': 'sulfate', 'Schwertmannite': 'sulfate',
                'Kaolinite': 'clay', 'Montmorillonite': 'clay', 'Illite+Muscovite': 'clay/mica',
                'Chlorite': 'clay/mica', 'Vermiculite': 'clay/mica'}


def load_matrix(path):
    rows = {}
    by_file = {}
    with open(path, encoding='utf-8', errors='replace') as f:
        for r in csv.DictReader(f):
            rec = {'index': int(r['Index']), 'name': r['Name'].strip(), 'file': r['Filename'].strip(),
                   'group': int(r['Group']),
                   'emit10': {m: float(r[m]) for m in EMIT10 if r.get(m, '').strip() not in ('', '0')},
                   'classes': [c for c in CLASS_COLS if r.get(c, '').strip() not in ('', '0')]}
            rows[rec['index']] = rec
            by_file[rec['file'].split('/')[-1].lower()] = rec
    return rows, by_file


def _first_word(name):
    w = re.split(r'[\s_]', name.strip())[0] if name.strip() else '?'
    w = re.sub(r'[\d.]+$', '', re.split(r'[+(]', w)[0]) or w
    return w[:1].upper() + w[1:]


# readable names for a few library spectra whose sample name is a lab code (matched on the file name)
PRETTY = [('hydrated_basaltic_glass', 'Hydrated basaltic glass', 'silica/glass'), ('sioh_chalcedony', 'Chalcedony', 'silica/glass'),
          ('sioh_opal', 'Opal', 'silica/glass'), ('amd.assemb', 'Fe3+ mine-drainage mix', 'iron-bearing'),
          ('generic_basalt', 'Basalt (Fe2+)', 'iron-bearing')]


def family_of(sample_name, csv_rec, file_name=''):
    low = sample_name.lower()
    fl = (file_name or (csv_rec['file'] if csv_rec else '')).lower()
    for key, nice, cls in PRETTY:
        if key in fl:
            return nice, cls
    if csv_rec and 'Vegetation' in csv_rec['classes']:
        return 'Dry vegetation', 'vegetation'
    if csv_rec and 'Artifical Materials' in csv_rec['classes']:
        return 'Man-made material', 'artificial'
    if csv_rec and csv_rec['emit10']:
        best = max(csv_rec['emit10'].values())
        tied = [m for m, v in csv_rec['emit10'].items() if v == best]

        def pos(m):
            keys = [k for k, fam in KEYWORDS if fam == m]
            hits = [low.find(k) for k in keys if low.find(k) >= 0]
            return min(hits) if hits else 999
        fam = sorted(tied, key=pos)[0]
        return fam, FAMILY_CLASS.get(fam, 'other')
    hits = [(low.find(k), fam) for k, fam in KEYWORDS if low.find(k) >= 0]
    if csv_rec and hits and min(hits)[1] in EMIT10:
        # the matrix knows this spectrum and gives it no EMIT-10 weight: do not relabel it as one
        hits = []
    if hits:
        fam = min(hits)[1]
        return fam, FAMILY_CLASS.get(fam, 'other')
    if 'vegetation' in low or 'grass' in low or 'lignin' in low:
        return 'Dry vegetation', 'vegetation'
    if any(k in low for k in ('plastic', 'paint', 'tarp', 'asphalt', 'roof')):
        return 'Man-made material', 'artificial'
    cls = 'other'
    if any(k in low for k in ('beidell', 'nontron', 'saponit', 'smectit', 'halloy', 'dickite', 'pyrophyl', 'sepiol',
                              'palygor', 'serpent', 'talc')):
        cls = 'clay/phyllosilicate'
    elif csv_rec:
        for c, lab in (('Iron Oxide', 'iron-bearing'), ('Carbonate', 'carbonate'), ('Sulfate', 'sulfate'),
                       ('Clay', 'clay'), ('Sulfide', 'sulfide'), ('Coating', 'coating')):
            if c in csv_rec['classes']:
                cls = lab
                break
    return _first_word(sample_name), cls


def granule_lut(ds, matrix_rows, matrix_by_file):
    """{mineral_id: {...}} for one granule from its /mineral_metadata (read via emit_dmrpp.Dataset)."""
    idx = ds.read_1d('mineral_metadata/index')
    grp = ds.read_1d('mineral_metadata/group')
    has_sample = 'mineral_metadata/sample_name' in ds.vars
    names = ds.read_1d('mineral_metadata/sample_name' if has_sample else 'mineral_metadata/name')
    files = ds.read_1d('mineral_metadata/name') if has_sample else [None] * len(idx)
    lut = {}
    mismatch = 0
    for i, g, s, f in zip(idx, grp, names, files):
        i = int(i)
        if f:   # V002: match on library file name
            rec = matrix_by_file.get(f.strip().lower())
        else:   # V001: index into the 20230503 matrix, sanity-check the name
            rec = matrix_rows.get(i)
            if rec and rec['name'].split()[0] != (s or '').split()[0]:
                mismatch += 1
                rec = None
        fam, cls = family_of(s or '', rec, f or '')
        lut[i] = {'sample': (s or '').strip(), 'file': (f or (rec['file'].split('/')[-1] if rec else '')).strip(),
                  'group': int(g), 'family': fam, 'class': cls,
                  'emit10': rec['emit10'] if rec else {}, 'matrix': bool(rec)}
    return lut, mismatch
