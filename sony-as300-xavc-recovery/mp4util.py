"""Minimal MP4 box walker + XAVC S analysis helpers (Sony HDR-AS300 recovery)."""
import struct


def boxes(buf):
    """Yield (type, payload_offset, payload_size) for sibling boxes in buf."""
    off = 0
    while off + 8 <= len(buf):
        sz, typ = struct.unpack('>I4s', buf[off:off + 8])
        hs = 8
        if sz == 1:
            if off + 16 > len(buf):
                break
            sz = struct.unpack('>Q', buf[off + 8:off + 16])[0]
            hs = 16
        elif sz == 0:
            sz = len(buf) - off
        if sz < hs or off + sz > len(buf):
            break
        yield typ, off + hs, sz - hs
        off += sz


def find_top(data, typ):
    for t, off, sz in boxes(data):
        if t == typ:
            return off, sz
    return None


def trak_info(trak):
    """Return (hdlr_type, stsz_sizes, stco_offsets, stsc) for a trak box payload."""
    hdlr = None
    minf = None
    for t, off, sz in boxes(trak):
        if t == b'hdlr':
            hdlr = trak[off + 8:off + 12]
        if t == b'mdia':
            for t2, off2, sz2 in boxes(trak[off:off + sz]):
                if t2 == b'minf':
                    minf = trak[off + off2:off + off2 + sz2]
    if minf is None:
        return hdlr, None, None, None
    stbl = None
    for t2, off2, sz2 in boxes(minf):
        if t2 == b'stbl':
            stbl = minf[off2:off2 + sz2]
    if stbl is None:
        return hdlr, None, None, None
    stsz = stco = stsc = None
    for t2, off2, sz2 in boxes(stbl):
        if t2 == b'stsz':
            stsz = stbl[off2:off2 + sz2]
        if t2 == b'stco':
            stco = stbl[off2:off2 + sz2]
        if t2 == b'stsc':
            stsc = stbl[off2:off2 + sz2]
    n, ssz = struct.unpack('>II', stsz[4:12])
    sizes = [ssz] * n if ssz else list(struct.unpack(f'>{n}I', stsz[12:12 + 4 * n]))
    nch = struct.unpack('>I', stco[4:8])[0]
    chunks = list(struct.unpack(f'>{nch}I', stco[8:]))
    return hdlr, sizes, chunks, stsc


def chunk_map(sizes, chunks, stsc):
    """Map samples -> (chunk_offset, intra_chunk_index). stsc raw payload."""
    entries = []
    n = struct.unpack('>I', stsc[4:8])[0]
    for i in range(n):
        first, per, idx = struct.unpack('>III', stsc[8 + 12 * i:20 + 12 * i])
        entries.append((first, per, idx))
    res = []
    si = 0
    for ci, coff in enumerate(chunks):
        per = 0
        for e_i, (first, p, idx) in enumerate(entries):
            if first - 1 == ci:
                nxt = entries[e_i + 1][0] - 1 if e_i + 1 < len(entries) else len(chunks)
                per = p * (nxt - ci > 0 and 1 or 1) if nxt > ci else p
        # simpler: find applicable run
        per = entries[0][1]
        for e_i, (first, p, idx) in enumerate(entries):
            if first - 1 <= ci:
                nxt = entries[e_i + 1][0] - 1 if e_i + 1 < len(entries) else 10 ** 9
                if ci < nxt:
                    per = p
        for _ in range(per):
            if si >= len(sizes):
                break
            res.append((coff, si, sizes[si]))
            si += 1
    return res
