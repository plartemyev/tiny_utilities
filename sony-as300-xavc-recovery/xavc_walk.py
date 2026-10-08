"""Walk XAVC S (Sony Action Cam) group structure in damaged/unfinalized files.

Layout (empirical, from healthy C0461):
  mdat payload = repeating groups of:
    data track : 30 records x 1024 B, each starting with SIG
    video chunk: 30 AVCC NALUs (4-byte BE length prefix)
    audio chunk: 95919 B PCM s16be 48k stereo
Group sizes vary with video bitrate. First group starts at 192.
"""
import struct
import sys

SIG = bytes.fromhex('0008010000ad034b')
AUD_SIZE = 95919
RECS_PER_GROUP = 30
REC_SIZE = 1024


def find_groups(path):
    """Return list of group-start candidates (offsets of SIG record runs)."""
    size = __import__('os').path.getsize(path)
    groups = []
    with open(path, 'rb') as fh:
        # read in 8 MiB windows with 64 KiB back-overlap
        WIN = 8 << 20
        pos = 0
        prev_tail = b''
        base = 0
        while pos < size:
            fh.seek(pos)
            buf = fh.read(WIN)
            if not buf:
                break
            hay = prev_tail + buf
            start = 0
            while True:
                i = hay.find(SIG, start)
                if i < 0:
                    break
                groups.append(base - len(prev_tail) + i)
                start = i + 1
            prev_tail = hay[-(64 << 10):]
            base = pos + len(buf)
            pos += len(buf)
    # keep only offsets that begin a plausible run of 30 records at 1024 stride
    good = []
    with open(path, 'rb') as fh:
        for g in groups:
            fh.seek(g + (RECS_PER_GROUP - 1) * REC_SIZE)
            tail = fh.read(8)
            if tail == SIG:
                good.append(g)
    return good


def chain_frames(path, start, limit):
    """Walk AVCC NALUs from start; return (n_frames, end_offset, nal_sizes, break_kind)."""
    n = 0
    off = start
    sizes = []
    with open(path, 'rb') as fh:
        while off + 4 <= limit:
            fh.seek(off)
            hdr = fh.read(4)
            if len(hdr) < 4:
                return n, off, sizes, 'eof'
            ln = struct.unpack('>I', hdr)[0]
            if ln < 2 or off + 4 + ln > limit:
                return n, off, sizes, f'badlen:{ln}'
            fh.seek(off + 4)
            nb = fh.read(1)
            if not nb:
                return n, off, sizes, 'eof'
            ntype = nb[0] & 0x1f
            if ntype == 0 or ntype > 12:
                return n, off, sizes, f'naltype:{ntype}'
            sizes.append(ln)
            off += 4 + ln
            n += 1
    return n, off, sizes, 'limit'


def analyze(path):
    print(f"== {path} ==")
    size = __import__('os').path.getsize(path)
    groups = find_groups(path)
    print(f"  file size {size} ({size/2**20:.1f} MiB), {len(groups)} group starts")
    if not groups:
        return
    with open(path, 'rb') as fh:
        prev_end = None
        total_frames = 0
        for gi, g in enumerate(groups):
            # count records in run
            run = 0
            off = g
            fh.seek(off)
            while True:
                fh.seek(off)
                if fh.read(8) != SIG:
                    break
                run += 1
                off += REC_SIZE
                if run > 64:
                    break
            vstart = g + RECS_PER_GROUP * REC_SIZE
            # limit: next group start (or file end)
            nxt = groups[gi + 1] if gi + 1 < len(groups) else size
            nfr, fend, fsz, why = chain_frames(path, vstart, nxt)
            total_frames += nfr
            vbytes = sum(fsz)
            gap = '' if prev_end is None else f' prev_gap={g - prev_end}'
            print(f"  G{gi:03d} @{g:>11}: records={run:>2} video@{vstart} frames={nfr:>3} "
                  f"({vbytes/2**20:6.2f} MiB) end={fend} next={nxt} rest={nxt-fend} [{why}]{gap}")
            prev_end = nxt
        print(f"  TOTAL frames parsed: {total_frames}")


if __name__ == '__main__':
    for p in sys.argv[1:]:
        analyze(p)
