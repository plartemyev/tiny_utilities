# sony-as300-xavc-recovery

Recover **unfinalized** Sony XAVC S recordings (HDR-AS300 action cam) whose
`.MP4` files look destroyed: no `ftyp` box, ffprobe says *"moov atom not
found"*, and the first bytes are random garbage. The video/audio essence is
actually 100% intact — only the MP4 index (written at finalize) is missing,
plus the first 192 bytes are overwritten *on the card itself*. This tool
carves the essence straight out of the `mdat` payload and remuxes it into
playable MP4s, stream-copy only (no re-encode).

Verified end-to-end on 5 real clips (31 s … 7:14, 1080p59.94 H.264 + PCM),
all restored to full length.

## Symptoms vs. reality

| What you see | What it is |
|---|---|
| No `ftyp`, ffprobe: "moov atom not found" | Recording never finalized (camera crashed / battery pulled / card pulled) |
| First 192 bytes random or `0x55`-patterned | Overwrite baked into the card at recording time — stable across reads |
| "1 MiB video, then 2 MiB random garbage" byte map | False alarm: H.264 at ~50 Mbps has byte entropy ≈ 8.00 with ~0.4% zeros — indistinguishable from random by entropy. Only the NALU length-chain walk proves video |
| Two files with *identical* sizes (e.g. 2688 MiB exactly) | Camera preallocation, not equal recordings |

## Essence layout (reverse-engineered)

After `ftyp`+`uuid` (176 bytes, often destroyed), the `mdat` payload is a
flat repetition of **groups**, each ≈ 0.5 s of recording:

```
group (variable size, ~3.2 MiB at ~50 Mbps):
┌──────────────────────────────────────────────────────────────┐
│ 30 × 1024 B per-frame KLV metadata records                   │
│   each record starts with SIG 00 08 01 00 00 ad 03 4b        │
├──────────────────────────────────────────────────────────────┤
│ video chunk: 30 H.264 access units, AVCC format              │
│   (4-byte big-endian length prefix per NALU)                 │
│   AU = AUD(9 B) + SEI(6 B) + slices (5 IDR or 1 P)           │
│   ⚠ no in-band SPS/PPS — they live only in the (missing) moov│
├──────────────────────────────────────────────────────────────┤
│ audio chunk: 96096 B PCM s16be 48 kHz stereo                 │
│   = exactly 30 frames @ 59.94 fps → proves the frame rate    │
│     without any moov (96096 / 48000 / 4 / 30 · 60000/1001)   │
└──────────────────────────────────────────────────────────────┘
```

The first group starts at offset 192. Group sizes vary with bitrate.

## Usage

Requirements: `python3`, `ffmpeg` on PATH.

```
# main recovery (multiple sources OK; output next to the extracted .264/.pcm)
python3 recover.py <dst_dir> <healthy_reference.MP4> <damaged1.MP4> [damaged2.MP4 ...]

# structure analysis of a damaged/unfinalized file (group starts, frame chains)
python3 xavc_walk.py <damaged.MP4> [...]

# minimal MP4 box walker used during the reverse engineering
python3 mp4util.py   # library, not a CLI
```

The **healthy reference** is any finalized clip from the *same camera in the
same recording mode* — its `avcC` provides the SPS/PPS NALUs that the damaged
files don't carry in-band. Parameters are identical across the camera's
clips, so injection is safe.

Example (the run that validated this tool):

```
python3 recover.py recovered ~/Videos/raw/C0461.MP4 \
    ~/Videos/raw/damaged/C0457.MP4 ~/Videos/raw/damaged/C0458.MP4 ...
```

Per input file this writes `<label>.264` (Annex B, SPS/PPS injected once up
front), `<label>.pcm` and `<label>_recovered.mp4` (H.264 + PCM, `+faststart`)
into `<dst_dir>` and prints group/frame/audio-duration stats.

## How recover.py works

1. **Find group starts**: scan for SIG (`00 08 01 00 00 ad 03 4b`) in
   8 MiB windows with 64 KiB back-overlap; keep only offsets that begin a
   plausible run of 30 records at 1024-byte stride.
2. **Verify video chains**: from each group's video start, walk the AVCC
   4-byte length prefixes; any NALU type outside 1–12 or a length overrun
   marks a corrupt tail.
3. **Trim crash tails**: if a group doesn't chain cleanly (file ends
   mid-frame), cut the elements after the last complete access unit (last
   AUD NALU).
4. **Emit Annex B**: every NALU gets a `00 00 00 01` start code; SPS/PPS
   come from the reference `avcC` (emitted once before the first frame);
   any stray in-band SPS/PPS is dropped.
5. **Carry audio**: per group, the PCM chunk follows the last kept video
   byte and is clamped to the next group/EOF, so a trimmed video tail
   doesn't add phantom audio (A/V stays in sync).
6. **Mux**: `ffmpeg -f h264 -r 60000/1001 -i v.264 -f s16be -ar 48000
   -ac 2 -i a.pcm -c copy`.

## Gotchas (each one bit during the real recovery)

1. **Entropy proves nothing.** ~50 Mbps H.264 ≈ 8.00 byte entropy, 0.4 %
   zeros — don't classify essence as "garbage"; only the length-chain walk
   distinguishes video from noise.
2. **Dedupe sliding-window signature hits.** Window overlap double-reports
   a SIG hit, and every phantom group silently added 0.5 s of audio with no
   video → cumulative A/V drift.
3. **Frame rate is provable from the audio chunk size** (96096 B = 0.5005 s
   = 30 frames → 59.94 fps) — no moov needed.
4. **Equal unfinalized file sizes are preallocation**, not equal
   recordings — group counts (i.e. durations) still differ.
5. **If one file has a mangled header, suspect the card, not the copy.**
   The 192-byte overwrite was identical on re-reads and on the card
   originals. Salvage the card contents first, retire the card.
6. **A single corrupt frame can survive full chain validation** — chain
   validity checks lengths/types, not slice payload correctness. Expect (at
   worst) isolated glitched frames; here exactly one in 7:14 of footage.

## Files

- `recover.py` — carve + remux recovery tool (authoritative constants live here)
- `xavc_walk.py` — structure-analysis walker (group starts, NALU chain report)
- `mp4util.py` — minimal MP4 box walker (analysis helper from the reverse engineering)
