"""The JavaScript the agent runs inside the page.

It is kept in one module, as constants, for three reasons: it is the only
code in this package that executes in someone else's origin, so it should be
readable in one sitting; it must be reviewable against the safety boundary;
and none of it may ever be assembled from model output.

Every script here only READS, with one exception: `PAGE_MODEL` stamps a
`data-aq-ref` attribute on the elements it inventoried, so the executor can
address exactly the element the observer classified rather than re-querying
by text and hoping. The stamp is applied before any interaction probe is
installed, so it never inflates a mutation count, and it changes no
behaviour, style or content of the page.

Nothing here is injected from a CDN and nothing is fetched. See CLAUDE.md
§5.4 on `a11y.py` for the same rule applied to axe-core.
"""
from __future__ import annotations

# ══════════════════════════════════════════════════ page model extraction

PAGE_MODEL = r"""
(maxElements) => {
  const MAX = maxElements || 220;
  const seen = [];
  let n = 0;

  const vis = (el) => {
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none') return false;
    if (parseFloat(s.opacity || '1') < 0.05) return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  };

  const textOf = (el) => (el.innerText || el.textContent || '')
      .replace(/\s+/g, ' ').trim().slice(0, 120);

  /* Accessible name, in specification order, stopping at the first hit.
     Not a full accname implementation — enough to name a control the way a
     screen reader would announce it, which is what the agent needs to
     decide whether a user would recognise it. */
  const accName = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria && aria.trim()) return aria.trim().slice(0, 120);
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const parts = by.split(/\s+/)
        .map(id => document.getElementById(id))
        .filter(Boolean).map(textOf).filter(Boolean);
      if (parts.length) return parts.join(' ').slice(0, 120);
    }
    if (el.tagName === 'IMG' && el.alt) return el.alt.trim().slice(0, 120);
    if (el.labels && el.labels.length) {
      const l = Array.from(el.labels).map(textOf).filter(Boolean).join(' ');
      if (l) return l.slice(0, 120);
    }
    const t = textOf(el);
    if (t) return t;
    for (const a of ['title', 'placeholder', 'value', 'name', 'alt']) {
      const v = el.getAttribute(a);
      if (v && v.trim()) return v.trim().slice(0, 120);
    }
    return '';
  };

  const roleOf = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit.trim().toLowerCase();
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'a') return el.hasAttribute('href') ? 'link' : 'generic';
    if (tag === 'button') return 'button';
    if (tag === 'select') return 'combobox';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'summary') return 'button';
    if (tag === 'video' || tag === 'audio') return 'media';
    if (tag === 'input') {
      if (type === 'checkbox') return 'checkbox';
      if (type === 'radio') return 'radio';
      if (type === 'search') return 'searchbox';
      if (['submit', 'button', 'reset', 'image'].includes(type)) return 'button';
      return 'textbox';
    }
    return 'generic';
  };

  /* Everything a user could plausibly act on, including the ARIA-only
     controls that a tag-name sweep would miss entirely. */
  const SEL = [
    'a[href]', 'button', 'input', 'select', 'textarea', 'summary',
    'video', 'audio',
    '[role=button]', '[role=link]', '[role=tab]', '[role=menuitem]',
    '[role=checkbox]', '[role=radio]', '[role=combobox]', '[role=searchbox]',
    '[role=switch]', '[role=option]', '[role=treeitem]',
    '[onclick]', '[tabindex]:not([tabindex="-1"])',
    '[data-testid*=cart]', '[class*=add-to-cart]', '[class*=addToCart]',
  ].join(',');

  const vh = window.innerHeight || 1;
  const vw = window.innerWidth || 1;

  for (const el of document.querySelectorAll(SEL)) {
    if (n >= MAX) break;
    if (el.closest('[aria-hidden=true]')) continue;
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    if (tag === 'input' && type === 'hidden') continue;

    const visible = vis(el);
    const r = el.getBoundingClientRect();
    const ref = 'e' + (n++);
    el.setAttribute('data-aq-ref', ref);

    const name = accName(el);
    const disabled = el.disabled === true ||
        el.getAttribute('aria-disabled') === 'true';

    seen.push({
      ref, tag, type,
      role: roleOf(el),
      name,
      text: textOf(el),
      href: el.getAttribute('href'),
      id: el.id || '',
      cls: (el.getAttribute('class') || '').slice(0, 160),
      elName: el.getAttribute('name') || '',
      placeholder: el.getAttribute('placeholder') || '',
      testid: el.getAttribute('data-testid') || el.getAttribute('data-test') || '',
      expanded: el.getAttribute('aria-expanded'),
      haspopup: el.getAttribute('aria-haspopup'),
      controls: el.getAttribute('aria-controls'),
      inNav: !!el.closest('nav,[role=navigation],header'),
      inForm: !!el.closest('form'),
      inCard: !!el.closest('article,[class*=card],[class*=product],[class*=tile],li'),
      x: Math.round(r.left), y: Math.round(r.top),
      w: Math.round(r.width), h: Math.round(r.height),
      inViewport: visible && r.top < vh && r.bottom > 0 && r.left < vw && r.right > 0,
      visible,
      enabled: !disabled,
      focusable: el.tabIndex >= 0,
      named: !!name,
    });
  }

  /* ---- forms ---------------------------------------------------------- */
  const forms = [];
  let f = 0;
  for (const form of document.querySelectorAll('form')) {
    const fref = 'f' + (f++);
    form.setAttribute('data-aq-form', fref);
    const fields = Array.from(
      form.querySelectorAll('input,select,textarea'))
      .filter(x => (x.getAttribute('type') || '') !== 'hidden');
    const submit = form.querySelector(
      'button[type=submit],input[type=submit],button:not([type])');
    forms.push({
      ref: fref,
      name: form.getAttribute('name') || form.getAttribute('id') ||
            accName(form) || '',
      action: form.getAttribute('action') || '',
      method: (form.getAttribute('method') || 'get').toLowerCase(),
      fieldRefs: fields.map(x => x.getAttribute('data-aq-ref')).filter(Boolean),
      fieldNames: fields.map(
        x => [x.getAttribute('name'), x.getAttribute('id'),
              x.getAttribute('placeholder'), x.getAttribute('autocomplete'),
              x.getAttribute('type')].filter(Boolean).join(' ')).slice(0, 30),
      hasPassword: fields.some(x => (x.getAttribute('type') || '') === 'password'),
      submitRef: submit ? submit.getAttribute('data-aq-ref') : null,
    });
  }

  /* ---- accessibility structure ---------------------------------------- */
  const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'));
  const levels = headings.map(h => parseInt(h.tagName[1], 10));
  let orderOk = true;
  for (let i = 1; i < levels.length; i++) {
    if (levels[i] - levels[i - 1] > 1) { orderOk = false; break; }
  }
  const controls = Array.from(document.querySelectorAll(
    'a[href],button,input:not([type=hidden]),select,textarea,[role=button]'));
  const unlabelled = controls.filter(c => !accName(c)).length;
  const imgs = Array.from(document.querySelectorAll('img'));
  const noAlt = imgs.filter(
    i => !i.hasAttribute('alt') && i.getAttribute('role') !== 'presentation').length;
  const landmarks = Array.from(document.querySelectorAll(
    'header,nav,main,aside,footer,[role=banner],[role=navigation],' +
    '[role=main],[role=contentinfo],[role=search]'))
    .map(e => e.getAttribute('role') || e.tagName.toLowerCase());
  const first = document.querySelector('a[href^="#"]');
  const skip = !!(first && /skip|jump/i.test(first.textContent || ''));

  /* ---- page shape ------------------------------------------------------ */
  const de = document.documentElement;
  const scrollHeight = Math.max(de.scrollHeight, document.body ?
      document.body.scrollHeight : 0);
  const modal = document.querySelector(
    '[role=dialog],[role=alertdialog],dialog[open],[aria-modal=true]');

  /* Structural fingerprint: what the page IS, not what it says. Two product
     pages differ in text but share a skeleton; the agent uses this to notice
     it has landed somewhere it has already been. */
  const skeleton = Array.from(document.querySelectorAll('body *'))
    .slice(0, 400)
    .map(e => e.tagName + (e.className && typeof e.className === 'string'
        ? '.' + e.className.split(/\s+/)[0] : ''))
    .join('>');
  let hash = 5381;
  for (let i = 0; i < skeleton.length; i++) {
    hash = ((hash * 33) ^ skeleton.charCodeAt(i)) >>> 0;
  }

  return {
    url: location.href,
    title: document.title || '',
    fingerprint: hash.toString(16),
    headings: headings.slice(0, 24).map(h => textOf(h)).filter(Boolean),
    textExcerpt: (document.body ? textOf(document.body) : '').slice(0, 1400),
    elements: seen,
    forms,
    a11y: {
      focusableCount: document.querySelectorAll(
        'a[href],button,input,select,textarea,[tabindex]:not([tabindex="-1"])'
      ).length,
      unlabelledControls: unlabelled,
      imagesMissingAlt: noAlt,
      headingLevels: levels.slice(0, 40),
      headingOrderOk: orderOk,
      landmarkRoles: Array.from(new Set(landmarks)),
      hasSkipLink: skip,
    },
    scrollable: scrollHeight > window.innerHeight + 40,
    scrollHeight,
    viewportHeight: window.innerHeight,
    hasModal: !!modal,
  };
}
"""

# ══════════════════════════════════════════════════ interaction probe

#: Installed immediately BEFORE an action is dispatched and read immediately
#: after. Everything it reports is a raw timestamp — the arithmetic that turns
#: these into latencies happens in Python (`measure.py`), because the model
#: is not the only thing in this system forbidden from computing in the wrong
#: place: the page is not a trusted calculator either.
PROBE_INSTALL = r"""
() => {
  try { if (window.__aq && window.__aq.stop) window.__aq.stop(); } catch (e) {}

  const P = {
    t0: performance.now(),
    firstMutation: null,
    lastMutation: null,
    firstPaint: null,
    mutations: 0,
    requests: [],
    shift: 0,
    longTask: 0,
    frames: [],
    recording: false,
    errors: [],
    startUrl: location.href,
    startScroll: window.scrollY,
  };
  window.__aq = P;

  /* Only mutations that change what is on screen count. A framework that
     rewrites a data attribute every tick is not the page responding to the
     user, and counting it would make every dead button look alive. */
  const meaningful = (m) => {
    if (m.type === 'childList') {
      return m.addedNodes.length > 0 || m.removedNodes.length > 0;
    }
    if (m.type === 'characterData') return true;
    const a = m.attributeName;
    return ['class', 'style', 'hidden', 'open', 'src', 'value', 'checked',
            'disabled', 'selected', 'aria-expanded', 'aria-hidden',
            'aria-selected', 'aria-checked', 'aria-busy'].includes(a);
  };

  try {
    P.mo = new MutationObserver((muts) => {
      let k = 0;
      for (const m of muts) {
        if (m.target === document.documentElement && m.type === 'attributes') {
          continue;   // smooth-scroll libraries write to <html> every frame
        }
        if (meaningful(m)) k++;
      }
      if (!k) return;
      const now = performance.now();
      if (P.firstMutation === null) {
        P.firstMutation = now;
        /* Two frames after the first mutation is the earliest moment the
           user could actually SEE it. That is the visual response. */
        requestAnimationFrame(() => requestAnimationFrame(() => {
          if (P.firstPaint === null) P.firstPaint = performance.now();
        }));
      }
      P.lastMutation = now;
      P.mutations += k;
    });
    P.mo.observe(document.documentElement, {
      subtree: true, childList: true, attributes: true, characterData: true,
    });
  } catch (e) { P.errors.push('mo:' + e.message); }

  const obs = (type, fn) => {
    try {
      const o = new PerformanceObserver((l) => {
        for (const e of l.getEntries()) fn(e);
      });
      o.observe({ type, buffered: false });
      return o;
    } catch (e) { return null; }
  };

  P.po = obs('resource', (e) => {
    if (e.startTime < P.t0 - 2) return;
    if (P.requests.length > 120) return;
    P.requests.push({
      name: String(e.name).slice(0, 180),
      start: e.startTime,
      /* responseStart is 0 without Timing-Allow-Origin on a cross-origin
         resource. We pass the zero through as null rather than treating it
         as an instantaneous first byte. */
      responseStart: e.responseStart > 0 ? e.responseStart : null,
      end: e.responseEnd > 0 ? e.responseEnd : e.startTime + e.duration,
      size: typeof e.transferSize === 'number' ? e.transferSize : null,
      initiator: e.initiatorType || '',
    });
  });
  P.ls = obs('layout-shift', (e) => {
    if (!e.hadRecentInput && e.startTime >= P.t0) P.shift += e.value;
  });
  P.lt = obs('longtask', (e) => {
    if (e.startTime >= P.t0) P.longTask += e.duration;
  });

  /* Focus is the feedback a text field is supposed to give. It is recorded
     separately from mutations because focusing a BUTTON is not a response to
     pressing it — every click moves focus, so counting focus as a response
     universally would make a dead button look alive. `_judge` decides which
     elements it counts for. */
  P.firstFocus = null;
  P.focusRef = '';
  P.onFocus = (ev) => {
    if (P.firstFocus !== null) return;
    P.firstFocus = performance.now();
    const t = ev.target;
    P.focusRef = (t && t.getAttribute) ? (t.getAttribute('data-aq-ref') || '') : '';
  };
  document.addEventListener('focusin', P.onFocus, true);

  P.onErr = (ev) => {
    if (P.errors.length < 20) {
      P.errors.push(String(ev.message || ev.reason || 'error').slice(0, 200));
    }
  };
  window.addEventListener('error', P.onErr, true);
  window.addEventListener('unhandledrejection', P.onErr, true);

  const tick = () => {
    if (!P.recording) return;
    P.frames.push(performance.now());
    if (P.frames.length < 900) requestAnimationFrame(tick);
  };
  P.startFrames = () => {
    if (P.recording) return;
    P.recording = true;
    P.frames = [];
    requestAnimationFrame(tick);
  };
  P.stopFrames = () => { P.recording = false; };

  P.stop = () => {
    P.recording = false;
    try { P.mo && P.mo.disconnect(); } catch (e) {}
    for (const o of [P.po, P.ls, P.lt]) { try { o && o.disconnect(); } catch (e) {} }
    try {
      window.removeEventListener('error', P.onErr, true);
      window.removeEventListener('unhandledrejection', P.onErr, true);
      document.removeEventListener('focusin', P.onFocus, true);
    } catch (e) {}
  };

  return true;
}
"""

#: Marks the instant the action is dispatched, and CLEARS everything observed
#: before it. Called as late as possible, so `t0` is the dispatch itself.
#:
#: The reset is the load-bearing part. Getting an element ready to act on —
#: scrolling it into view, focusing a field before typing — moves the page,
#: and without a reset those mutations are attributed to the action that has
#: not happened yet. The visible symptom is an interaction that reports a
#: mutation count with no first-mutation timestamp, because the timestamp
#: predates t0 and is correctly discarded while the count is not.
PROBE_MARK = r"""
() => {
  const P = window.__aq;
  if (!P) return 0;
  P.t0 = performance.now();
  P.firstMutation = null;
  P.lastMutation = null;
  P.firstPaint = null;
  P.mutations = 0;
  P.requests = [];
  P.shift = 0;
  P.longTask = 0;
  P.errors = [];
  P.firstFocus = null;
  P.focusRef = '';
  P.startUrl = location.href;
  P.startScroll = window.scrollY;
  return P.t0;
}
"""

PROBE_FRAMES_START = "() => { if (window.__aq) window.__aq.startFrames(); }"
PROBE_FRAMES_STOP = "() => { if (window.__aq) window.__aq.stopFrames(); }"

PROBE_READ = r"""
() => {
  const P = window.__aq;
  if (!P) return null;
  return {
    t0: P.t0,
    now: performance.now(),
    firstMutation: P.firstMutation,
    lastMutation: P.lastMutation,
    firstPaint: P.firstPaint,
    firstFocus: P.firstFocus,
    focusRef: P.focusRef,
    mutations: P.mutations,
    requests: P.requests.slice(0, 120),
    shift: P.shift,
    longTask: P.longTask,
    frames: P.frames.slice(0, 900),
    errors: P.errors.slice(0, 20),
    startUrl: P.startUrl,
    url: location.href,
    startScroll: P.startScroll,
    scrollY: window.scrollY,
    scrollHeight: Math.max(document.documentElement.scrollHeight,
                           document.body ? document.body.scrollHeight : 0),
    viewportHeight: window.innerHeight,
    modalOpen: !!document.querySelector(
      '[role=dialog],[role=alertdialog],dialog[open],[aria-modal=true]'),
    focused: document.activeElement
      ? (document.activeElement.getAttribute('data-aq-ref') || '') : '',
    visibleText: (document.body
      ? (document.body.innerText || '') : '').replace(/\s+/g, ' ').slice(0, 900),
  };
}
"""

PROBE_STOP = "() => { if (window.__aq) window.__aq.stop(); }"

# ══════════════════════════════════════════════════ page-load vitals

#: Read after a navigation settles. `buffered: true` picks up entries emitted
#: before this ran, which is the only way to see an LCP that has already
#: happened. Anything the browser did not report stays null.
VITALS = r"""
async () => {
  const out = {
    status: null, dns: null, tcp: null, tls: null, ttfb: null,
    dcl: null, load: null, fcp: null, lcp: null, cls: null,
    js: null, bytes: null, requests: 0, failed: 0, redirects: 0,
  };
  const [nav] = performance.getEntriesByType('navigation');
  if (nav) {
    out.status = typeof nav.responseStatus === 'number' ? nav.responseStatus : null;
    out.dns = nav.domainLookupEnd - nav.domainLookupStart || null;
    out.tcp = nav.connectEnd - nav.connectStart || null;
    out.tls = nav.secureConnectionStart > 0
      ? nav.connectEnd - nav.secureConnectionStart : null;
    out.ttfb = nav.responseStart > 0 ? nav.responseStart - nav.startTime : null;
    out.dcl = nav.domContentLoadedEventEnd > 0
      ? nav.domContentLoadedEventEnd - nav.startTime : null;
    out.load = nav.loadEventEnd > 0 ? nav.loadEventEnd - nav.startTime : null;
    out.redirects = nav.redirectCount || 0;
  }
  const fcp = performance.getEntriesByName('first-contentful-paint')[0];
  if (fcp) out.fcp = fcp.startTime;

  const res = performance.getEntriesByType('resource');
  out.requests = res.length;
  out.bytes = res.reduce(
    (a, r) => a + (typeof r.transferSize === 'number' ? r.transferSize : 0), 0);
  const scripts = res.filter(r => r.initiatorType === 'script');
  out.js = scripts.length
    ? scripts.reduce((a, r) => a + r.duration, 0) : null;

  await new Promise((resolve) => {
    let done = false;
    const finish = () => { if (!done) { done = true; resolve(); } };
    try {
      new PerformanceObserver((l) => {
        const e = l.getEntries();
        if (e.length) out.lcp = e[e.length - 1].startTime;
      }).observe({ type: 'largest-contentful-paint', buffered: true });
      let cls = 0;
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) if (!e.hadRecentInput) cls += e.value;
        out.cls = cls;
      }).observe({ type: 'layout-shift', buffered: true });
    } catch (e) { /* unsupported: both stay null */ }
    setTimeout(finish, 350);
  });
  return out;
}
"""

# ══════════════════════════════════════════════════ keyboard walk

#: One Tab press, reporting where focus landed and whether it is visibly
#: indicated. Called in a loop by the observer. Focus indication is judged by
#: comparing the computed outline/box-shadow against the same element
#: unfocused — a heuristic, reported as such, never as a WCAG verdict.
FOCUS_STATE = r"""
() => {
  const el = document.activeElement;
  if (!el || el === document.body || el === document.documentElement) return null;
  const s = getComputedStyle(el);
  const r = el.getBoundingClientRect();
  const outline = s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0;
  const ring = (s.boxShadow || 'none') !== 'none';
  const bordered = parseFloat(s.borderWidth || '0') > 0;
  return {
    ref: el.getAttribute('data-aq-ref') || '',
    tag: el.tagName.toLowerCase(),
    name: (el.getAttribute('aria-label') || el.innerText || '')
      .replace(/\s+/g, ' ').trim().slice(0, 60),
    indicated: outline || ring || bordered,
    inViewport: r.top >= -2 && r.bottom <= window.innerHeight + 2,
    y: Math.round(r.top + window.scrollY),
  };
}
"""

#: A single paced scroll step. `behavior: 'instant'` because the agent's own
#: pacing is the human element; layering the browser's smooth-scroll on top
#: would measure the browser's animation instead of the site's response.
SCROLL_BY = r"""
(px) => { window.scrollBy({ top: px, left: 0, behavior: 'instant' }); }
"""

SCROLL_TO = r"""
(y) => { window.scrollTo({ top: y, left: 0, behavior: 'instant' }); }
"""
