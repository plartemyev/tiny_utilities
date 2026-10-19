# opencode-power-saver

Tampermonkey userscript that cuts the CPU/GPU/battery cost of the **opencode
web UI** (`opencode serve`, verified against 2.0.32) — especially while agent
sessions stream.

Design constraint (v0.3.0): **no unloading, no reloads** — the session stays
fully alive in every mode; power saving happens at the delivery/render layer.
The old hard-freeze (SSE kill + reload on wake) still exists but is opt-in.

`opencode-power-saver.user.js` is the script; everything below explains what
it does, why, and how to verify it.

## What actually burns GPU in this UI (probed, not guessed)

Findings from inspecting the live DOM/bundles of the 2.0.32 web UI:

1. **The timeline is already virtualized.** A 50-message session keeps only
   ~4-12 turn containers in the DOM, and collapsed tool bodies are NOT mounted
   (Solid `<Show>`). The naive `content-visibility` on messages (the usual
   advice) targets a non-problem here.
2. **Class-name selectors match nothing.** The UI is Tailwind utility soup
   with shadcn-style hooks: the real selectors are `[data-slot=...]` /
   `[data-component=...]`. A draft with `[class*="message"]`, `[class*="part"]`,
   `details` matched 0/0/0 elements.
3. **Every collapsed row embeds the animated-number machinery**: ~30
   `animated-number-cell` elements per digit (`animated-number-strip`, 390 px
   tall, clipped to 13 px), re-laid-out on every token-count change — that is
   300+ cells re-rendering while you only see "Thinking… +42".
4. **Real hot spots while streaming:**
   - `markdown-word-enter`: per-word 0.18s fade-in — hundreds of concurrent
     animations during generation.
   - `text-shimmer` / pulse decorations on the "working" indicator.
   - **The SSE event flood itself**: every token chunk arrives on
     `GET /api/event` and triggers Solid re-render + style/layout/paint.
     Browsers do not composite hidden tabs (GPU ~0 there), but an **unfocused
     window on X11 is still "visible"** — Firefox keeps rendering the
     firehose at event rate (10-30 frames/s) even though nobody sees it.
     Measured: ~12% GPU / ~30% CPU in the WebRender process for a watched
     streaming session with all CSS animations already dead.
5. The app does **not** respect `prefers-reduced-motion`.

## What the script does

| Feature | Mechanism | Effect |
|---|---|---|
| `killMotion` | CSS: `animation: none` on word-enter/shimmer/pulse, `transition: none` on counters | Removes per-frame animation work; counters jump instantly |
| `hideDigitStrips` | CSS: `display: none` on the 30-cell digit strips + force the static digit visible | Same numbers on screen (static digit renders the same value in the same grid cell), hundreds of cells no longer laid out/painted per chunk |
| `contentVisibility` | CSS: `content-visibility: auto` on markdown leaves (`pre`, `img`, `video`) | Skips layout/paint of scrolled-out code blocks/media |
| `softThrottleEvents` | Wraps `fetch('/api/event')`: while the tab is hidden **or the window unfocused**, SSE chunks are buffered and flushed at ~1 Hz. Focused delivery is immediate pass-through | Unseen rendering drops from event-rate to ~1 frame/s. **Every byte still arrives, in order, no reload, no state loss** — verified byte-exact against a stub stream |
| `freezeWhenHidden` (opt-in, default off) | Hard freeze: `window.stop()`, sockets closed, animations paused, "⏸ paused" overlay, reload on wake | Near-zero dormant tab at the cost of one reload; also available manually: `__ocPowerSaver.freeze()` / `.wake()` |

The soft throttle is the piece that matches "I do not want my session to
unload when I switch tabs": switching tabs (hidden) costs no GPU natively and
now also renders at ~1 Hz instead of per-chunk; leaving the *window* behind
others (X11 never reports occlusion) drops to the same ~1 Hz. Refocus →
instant pass-through, state already current.

### Honest floor

A session you are **actively watching** (window focused, stream visible)
must repaint while text streams in — no userscript makes a live view free.
The motion/digit kills trim the decorative part; the rest is the price of
watching. To actually save GPU/battery, leave the window unfocused (or the
tab hidden) and check back with a click.

## Install (Firefox + Tampermonkey)

1. Install **Tampermonkey** from addons.mozilla.org (MV2 works fine on
   current Firefox).
2. Tampermonkey icon → **Dashboard** → `+` (new script) → delete the template
   → paste the full contents of `opencode-power-saver.user.js` → `Ctrl+S`.
3. The `@match` list covers the default opencode port 4096 and this host's
   instance on 49374 (`127.0.0.1` and `localhost`). Add your port if different.
4. Reload the opencode tab. After updating the script, reload the tab again.

No CSP problems: Tampermonkey content scripts bypass page CSP, and the
opencode server allows inline styles anyway (`style-src ... 'unsafe-inline'`).

## Verify it is working

- Tampermonkey badge shows `1` on the opencode tab; devtools console shows
  `[oc-power-saver] active {...}`.
- Motion/digit kills:
  `getComputedStyle(document.querySelector('[data-slot="animated-number-strip"]')).display`
  → `none`; numbers on screen still show correct values.
- Soft throttle: `window.__ocPowerSaver.throttled` → `true` after clicking
  into another window. While an agent streams, the DevTools Performance
  record of the unfocused window should show render activity clustered in
  ~1 s bursts instead of continuous work.
- GPU: compare `grep -h drm-engine-gfx /proc/<firefox-pid>/fdinfo/*` sums
  (ns) across a few seconds (the process holding the dri fds is Firefox's
  WebRender/GPU funnel), or watch `about:processes`.
- Manual pause (kills SSE entirely): `__ocPowerSaver.freeze()`; resume with
  `.wake()` (one reload, draft restored) or the overlay click.

## Caveats / honest limits

- While throttled, the *rendering* of unseen updates is batched to ~1 Hz; the
  moment you focus the window again you see the current state (buffered
  chunks flush immediately). If Firefox intensive-throttles a long-hidden
  tab's timers to 1/min, flushes follow that cadence — still zero data loss.
- `freezeWhenHidden` (if you opt in) reloads on wake: in-tab UI state (open
  side panel, scrolled position, dialogs, composer attachments) resets;
  draft *text* is preserved. Not enabled by default.
- The freeze also aborts in-flight requests; submitting a prompt and
  instantly hiding the tab is still safe (localhost POSTs finish in ms, and
  the server processes submissions regardless of the UI).
- User-opened PTY terminals in the side panel are closed only by the manual/
  opt-in freeze; the reload re-establishes what the app persists.
- The agent/session work happens entirely server-side — nothing in this
  script can affect the run itself.
- If the UI changes its `data-slot` names (or SSE path), update the CSS
  constants / `/api/event` matcher at the top of the script.
