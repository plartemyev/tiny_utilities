// ==UserScript==
// @name         OpenCode Web UI Power Saver
// @namespace    tiny-utilities
// @version      0.3.0
// @description  Cuts CPU/GPU/battery cost of the opencode web UI: kills decorative motion and digit-strip churn, soft-throttles the /api/event SSE firehose while the tab is hidden or the window unfocused (all events still delivered, no reload, no state loss). Optional hard freeze stays opt-in.
// @author       pasha
// @match        http://127.0.0.1:4096/*
// @match        http://localhost:4096/*
// @match        http://127.0.0.1:49374/*
// @match        http://localhost:49374/*
// @run-at       document-start
// @noframes
// @grant        none
// ==/UserScript==

(function () {
  'use strict';

  const CONFIG = {
    // Continuous/decorative animation kill (word-enter fades, shimmer, pulses).
    // One-shot dialog entrance animations and small spinners are left alone.
    killMotion: true,
    // content-visibility on heavy leaves inside rendered turns (code blocks, media).
    contentVisibility: true,
    // Hide the 30-cells-per-digit animated-number strips in every collapsed
    // tool/thinking row. The static digit (content: attr(data-digit)) renders in
    // the same grid cell and shows the same value; combined with transition:none
    // (numbers jump instantly) this is visually lossless and removes a large
    // layout/paint subtree that re-renders on every token-count change.
    hideDigitStrips: true,
    // While the tab is hidden OR the window unfocused, buffer /api/event SSE
    // chunks and deliver them at ~1 Hz instead of per-chunk. Every event still
    // arrives in order (state stays exact, NO reload, NO unloading); unseen
    // rendering drops from event-rate (10-30 frames/s) to ~1 frame/s. Focused
    // delivery is immediate pass-through.
    softThrottleEvents: true,
    softThrottleFlushMs: 1000,
    // OPT-IN hard freeze (window.stop() the SSE, pause animations, overlay,
    // reload-on-wake). OFF by default: soft throttling already handles the
    // background case without unloading anything. Enable only if you want a
    // near-zero-cost dormant tab and accept one reload on return.
    freezeWhenHidden: false,
    hideDelayMs: 20000,
    // Restore the composer draft across any resync reload (manual freeze only).
    preserveDrafts: true,
  };

  // ---------------------------------------------------------------- CSS ----
  // Selectors verified against opencode 2.0.32 web UI (data-slot/data-component
  // attributes; Tailwind class names are minified utilities and match nothing).
  const CSS = `
/* streaming text: per-word 0.18s fade-in, hundreds concurrently during generation */
[data-component="markdown"] [data-markdown-word][data-markdown-enter],
[data-component="markdown"] code[data-markdown-enter] {
  animation: none !important;
}

/* token-count counters: 0.56s spring transitions (top/width) on every count
   change -> instant jumps; and drop the 30-digit-cell strips entirely (the
   static digit renders the same value in the same grid cell) */
[data-slot="animated-number-strip"],
[data-slot="animated-number-value"],
[data-slot="animated-number-value"][data-resizing="true"] {
  transition: none !important;
}
` + (CONFIG.hideDigitStrips ? `
[data-slot="animated-number-strip"] {
  display: none !important;
}
/* the app hides the static digit while data-animating=true and clears the flag
   on transitionend - which never fires with the strip display:none. Force the
   static digit visible so numbers never blank out. */
[data-slot="animated-number-digit"][data-animating="true"] [data-slot="animated-number-static"] {
  visibility: visible !important;
}
` : '') + `
/* continuous decorative motion while the agent works */
[data-slot^="text-shimmer"],
[data-slot="tab-prompt-pulse"] {
  animation: none !important;
}

/* heavy leaves inside a rendered turn: highlighted code blocks and media are
   skipped for layout/paint when scrolled out of the viewport */
[data-component="markdown"] pre,
[data-component="markdown"] img,
[data-component="markdown"] video {
  content-visibility: auto;
  contain-intrinsic-size: auto 160px;
}
`;

  // At document-start document.head/documentElement can both be null; bounded
  // retry (200 x 5ms = 1s) so the CSS lands before the app's first paint.
  function addCssWhenReady(text, attempts) {
    if (document.head) {
      const style = document.createElement('style');
      style.id = 'oc-power-saver-css';
      style.textContent = text;
      document.head.append(style);
      return;
    }
    if (attempts <= 0) return;
    setTimeout(function () { addCssWhenReady(text, attempts - 1); }, 5);
  }

  // ------------------------------------------------------- focus state -----
  let unfocused = typeof document.hasFocus === 'function' ? !document.hasFocus() : false;
  window.addEventListener('blur', function () { unfocused = true; });
  window.addEventListener('focus', function () { unfocused = false; });
  function softThrottled() {
    return unfocused || document.hidden;
  }

  // ------------------------------------------------ soft-throttled SSE -----
  // The app fetches GET /api/event and consumes response.body as a stream.
  // While unfocused/hidden we buffer chunks and flush the whole buffer once per
  // tick; byte order is preserved and the app's SSE parser re-assembles events,
  // so nothing is lost or reordered - it just arrives in bigger, rarer bites.
  function wrapEventStreamResponse(resp) {
    if (!resp.ok || !resp.body) return resp;
    const reader = resp.body.getReader();
    const buffer = [];
    let flushTimer = null;
    let done = false;

    function flush() {
      if (done) return;
      while (buffer.length) {
        controller.enqueue(buffer.shift());
      }
    }
    let controller = null;
    const stream = new ReadableStream({
      start(c) {
        controller = c;
        (function read() {
          reader.read().then(function (r) {
            if (r.done) {
              flush(); // drain the tail buffer BEFORE closing: no byte loss
              done = true;
              if (flushTimer) { clearInterval(flushTimer); flushTimer = null; }
              controller.close();
              return;
            }
            if (softThrottled()) {
              buffer.push(r.value);
              if (!flushTimer) {
                flushTimer = setInterval(function () {
                  flush();
                  if (done && flushTimer) { clearInterval(flushTimer); flushTimer = null; }
                }, CONFIG.softThrottleFlushMs);
              }
            } else {
              controller.enqueue(r.value);
            }
            read();
          }, function (e) { controller.error(e); });
        })();
      },
      cancel() {
        done = true;
        if (flushTimer) { clearInterval(flushTimer); flushTimer = null; }
        reader.cancel();
      },
    });
    return new Response(stream, { status: resp.status, statusText: resp.statusText, headers: resp.headers });
  }

  // ------------------------------------------------------------- freeze ----
  let frozen = false;
  let hideTimer = null;
  const liveSockets = new Set();

  // Installed before app code runs (document-start); the app wraps fetch too
  // and special-cases pathname /api/event on top of ours.
  const origFetch = window.fetch;
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (frozen && url.indexOf('/api/event') !== -1) {
      return new Promise(function () {}); // hang forever: blocks SSE reconnect
    }
    const p = origFetch.call(this, input, init);
    if (CONFIG.softThrottleEvents && !frozen && url.indexOf('/api/event') !== -1) {
      return p.then(function (resp) {
        try { return wrapEventStreamResponse(resp); } catch (e) { return resp; }
      });
    }
    return p;
  };

  // Track WebSockets (terminal/PTY panel) so a manual freeze can close them.
  const NativeWebSocket = window.WebSocket;
  function WrappedWebSocket(url, protocols) {
    const ws = protocols === undefined ? new NativeWebSocket(url)
                                       : new NativeWebSocket(url, protocols);
    if (frozen) {
      setTimeout(function () { ws.close(); }, 0);
    } else {
      liveSockets.add(ws);
      ws.addEventListener('close', function () { liveSockets.delete(ws); });
    }
    return ws;
  }
  WrappedWebSocket.prototype = NativeWebSocket.prototype;
  WrappedWebSocket.CONNECTING = NativeWebSocket.CONNECTING;
  WrappedWebSocket.OPEN = NativeWebSocket.OPEN;
  WrappedWebSocket.CLOSING = NativeWebSocket.CLOSING;
  WrappedWebSocket.CLOSED = NativeWebSocket.CLOSED;
  window.WebSocket = WrappedWebSocket;

  function showPausedOverlay() {
    if (document.getElementById('oc-power-saver-overlay')) return;
    const el = document.createElement('div');
    el.id = 'oc-power-saver-overlay';
    el.textContent = '⏸ opencode paused (power saver) — click to resume';
    el.style.cssText = 'position:fixed;right:12px;bottom:12px;z-index:2147483647;' +
      'background:#111;color:#eee;font:12px/1.4 system-ui,sans-serif;padding:8px 12px;' +
      'border-radius:8px;cursor:pointer;opacity:.85;box-shadow:0 2px 8px rgba(0,0,0,.4)';
    el.addEventListener('click', wake);
    (document.body || document.documentElement).append(el);
  }

  // Manual/opt-in dormant mode: SSE dead, sockets closed, animations paused,
  // resync via reload on wake. NOT triggered automatically unless
  // CONFIG.freezeWhenHidden is enabled.
  function freeze() {
    if (frozen) return;
    if (document.querySelector('#server-connect-url')) return;
    frozen = true;
    try { window.stop(); } catch (e) {}
    for (const ws of liveSockets) {
      try { ws.close(); } catch (e) {}
    }
    try { document.getAnimations().forEach(function (a) { a.pause(); }); } catch (e) {}
    if (document.title.indexOf('⏸') !== 0) document.title = '⏸ ' + document.title;
    if (!document.hidden) showPausedOverlay();
    console.info('[oc-power-saver] frozen (paused)');
  }

  // Composer is a contenteditable div on session pages, a textarea elsewhere.
  function getComposer() {
    return document.querySelector('#root div[contenteditable="true"]') ||
           document.querySelector('[data-slot="text-input-v2-input"]');
  }

  function composerText(c) {
    return c.contentEditable === 'true' ? c.innerText : c.value;
  }

  function setComposerText(c, text) {
    if (c.contentEditable === 'true') {
      c.innerText = text;
      c.dispatchEvent(new Event('input', { bubbles: true }));
    } else {
      c.value = text;
      c.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }

  function snapshotDraft() {
    try {
      const c = getComposer();
      const text = c ? composerText(c).trim() : '';
      if (text) sessionStorage.setItem('oc-power-saver:draft', text);
    } catch (e) {}
  }

  function wake() {
    if (!frozen) return;
    if (CONFIG.preserveDrafts) snapshotDraft();
    try { sessionStorage.setItem('oc-power-saver:reloaded', String(Date.now())); } catch (e) {}
    location.reload(); // app boots fresh, refetches state, re-attaches SSE
  }

  if (CONFIG.freezeWhenHidden) {
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) {
        if (!hideTimer) hideTimer = setTimeout(freeze, CONFIG.hideDelayMs);
      } else {
        if (hideTimer) { clearTimeout(hideTimer); hideTimer = null; }
        if (frozen) wake();
      }
    });
  }

  // ----------------------------------------------------- draft restore -----
  function restoreDraft() {
    let reloaded = null;
    let draft = null;
    try {
      reloaded = sessionStorage.getItem('oc-power-saver:reloaded');
      draft = sessionStorage.getItem('oc-power-saver:draft');
      sessionStorage.removeItem('oc-power-saver:reloaded');
      sessionStorage.removeItem('oc-power-saver:draft');
    } catch (e) { return; }
    if (!reloaded || !draft) return;
    // App mounts asynchronously; bounded retry loop (max 20 x 250ms = 5s).
    let attempts = 0;
    const timer = setInterval(function () {
      const c = getComposer();
      attempts += 1;
      if (c || attempts >= 20) {
        clearInterval(timer);
        if (c && !composerText(c).trim()) {
          setComposerText(c, draft);
          console.info('[oc-power-saver] composer draft restored');
        }
      }
    }, 250);
  }

  // ---------------------------------------------------------------- init ---
  addCssWhenReady(CSS, 200);
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', restoreDraft);
  } else {
    restoreDraft();
  }
  window.__ocPowerSaver = {
    get frozen() { return frozen; },
    get throttled() { return softThrottled(); },
    freeze, // manual pause: __ocPowerSaver.freeze() / resume: __ocPowerSaver.wake()
    wake,
    config: CONFIG,
  };
  console.info('[oc-power-saver] active', CONFIG);
})();
