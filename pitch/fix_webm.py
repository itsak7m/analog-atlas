"""Make a browser-recorded WebM seekable: add its duration and a seek index (Cues).

Chrome's MediaRecorder writes WebM as a live stream: the segment and clusters have
"unknown" sizes, the Info has no Duration and there are no Cues, so players show no
length and cannot jump forward or back. This rewrites the same frames (no re-encoding,
same quality) with known sizes, a Duration, a SeekHead and one cue per video keyframe.

    python -I pitch/fix_webm.py IN.webm OUT.webm
"""
import struct
import sys

SEGMENT, SEEKHEAD, SEEK, SEEKID, SEEKPOS = 0x18538067, 0x114D9B74, 0x4DBB, 0x53AB, 0x53AC
INFO, DURATION, TRACKS, CLUSTER, CUES = 0x1549A966, 0x4489, 0x1654AE6B, 0x1F43B675, 0x1C53BB6B
TOP_LEVEL = {SEEKHEAD, INFO, TRACKS, CLUSTER, CUES, 0x1254C367, 0x1941A469, 0x1043A770}


def read_vint(b, i, keep_marker=False):
    first, n = b[i], 1
    while not first & (0x80 >> (n - 1)):
        n += 1
    v = first if keep_marker else first & ((0x80 >> (n - 1)) - 1)
    for k in range(1, n):
        v = (v << 8) | b[i + k]
    return v, n


def read_head(b, i):
    """(id, size or None if unknown, data start)"""
    eid, n = read_vint(b, i, keep_marker=True)
    size, m = read_vint(b, i + n)
    return eid, (None if size == (1 << (7 * m)) - 1 else size), i + n + m


def id_bytes(eid):
    return eid.to_bytes((eid.bit_length() + 7) // 8, 'big')


def el(eid, payload):  # 8-byte sizes keep every length predictable
    return id_bytes(eid) + b'\x01' + len(payload).to_bytes(7, 'big') + payload


def uint_el(eid, v, width=None):
    return el(eid, v.to_bytes(width or max(1, (v.bit_length() + 7) // 8), 'big'))


def children(b, start, end):
    i = start
    while i < end:
        eid, size, d = read_head(b, i)
        yield eid, i, d, d + size
        i = d + size


def main(src, dst):
    b = open(src, 'rb').read()
    eid, hsize, hdata = read_head(b, 0)
    seg = hdata + hsize  # the Segment starts right after the EBML header
    seg_id, seg_size, seg_data = read_head(b, seg)
    assert eid == 0x1A45DFA3 and seg_id == SEGMENT, 'not a WebM file'
    seg_end = len(b) if seg_size is None else seg_data + seg_size

    info = tracks = None
    clusters = []  # (payload bytes, [(time_ms, offset of the keyframe block in the payload)])
    video_track, last_video = None, 0
    i = seg_data
    while i < seg_end:
        eid, size, d = read_head(b, i)
        end = seg_end if size is None else d + size
        if eid == INFO:
            info = b''.join(b[s:e] for cid, s, _, e in children(b, d, end) if cid != DURATION)
        elif eid == TRACKS:
            tracks = b[i:end]
            for _, _, ed, ee in children(b, d, end):  # TrackEntry
                num = kind = None
                for cid, _, cd, ce in children(b, ed, ee):
                    if cid == 0xD7:
                        num = int.from_bytes(b[cd:ce], 'big')
                    if cid == 0x83:
                        kind = int.from_bytes(b[cd:ce], 'big')
                if kind == 1:
                    video_track = num
        elif eid == CLUSTER:
            j, tc, keys = d, 0, []
            while j < end:  # an unknown-size cluster ends at the next top-level element
                cid, csize, cd = read_head(b, j)
                if cid in TOP_LEVEL:
                    end = j
                    break
                ce = cd + csize
                if cid == 0xE7:
                    tc = int.from_bytes(b[cd:ce], 'big')
                elif cid in (0xA0, 0xA3):  # BlockGroup / SimpleBlock
                    blk = [(cd, ce)] if cid == 0xA3 else [(xd, xe) for x, _, xd, xe in children(b, cd, ce) if x == 0xA1]
                    has_ref = cid == 0xA0 and any(x == 0xFB for x, _, _, _ in children(b, cd, ce))
                    bd, _ = blk[0]
                    track, k = read_vint(b, bd)
                    t = tc + int.from_bytes(b[bd + k:bd + k + 2], 'big', signed=True)
                    key = (b[bd + k + 2] & 0x80) if cid == 0xA3 else not has_ref
                    if track == video_track:
                        last_video = max(last_video, t)
                        if key:
                            keys.append((t, j - d))
                j = ce
            clusters.append((b[d:end], keys))
        i = end
    assert info is not None and tracks and clusters and video_track, 'unexpected WebM layout'

    duration_ms = last_video + 1000 / 30  # the last frame lasts one frame (30 fps)
    info_el = el(INFO, info + el(DURATION, struct.pack('>d', duration_ms)))
    seekhead_len = len(el(SEEKHEAD, b''.join(el(SEEK, uint_el(SEEKID, x, 4) + uint_el(SEEKPOS, 0, 8)) for x in (INFO, TRACKS, CUES))))
    pos = seekhead_len
    info_pos = pos; pos += len(info_el)
    tracks_pos = pos; pos += len(tracks)
    cluster_els, cue_points = [], []
    for payload, keys in clusters:
        for t, rel in keys:
            cue_points.append(el(0xBB, uint_el(0xB3, t) + el(0xB7, uint_el(0xF7, video_track) + uint_el(0xF1, pos) + uint_el(0xF0, rel))))
        cel = el(CLUSTER, payload)
        cluster_els.append(cel)
        pos += len(cel)
    cues_pos = pos
    seekhead = el(SEEKHEAD, b''.join(el(SEEK, uint_el(SEEKID, x, 4) + uint_el(SEEKPOS, p, 8)) for x, p in ((INFO, info_pos), (TRACKS, tracks_pos), (CUES, cues_pos))))
    body = seekhead + info_el + tracks + b''.join(cluster_els) + el(CUES, b''.join(cue_points))
    with open(dst, 'wb') as f:
        f.write(b[:seg] + el(SEGMENT, body))
    print(f'{dst}: {duration_ms / 1000:.2f} s, {len(clusters)} clusters, {len(cue_points)} seek points')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
