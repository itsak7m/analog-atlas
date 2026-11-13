"""Cosmic Cat field-kit case: the team's pixel-art mascot as a 3D-printable housing.

The body holds the ESP32 DevKit V1, the tail is a hollow tube for the wires with a vented
section for the BME280 (away from the ESP32's heat), and the tail tip holds the sky sensors
(BH1750 up, GUVA-S12SD UV) on top and the ground sensors (BH1750 down, MLX90614) underneath.

Plain Python, no libraries. Writes binary STL files next to this script:
    python -I hardware/cosmic-cat/make_cat.py
All sizes are in millimetres. The model is built from boxes on a 0.5 mm grid, so every
surface is flat and the blocky "pixel" look comes for free.
"""
import json
import os
import struct

RES = 0.5          # grid step (mm)
U = 6.0            # one mascot "pixel" (mm)
WALL = 2.5         # wall thickness: 6 perimeters with a 0.4 mm nozzle
GAP = 0.5          # clearance per side for parts that slide into each other
HERE = os.path.dirname(os.path.abspath(__file__))

# Body (base) outer size: 14 x 8 pixels, 7 pixels tall, on 2-pixel legs.
BX, BY = 14 * U, 8 * U            # 84 x 48
LEG = 2 * U                       # 12
FLOOR = 3.0
BTOP = LEG + 7 * U                # 54: top of the body walls
PLATE = 3.0                       # lid plate thickness (sits inside the walls)
TUBE = 28.0                       # tail tube outer size
TUBE_IN = 18.0                    # tail tube channel
TUBE_H = 110.0
SOCKET_FLOOR = 20.0               # tail tube rests here in the tail root
ROOT_TOP = 32.0
TAIL_X = -21.0                    # tail tube centre (behind the body)
POD_X, POD_Y, POD_H = 66.0, 42.0, 30.0
COLLAR = 3.0                      # collar wall around the tube top
SENSOR_X = 47.0                   # tail tip: sensor windows sit beyond the tube, between the screw columns
SENSOR_Y = (12.5, 29.5)           # two boards side by side (about 18 x 14 mm each)
BOLT = 3.4                        # M3 clearance hole
PILOT = 2.5                       # M3 self-tapping pilot hole
NUT_POCKET = 11.5                 # 1/4"-20 tripod nut (11.1 across flats), stops it turning
NUT_H = 6.0
TRIPOD_HOLE = 7.0                 # 1/4" screw clearance


class Part:
    """Solid made of boxes on a grid. Each x-row is a Python int used as a bit set."""

    def __init__(self, name, lo, hi):
        self.name = name
        self.o = lo
        self.n = [int(round((hi[a] - lo[a]) / RES)) for a in range(3)]
        self.rows = [[0] * self.n[1] for _ in range(self.n[2])]

    def _span(self, a, v0, v1):
        i0 = max(0, int(round((v0 - self.o[a]) / RES)))
        i1 = min(self.n[a], int(round((v1 - self.o[a]) / RES)))
        return i0, i1

    def _box(self, x0, x1, y0, y1, z0, z1, solid):
        i0, i1 = self._span(0, x0, x1)
        j0, j1 = self._span(1, y0, y1)
        k0, k1 = self._span(2, z0, z1)
        if i1 <= i0 or j1 <= j0 or k1 <= k0:
            return
        mask = ((1 << (i1 - i0)) - 1) << i0
        for k in range(k0, k1):
            row = self.rows[k]
            for j in range(j0, j1):
                row[j] = row[j] | mask if solid else row[j] & ~mask

    def add(self, *b):
        self._box(*b, True)

    def cut(self, *b):
        self._box(*b, False)

    def volume_cm3(self):
        return sum(bin(r).count('1') for plane in self.rows for r in plane) * RES ** 3 / 1000

    def triangles(self):
        """Greedy-merged outer faces, two triangles per rectangle, with outward normals."""
        nx, ny, nz = self.n
        rows, ox, oy, oz = self.rows, *self.o
        full = (1 << nx) - 1
        tris = []

        def runs(m):
            while m:
                i0 = (m & -m).bit_length() - 1
                s = m >> i0
                length = (s ^ (s + 1)).bit_length() - 1
                yield i0, i0 + length
                m &= ~(((1 << length) - 1) << i0)

        def merge(planes, emit):
            # planes: list over rows r of bit masks along i; merge equal runs over consecutive r
            active = {}
            for r, m in enumerate(planes + [0]):
                cur = set(runs(m))
                for key in list(active):
                    if key not in cur:
                        emit(key[0], key[1], active.pop(key), r)
                for key in cur:
                    active.setdefault(key, r)

        X = lambda i: ox + i * RES
        Y = lambda j: oy + j * RES
        Z = lambda k: oz + k * RES

        def quad(n, a, b, c, d):
            tris.append((n, a, b, c))
            tris.append((n, a, c, d))

        # faces normal to z (plane between k and k+1), rows over j, bits over i
        for k in range(nz + 1):
            below = rows[k - 1] if k > 0 else [0] * ny
            above = rows[k] if k < nz else [0] * ny
            up = [below[j] & ~above[j] for j in range(ny)]
            dn = [above[j] & ~below[j] for j in range(ny)]
            z = Z(k)
            merge(up, lambda i0, i1, j0, j1: quad((0, 0, 1), (X(i0), Y(j0), z), (X(i1), Y(j0), z), (X(i1), Y(j1), z), (X(i0), Y(j1), z)))
            merge(dn, lambda i0, i1, j0, j1: quad((0, 0, -1), (X(i0), Y(j0), z), (X(i0), Y(j1), z), (X(i1), Y(j1), z), (X(i1), Y(j0), z)))
        # faces normal to y (plane between j and j+1), rows over k, bits over i
        for j in range(ny + 1):
            pos = [(rows[k][j - 1] if j > 0 else 0) & ~(rows[k][j] if j < ny else 0) for k in range(nz)]
            neg = [(rows[k][j] if j < ny else 0) & ~(rows[k][j - 1] if j > 0 else 0) for k in range(nz)]
            y = Y(j)
            merge(pos, lambda i0, i1, k0, k1: quad((0, 1, 0), (X(i0), y, Z(k0)), (X(i0), y, Z(k1)), (X(i1), y, Z(k1)), (X(i1), y, Z(k0))))
            merge(neg, lambda i0, i1, k0, k1: quad((0, -1, 0), (X(i0), y, Z(k0)), (X(i1), y, Z(k0)), (X(i1), y, Z(k1)), (X(i0), y, Z(k1))))
        # faces normal to x: within each row, bit i solid and bit i+1 empty (or the reverse)
        for k in range(nz):
            for sign in (1, -1):
                # collect, per x plane, a mask over j for this k
                planes = {}
                for j in range(ny):
                    m = rows[k][j]
                    f = m & ~(m >> 1) if sign > 0 else m & ~((m << 1) & full)
                    for i0, i1 in runs(f):
                        for i in range(i0, i1):
                            planes.setdefault(i, 0)
                            planes[i] |= 1 << j
                for i, mj in planes.items():
                    x = X(i + 1) if sign > 0 else X(i)
                    for j0, j1 in runs(mj):
                        if sign > 0:
                            quad((1, 0, 0), (x, Y(j0), Z(k)), (x, Y(j1), Z(k)), (x, Y(j1), Z(k + 1)), (x, Y(j0), Z(k + 1)))
                        else:
                            quad((-1, 0, 0), (x, Y(j0), Z(k)), (x, Y(j0), Z(k + 1)), (x, Y(j1), Z(k + 1)), (x, Y(j1), Z(k)))
        return tris

    def write_stl(self, path, place=(0, 0, 0), flip=False):
        """flip=True turns the part upside down (for printing), keeping the normals outward."""
        tris = self.triangles()
        if flip:
            top = self.o[2] + self.n[2] * RES
            tris = [((n[0], n[1], -n[2]), *[(v[0], v[1], top - (v[2] - self.o[2])) for v in (a, c, b)]) for n, a, b, c in tris]
        z0 = min(v[2] for t in tris for v in t[1:]) - place[2]  # every part starts on the bed (z = 0)
        place = (place[0], place[1], place[2] + z0)
        with open(path, 'wb') as f:
            f.write(b'Cosmic Cat field kit case - Analog Atlas'.ljust(80, b' '))
            f.write(struct.pack('<I', len(tris)))
            for n, *vs in tris:
                f.write(struct.pack('<3f', *n))
                for v in vs:
                    f.write(struct.pack('<3f', v[0] - place[0], v[1] - place[1], v[2] - place[2]))
                f.write(b'\0\0')
        self.placed = (place, self.o[2] + self.n[2] * RES if flip else None)
        return len(tris)


def base():
    """Body: legs, belly pad with the tripod nut, ESP32 bay, tail root with the tube socket."""
    p = Part('1_body_base', (-40, -2, 0), (BX + 2, BY + 2, BTOP + 1))
    # legs and belly pad (all stand on z = 0, so the cat sits flat on a tripod plate)
    for x0 in (U, BX - 3 * U):
        for y0 in (U, BY - 3 * U):
            p.add(x0, x0 + 2 * U, y0, y0 + 2 * U, 0, LEG)
    p.add(30, 54, 12, 36, 0, LEG)
    # body box, open at the top
    p.add(0, BX, 0, BY, LEG, BTOP)
    p.cut(WALL, BX - WALL, WALL, BY - WALL, LEG + FLOOR, BTOP + 1)
    # tripod: 1/4"-20 screw from below, hex nut dropped in from inside
    cx, cy = 42, 24
    p.cut(cx - TRIPOD_HOLE / 2, cx + TRIPOD_HOLE / 2, cy - TRIPOD_HOLE / 2, cy + TRIPOD_HOLE / 2, 0, LEG + FLOOR)
    p.cut(cx - NUT_POCKET / 2, cx + NUT_POCKET / 2, cy - NUT_POCKET / 2, cy + NUT_POCKET / 2, LEG + FLOOR - NUT_H - 3, LEG + FLOOR)
    # corner columns: rear two take the lid screws, front two hold the lid plate up
    lid_seat = BTOP - PLATE
    for x0 in (WALL, BX - WALL - 7):
        for y0 in (WALL, BY - WALL - 7):
            p.add(x0, x0 + 7, y0, y0 + 7, LEG + FLOOR, lid_seat)
    for y0 in (WALL, BY - WALL - 7):
        p.cut(WALL + 3.5 - PILOT / 2, WALL + 3.5 + PILOT / 2, y0 + 3.5 - PILOT / 2, y0 + 3.5 + PILOT / 2, lid_seat - 15, lid_seat)
    # chest: USB cable for the ESP32 (board lies upside down, USB end at the front)
    p.cut(BX - WALL - 1, BX + 1, 17, 31, LEG + FLOOR, LEG + FLOOR + 11)
    # right side, low at the back: DS18B20 soil probe cable
    p.cut(6, 12, BY - WALL - 1, BY + 1, LEG + FLOOR + 1, LEG + FLOOR + 7)
    # vents high on both sides (warm air out, away from the tail sensors)
    for x0 in (24, 33, 42, 51, 60):
        p.cut(x0, x0 + 3, -1, BY + 1, BTOP - 12, BTOP - 5)
    # paw badge on both sides (1 mm relief, paint it amber)
    for y_out, y_in in ((-1, 0), (BY, BY + 1)):
        p.add(36, 46, y_out, y_in, 26, 34)
        for tx in (35, 39.5, 44):
            p.add(tx, tx + 3, y_out, y_in, 36, 39)
    # tail root behind the body, with the tube socket and a wire channel into the body
    p.add(-38, 0, 7, 41, 0, ROOT_TOP)
    s = TUBE / 2 + GAP
    p.cut(TAIL_X - s, TAIL_X + s, 24 - s, 24 + s, SOCKET_FLOOR, ROOT_TOP + 1)
    h = TUBE_IN / 2
    p.cut(TAIL_X - h, WALL + 1, 24 - h + 2, 24 + h - 2, LEG + FLOOR, ROOT_TOP - 4)
    # M3 cross-bolt through the socket walls (locks the tail tube)
    p.cut(TAIL_X - BOLT / 2, TAIL_X + BOLT / 2, 0, 48, SOCKET_FLOOR + 6 - BOLT / 2, SOCKET_FLOOR + 6 + BOLT / 2)
    return p


def lid_head():
    """Lid plate (drops into the body) with the cat head and ears on top."""
    top = BTOP
    p = Part('2_lid_head', (-1, -1, top - PLATE - 1), (BX + 1, BY + 1, top + 63))
    p.add(WALL + GAP, BX - WALL - GAP, WALL + GAP, BY - WALL - GAP, top - PLATE, top)
    for y0 in (WALL, BY - WALL - 7):  # screw holes over the rear columns
        p.cut(WALL + 3.5 - BOLT / 2, WALL + 3.5 + BOLT / 2, y0 + 3.5 - BOLT / 2, y0 + 3.5 + BOLT / 2, top - PLATE - 1, top + 1)
    hx0 = BX - 8 * U  # head: 8 x 8 x 8 pixels at the front
    p.add(hx0, BX, 0, BY, top, top + 8 * U)
    ht = top + 8 * U
    for y0 in (0, BY - 2 * U):  # ears, flush with the face
        p.add(BX - 2 * U, BX, y0, y0 + 2 * U, ht, ht + 2 * U)
        p.cut(BX - 1.5, BX + 1, y0 + 3, y0 + 2 * U - 3, ht + 2, ht + 2 * U - 2)  # inner ear (paint pink)
    face = BX
    d = 1.5  # engraving depth on the face (paint it)
    for y0 in (9, BY - 18):  # eyes with a highlight pixel left standing
        p.cut(face - d, face + 1, y0, y0 + 9, top + 24, top + 33)
        p.add(face - d, face, y0 + 6, y0 + 9, top + 30, top + 33)
    p.cut(face - d, face + 1, BY / 2 - 3, BY / 2 + 3, top + 18, top + 21)  # nose
    # mouth "w": a bar with three short ticks
    p.cut(face - d, face + 1, BY / 2 - 9, BY / 2 - 7, top + 13, top + 17)
    p.cut(face - d, face + 1, BY / 2 - 1, BY / 2 + 1, top + 13, top + 17)
    p.cut(face - d, face + 1, BY / 2 + 7, BY / 2 + 9, top + 13, top + 17)
    p.cut(face - d, face + 1, BY / 2 - 9, BY / 2 + 9, top + 11, top + 13)
    for y0 in (2, BY - 8):  # cheeks
        p.cut(face - d, face + 1, y0, y0 + 6, top + 16, top + 20)
    for z0 in (top + 40, top + 44):  # forehead stripes
        p.cut(face - d, face + 1, BY / 2 - 6, BY / 2 + 6, z0, z0 + 1.5)
    return p


def tail_tube():
    """Hollow tail: wires inside, a vented section for the BME280, tabby stripes outside."""
    p = Part('3_tail_tube', (-TUBE / 2 - 1, -TUBE / 2 - 1, 0), (TUBE / 2 + 1, TUBE / 2 + 1, TUBE_H))
    t, h = TUBE / 2, TUBE_IN / 2
    p.add(-t, t, -t, t, 0, TUBE_H)
    p.cut(-h, h, -h, h, -1, TUBE_H + 1)
    # BME280 chamber: vertical slots on all four sides, shaded by the tail tip above
    for c in (-7, -1.5, 4):
        p.cut(c, c + 3, -t - 1, t + 1, 52, 82)
        p.cut(-t - 1, t + 1, c, c + 3, 52, 82)
    # tabby stripes (1 mm grooves, paint them grey)
    for z0 in (20, 32, 92):
        p.cut(-t - 1, t + 1, -t - 1, -t + 1, z0, z0 + 3)
        p.cut(-t - 1, t + 1, t - 1, t + 1, z0, z0 + 3)
        p.cut(-t - 1, -t + 1, -t - 1, t + 1, z0, z0 + 3)
        p.cut(t - 1, t + 1, -t - 1, t + 1, z0, z0 + 3)
    # cross-bolt holes: bottom (tail root) and top (tail tip collar)
    for zc in (6, TUBE_H - 6):
        p.cut(-BOLT / 2, BOLT / 2, -t - 1, t + 1, zc - BOLT / 2, zc + BOLT / 2)
    return p


def pod_shell():
    """Tail tip: open-bottom box. The top windows face the sky (BH1750 up, UV)."""
    p = Part('4_tailtip_shell', (-1, -1, 0), (POD_X + 1, POD_Y + 1, POD_H))
    p.add(0, POD_X, 0, POD_Y, 0, POD_H)
    p.cut(WALL, POD_X - WALL, WALL, POD_Y - WALL, -1, POD_H - WALL)
    for x0 in (WALL, POD_X - WALL - 7):  # screw columns for the bottom plate
        for y0 in (WALL, POD_Y - WALL - 7):
            p.add(x0, x0 + 7, y0, y0 + 7, 0, POD_H - WALL)
            p.cut(x0 + 3.5 - PILOT / 2, x0 + 3.5 + PILOT / 2, y0 + 3.5 - PILOT / 2, y0 + 3.5 + PILOT / 2, -1, 12)
    for yc in SENSOR_Y:  # sky windows: BH1750 UP (first) and GUVA-S12SD UV (second)
        p.cut(SENSOR_X - 4, SENSOR_X + 4, yc - 4, yc + 4, POD_H - WALL - 1, POD_H + 1)
    # a darker band at the very tip of the tail (paint it)
    p.cut(POD_X - 1, POD_X + 1, -1, POD_Y + 1, 8, 11)
    return p


def pod_plate():
    """Tail tip bottom plate: ground windows (BH1750 down, MLX90614) and the collar for the tube."""
    p = Part('5_tailtip_plate', (-1, -1, -14), (POD_X + 1, POD_Y + 1, PLATE + 1))
    p.add(0, POD_X, 0, POD_Y, 0, PLATE)
    for x0 in (WALL, POD_X - WALL - 7):
        for y0 in (WALL, POD_Y - WALL - 7):
            p.cut(x0 + 3.5 - BOLT / 2, x0 + 3.5 + BOLT / 2, y0 + 3.5 - BOLT / 2, y0 + 3.5 + BOLT / 2, -1, PLATE + 1)
    cxc, cyc = 17.5, POD_Y / 2  # collar centre: the tube comes up here
    c = TUBE / 2 + GAP
    p.add(cxc - c - COLLAR, cxc + c + COLLAR, cyc - c - COLLAR, cyc + c + COLLAR, -12, 0)
    p.cut(cxc - c, cxc + c, cyc - c, cyc + c, -13, 0)
    h = TUBE_IN / 2
    p.cut(cxc - h, cxc + h, cyc - h, cyc + h, -1, PLATE + 1)  # wires pass into the tip
    p.cut(cxc - BOLT / 2, cxc + BOLT / 2, -1, POD_Y + 1, -6 - BOLT / 2, -6 + BOLT / 2)  # cross-bolt
    y_bh, y_mlx = SENSOR_Y
    p.cut(SENSOR_X - 4, SENSOR_X + 4, y_bh - 4, y_bh + 4, -1, PLATE + 1)      # BH1750 DOWN window
    p.cut(SENSOR_X - 5, SENSOR_X + 5, y_mlx - 5, y_mlx + 5, -1, PLATE + 1)    # MLX90614: its metal can pokes through
    return p


def main():
    out = os.path.join(HERE, 'stl')
    os.makedirs(out, exist_ok=True)
    parts = [base(), lid_head(), tail_tube(), pod_shell(), pod_plate()]
    assembly = []
    # print orientation: every part already sits flat on z = its lowest layer, except the
    # tail-tip shell, which prints upside down (top face on the bed)
    for p in parts:
        flip = p.name.startswith(('4_', '5_'))
        n = p.write_stl(os.path.join(out, p.name + '.stl'), (p.o[0], p.o[1], p.o[2] if not flip else 0), flip)
        size = [round(v * RES, 1) for v in p.n]
        assembly.append(to_body(p))
        print(f'{p.name}: {n} triangles, box {size} mm, {p.volume_cm3():.0f} cm3 solid')


    with open(os.path.join(HERE, 'assembly.json'), 'w', encoding='utf-8') as f:
        json.dump(assembly, f, indent=1)


def to_body(p):
    """Affine map from the part's STL coordinates to the assembled cat (for preview.html):
    body = M * stl + t, with M a 3x3 matrix (rows) and t a vector."""
    (px, py, pz), top = p.placed
    tube_top = SOCKET_FLOOR + TUBE_H
    if top is None:  # printed as modelled: model = stl + place
        m, t = [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [px, py, pz]
        if p.name.startswith('3_'):
            t = [px + TAIL_X, py + 24, pz + SOCKET_FLOOR]
    else:  # printed upside down: model z = top + o_z - (stl z + pz); then turned 180 degrees behind the tube
        oz = top + p.o[2] - pz
        z0 = tube_top + (PLATE if p.name.startswith('4_') else 0)
        m = [[-1, 0, 0], [0, -1, 0], [0, 0, -1]]
        t = [TAIL_X + 17.5 - px, 24 + POD_Y / 2 - py, z0 + oz]
    return {'file': 'stl/' + p.name + '.stl', 'name': p.name, 'm': m, 't': t}


if __name__ == '__main__':
    main()
