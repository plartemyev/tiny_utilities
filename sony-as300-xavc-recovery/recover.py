"""Recover unfinalized Sony XAVC S (HDR-AS300) recordings.

The recordings are structurally intact but missing the MP4 index (moov) and
the first 192 bytes (ftyp/uuid/mdat header). Essence layout per ~3.2 MiB group:
  30 x 1024 B per-frame metadata records (SIG-prefixed)
  video chunk: 30 H.264 access units as AVCC NALUs (4-byte BE length prefixes)
  audio chunk: 96096 B PCM s16be 48 kHz stereo (= exactly 30 frames @ 59.94)

Recovery: carve groups, verify NALU chains, emit Annex B video (+SPS/PPS from
a healthy reference avcC) and PCM audio, mux with ffmpeg.
"""
import struct
import subprocess
import sys
import os

SIG = bytes.fromhex('0008010000ad034b')
REC_SIZE = 1024
RECS = 30
AUD_BYTES = 96096          # per-group PCM payload (incl. 177 B tail)
FIRST_GROUP_OFF = 192                     # first group's metadata records start here
FPS = '60000/1001'
AUDIO_RATE, AUDIO_CH = 48000, 2
CHUNK = 8 << 20


def read_avc_param_sets(ref_path):
    """Extract SPS/PPS NALUs from a healthy XAVC S file's avcC."""
    data = open(ref_path, 'rb').read()

    def child_boxes(buf):
        off = 0
        while off + 8 <= len(buf):
            sz, typ = struct.unpack('>I4s', buf[off:off + 8])
            hs = 8
            if sz == 1:
                sz = struct.unpack('>Q', buf[off + 8:off + 16])[0]
                hs = 16
            elif sz == 0:
                sz = len(buf) - off
            if sz < hs or off + sz > len(buf):
                break
            yield typ, buf[off + hs:off + sz]
            off += sz

    moov = next(p for t, p in child_boxes(data) if t == b'moov')
    avcc = None
    for trak in (p for t, p in child_boxes(moov) if t == b'trak'):
        for mdia in (p for t, p in child_boxes(trak) if t == b'mdia'):
            hdlrs = [p[8:12] for t, p in child_boxes(mdia) if t == b'hdlr']
            if b'vide' not in hdlrs:
                continue
            for minf in (p for t, p in child_boxes(mdia) if t == b'minf'):
                for stbl in (p for t, p in child_boxes(minf) if t == b'stbl'):
                    for stsd in (p for t, p in child_boxes(stbl) if t == b'stsd'):
                        for t, p in child_boxes(stsd[8:]):
                            if t == b'avc1':
                                for t2, p2 in child_boxes(p[78:]):
                                    if t2 == b'avcC':
                                        avcc = p2
    assert avcc, 'avcC not found'
    p = 6
    n_sps = avcc[5] & 0x1f
    sps_list, pps_list = [], []
    for _ in range(n_sps):
        ln = struct.unpack('>H', avcc[p:p + 2])[0]
        sps_list.append(avcc[p + 2:p + 2 + ln])
        p += 2 + ln
    n_pps = avcc[p]
    p += 1
    for _ in range(n_pps):
        ln = struct.unpack('>H', avcc[p:p + 2])[0]
        pps_list.append(avcc[p + 2:p + 2 + ln])
        p += 2 + ln
    return sps_list, pps_list


def find_groups(path, fsize):
    """Group start offsets = SIG found at 1024-stride runs of 30 records."""
    cands = []
    with open(path, 'rb') as fh:
        pos, prev_tail, base = 0, b'', 0
        while pos < fsize:
            fh.seek(pos)
            buf = fh.read(CHUNK)
            if not buf:
                break
            hay = prev_tail + buf
            start = 0
            while True:
                i = hay.find(SIG, start)
                if i < 0:
                    break
                cands.append(base - len(prev_tail) + i)
                start = i + 1
            prev_tail = hay[-(64 << 10):]
            base = pos + len(buf)
            pos += len(buf)
    good = []
    with open(path, 'rb') as fh:
        for g in sorted(set(cands)):
            fh.seek(g + (RECS - 1) * REC_SIZE)
            if fh.read(8) == SIG:
                good.append(g)
    return good


def parse_group_video(path, vstart, vend):
    """Parse AVCC NALUs in [vstart, vend). Return (elements, break_reason);
    element = (nal_type, payload_offset, payload_len)."""
    els = []
    off = vstart
    with open(path, 'rb') as fh:
        while off + 4 <= vend:
            fh.seek(off)
            hdr = fh.read(4)
            if len(hdr) < 4:
                return els, 'eof'
            ln = struct.unpack('>I', hdr)[0]
            if ln < 2 or off + 4 + ln > vend:
                return els, f'badlen:{ln}'
            fh.seek(off + 4)
            nb = fh.read(1)
            ntype = nb[0] & 0x1f
            if ntype == 0 or ntype > 12:
                return els, f'naltype:{ntype}'
            els.append((ntype, off + 4, ln))
            off += 4 + ln
    return els, 'clean'


def drop_truncated_tail(elements):
    """Cut elements after the start of the last (incomplete) access unit."""
    last_aud = -1
    for i, (t, _, _) in enumerate(elements):
        if t == 9:
            last_aud = i
    return elements[:last_aud] if last_aud >= 0 else elements


def recover(src, dst_dir, ref, label):
    fsize = os.path.getsize(src)
    groups = find_groups(src, fsize)
    print(f"{label}: {fsize} bytes, {len(groups)} groups")
    assert groups and groups[0] == FIRST_GROUP_OFF, f"{label}: first group at {groups[:1]}"
    sps_list, pps_list = read_avc_param_sets(ref)
    v_out = open(os.path.join(dst_dir, label + '.264'), 'wb')
    a_out = open(os.path.join(dst_dir, label + '.pcm'), 'wb')

    def emit_param_sets():
        for nal in sps_list + pps_list:
            v_out.write(b'\x00\x00\x00\x01' + nal)

    total_au = 0
    dropped_tail = 0
    for gi, g in enumerate(groups):
        final = gi == len(groups) - 1
        vstart = g + RECS * REC_SIZE
        vend = groups[gi + 1] - AUD_BYTES if not final else fsize
        els, why = parse_group_video(src, vstart, vend)
        if why != 'clean':
            els = drop_truncated_tail(els)
            dropped_tail += 1
        # audio starts after the last kept video byte
        a_start = els[-1][1] + els[-1][2] if els else vstart
        # count access units (start at AUD)
        n_au = sum(1 for i, (t, _, _) in enumerate(els) if t == 9)
        total_au += n_au
        if gi == 0:
            emit_param_sets()
        for t, off, ln in els:
            if t in (7, 8):
                continue          # SPS/PPS injected from reference instead
            v_out.seek(0, 2)
            v_out.write(b'\x00\x00\x00\x01')
            with open(src, 'rb') as fh:
                fh.seek(off)
                remaining = ln
                while remaining > 0:
                    chunk = fh.read(min(remaining, CHUNK))
                    v_out.write(chunk)
                    remaining -= len(chunk)
        # audio: [a_start, a_start + AUD_BYTES) clamped to next group / EOF
        a_end = min(groups[gi + 1] if not final else fsize, a_start + AUD_BYTES)
        with open(src, 'rb') as fh:
            fh.seek(a_start)
            remaining = a_end - a_start
            while remaining > 0:
                chunk = fh.read(min(remaining, CHUNK))
                if not chunk:
                    break
                a_out.write(chunk)
                remaining -= len(chunk)
    # pad audio to a whole 4-byte sample count
    a_out.close()
    apath = os.path.join(dst_dir, label + '.pcm')
    sz = os.path.getsize(apath)
    with open(apath, 'ab') as fh:
        fh.write(b'\x00' * (-sz % 4))
    v_out.close()
    dur = total_au / (60000 / 1001)
    adur = os.path.getsize(apath) / (AUDIO_RATE * AUDIO_CH * 2)
    print(f"  AUs={total_au} (~{dur:.2f} s)  audio={adur:.2f} s  tail-cut groups={dropped_tail}")
    return dur, adur


def mux(dst_dir, label, workdir):
    v = os.path.join(dst_dir, label + '.264')
    a = os.path.join(dst_dir, label + '.pcm')
    out = os.path.join(dst_dir, label + '_recovered.mp4')
    cmd = ['ffmpeg', '-y', '-v', 'error', '-stats_period', '60',
           '-r', FPS, '-f', 'h264', '-i', v,
           '-f', 's16be', '-ar', str(AUDIO_RATE), '-ac', str(AUDIO_CH), '-i', a,
           '-c', 'copy', '-movflags', '+faststart', out]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stderr.strip()[-2000:] if r.stderr else '', file=sys.stderr)
    return out, r.returncode


if __name__ == '__main__':
    dst_dir = sys.argv[1]
    ref = sys.argv[2]
    os.makedirs(dst_dir, exist_ok=True)
    for src in sys.argv[3:]:
        label = os.path.splitext(os.path.basename(src))[0]
        recover(src, dst_dir, ref, label)
        out, rc = mux(dst_dir, label, dst_dir)
        print(f"  muxed -> {out} (rc={rc})")
