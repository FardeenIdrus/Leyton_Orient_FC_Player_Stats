// Shared helpers for every page (ES module). Names follow mockup v5 so page builders can lift
// its rendering code as-is. Nothing here computes a number: it only formats what the API sends.

/** HTML-escape. Use for every provider/user string put into innerHTML; prefer textContent. */
export const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

export const num = v => (v == null || v === '') ? null : Number(v);

/** Blank marker: "—" for null/undefined/'' /NaN, never "None"/"nan"/"undefined". */
export const dash = v => {
  if (v == null || v === '') return '—';
  if (typeof v === 'number' && !Number.isFinite(v)) return '—';
  const t = String(v);
  return /^(none|nan|null|undefined)$/i.test(t.trim()) ? '—' : t;
};

/** Whole number, half-up (Math.round on a .5 rounds toward +inf, which matches half-up for
 *  the non-negative minutes/goals this is used for; negatives round half away from zero). */
export const roundHalfUp = v => {
  const x = num(v);
  if (x == null || !Number.isFinite(x)) return null;
  return x < 0 ? -Math.floor(-x + 0.5) : Math.floor(x + 0.5);
};
export const fmtInt = v => {
  const r = roundHalfUp(v);
  return r == null ? '—' : r.toLocaleString('en-GB');
};

/** Rating chip c4..c0 (club 1-5 bands). */
export const chip = v => {
  const x = num(v);
  if (x == null || isNaN(x)) return '<span class="chip c0">—</span>';
  return `<span class="chip ${x >= 4 ? 'c4' : x >= 3 ? 'c3' : x >= 2 ? 'c2' : 'c1'}">${x.toFixed(2)}</span>`;
};

/** Percentile colour: green >=70, grey 30-69, red <30. */
export const pcol = p => p >= 70 ? 'var(--hi)' : p >= 30 ? 'var(--mid)' : 'var(--lo)';

/** Percentile bar (.pb). */
/** A percentile as a plain coloured number (green 70+, red below 30) -- where a bar has no room
 *  (owner 2026-11-10: the player page's physical tables). */
export const pctNum = p => {
  const x = num(p);
  if (x == null || isNaN(x)) return '<span class="note">—</span>';
  const r = Math.round(x);
  return `<span class="pctn${r >= 70 ? ' hi' : r < 30 ? ' lo' : ''}">${r}</span>`;
};
export const bar = p => {
  const x = num(p);
  if (x == null || isNaN(x)) return '<span class="note">—</span>';
  const r = Math.round(x);
  return `<div class="pb"><div class="t"><i style="width:${r}%;background:${pcol(r)}"></i></div><b>${r}</b></div>`;
};

/** Table header row; numeric-looking column names are right-aligned. */
export const thead = cols => '<tr>' + cols.map(c =>
  `<th${/^(Per|Season total|All phases|In possession|Out of possession|Minutes|Mins|Days|Matches|Goals|Assists|npxG|xA|Age|#|Top speed)/.test(c) ? ' class="n"' : ''}>${esc(c)}</th>`
).join('') + '</tr>';

/** Pills: cls is strong | lean | grey | verdict-pos | verdict-neg | verdict-mid. */
export const pills = (arr, cls) =>
  (arr || []).map(s => `<span class="pill ${esc(cls)}">${esc(s)}</span>`).join('');

// ---- Radar (TASKS 2.36 U2/U10) --------------------------------------------------------------
// radar() returns a placeholder; the chart is drawn at the placeholder's real pixel width (so
// text is true size and never shrinks with the chart), redrawn when that width changes. The
// legend toggles lines, points show a tooltip, wheel/pinch zooms, drag pans, double-click
// resets. All interaction is delegated once, here, so every page gets it by importing this.

/** Line colours and styles: target (player A) ink, other players orange / teal, our position
 *  median Orient blue dashed, league median red dotted. */
export const RADAR = {
  players: ['#15171C', '#D9822B', '#2A9D8F'],
  orient: '#1F5FA8', league: '#C8102E',
  dash: {orient: '7 4', league: '2 4'},
};

/** Series for the Orient / our-position median line. */
export const orientSeries = (values, name) =>
  ({values, name, colour: RADAR.orient, dash: RADAR.dash.orient, width: 2});

const _specs = new Map();
let _rid = 0;

/** Radar chart. axes: [label]; series: [{values (0-100 percentiles), name, colour?, dash?,
 *  width?, fill?, dots?, raw?: [display value per axis]}] -- the first is the main player,
 *  whose percentile is printed at each label. opts.league (default true) adds the league
 *  median (50) ring as a legend item. Returns HTML; drawn when it lands in the page. */
export function radar(axes, series, opts = {}) {
  if (typeof opts !== 'object' || opts === null) opts = {};
  const id = 'r' + (++_rid);
  const S = series.map((x, i) => ({...x, colour: x.colour || RADAR.players[i] || RADAR.players[0],
    name: x.name || `Series ${i + 1}`, width: x.width || (i === 0 ? 2.4 : 2),
    fill: x.fill !== undefined ? x.fill : (i === 0 ? 'rgba(21,23,28,.07)' : 'none'),
    dots: x.dots !== undefined ? x.dots : i === 0}));
  const league = opts.league !== false;
  _specs.set(id, {axes: axes.map(String), series: S, league});
  if (_specs.size > 60) _specs.delete(_specs.keys().next().value);
  const sw = (colour, dash, width) => `<svg width="30" height="10" aria-hidden="true"><line x1="1" y1="5" x2="29" y2="5" stroke="${colour}" stroke-width="${Math.max(2, width)}" stroke-linecap="round"${dash ? ` stroke-dasharray="${dash}"` : ''}/></svg>`;
  const keys = S.map((x, i) =>
    `<button type="button" class="rdr-key" data-s="${i}" aria-pressed="true" aria-label="Show or hide ${esc(x.name)}">${sw(x.colour, x.dash, x.width)}<span>${esc(x.name)}</span></button>`).join('')
    + (league ? `<button type="button" class="rdr-key" data-s="league" aria-pressed="true" aria-label="Show or hide League median">${sw(RADAR.league, RADAR.dash.league, 2)}<span>League median</span></button>` : '');
  return `<figure class="rdr" data-rdr="${id}" data-off="">`
    + `<div class="rdr-stage"></div>`
    + `<div class="rdr-tools"><button type="button" data-z="in" aria-label="Zoom in">+</button><button type="button" data-z="out" aria-label="Zoom out">−</button><button type="button" data-z="reset" aria-label="Reset zoom">⟲</button></div>`
    + `<figcaption class="rdr-legend">${keys}</figcaption></figure>`;
}

let _ctx = null;
const _measure = (text, font) => {
  if (!_ctx) _ctx = document.createElement('canvas').getContext('2d');
  _ctx.font = font;
  return _ctx.measureText(text).width;
};

/** Split a label into lines no wider than maxW px (words never broken), at most 3 lines. */
function _wrap(label, font, maxW) {
  const words = label.split(/\s+/), lines = [];
  let cur = '';
  for (const w of words) {
    const t = cur ? cur + ' ' + w : w;
    if (cur && _measure(t, font) > maxW) { lines.push(cur); cur = w; } else cur = t;
  }
  if (cur) lines.push(cur);
  while (lines.length > 3) { const last = lines.pop(); lines[lines.length - 1] += ' ' + last; }
  return lines;
}

/** Lay out and draw spec at width W (px). Returns {svg, w, h}. */
function _draw(spec, W) {
  const {axes, series, league} = spec;
  const n = axes.length, main = series[0];
  const fam = getComputedStyle(document.body).fontFamily || 'system-ui, sans-serif';
  const FS = 12.5, LH = 15, font = `600 ${FS}px ${fam}`, vfont = `700 ${FS}px ${fam}`;
  // side labels wrap narrow (width is what limits the chart); top/bottom ones may be wider
  const sideMax = Math.min(118, Math.max(78, W * 0.16)), endMax = Math.min(150, Math.max(96, W * 0.24));
  const L = axes.map((a, i) => {
    const v = main.values[i];
    const vtxt = v == null ? '—' : String(Math.round(v));
    const c0 = Math.cos(-Math.PI / 2 + 2 * Math.PI * i / n);
    const lines = _wrap(a, font, Math.abs(c0) > 0.45 ? sideMax : endMax);
    const ws = lines.map((l, k) => _measure(l, font) + (k === lines.length - 1 ? _measure(' ' + vtxt, vfont) : 0));
    const ang = -Math.PI / 2 + 2 * Math.PI * i / n;
    return {lines, v, vtxt, w: Math.max(...ws), h: lines.length * LH, cos: Math.cos(ang), sin: Math.sin(ang)};
  });
  const sideW = Math.max(60, ...L.filter(l => Math.abs(l.cos) > 0.45).map(l => l.w));
  const RMAX = 300, RMIN = 90;
  let R = Math.max(RMIN, Math.min(RMAX, W / 2 - sideW - 16));
  let out;
  // grow into spare width, shrink on overflow (labels pushed outward can widen the chart)
  for (let tries = 0; tries < 10; tries++) {
    out = _layout(L, R);
    const spare = (W - 6) - (out.maxX - out.minX);
    if (spare < 0 && R > RMIN) { R = Math.max(RMIN, R + spare / 2 - 2); continue; }
    if (spare > 16 && R < RMAX && tries < 6) { R = Math.min(RMAX, R + spare / 2 - 4); continue; }
    if (spare >= 0 || R <= RMIN) break;
  }
  const {boxes, minX, maxX, minY, maxY} = out;
  const pt = (i, v) => {
    const r = R * Math.max(0, Math.min(100, v ?? 0)) / 100;
    return [(r * L[i].cos).toFixed(1), (r * L[i].sin).toFixed(1)];
  };
  let g = '';
  [25, 75, 100].forEach(k => {
    g += `<polygon points="${L.map((_, i) => pt(i, k).join(',')).join(' ')}" fill="none" stroke="#E2E4E8" stroke-width="1"/>`;
  });
  L.forEach((_, i) => { const [x, y] = pt(i, 100); g += `<line x1="0" y1="0" x2="${x}" y2="${y}" stroke="#E8EAED"/>`; });
  if (league) g += `<g class="rdr-s" data-s="league"><polygon points="${L.map((_, i) => pt(i, 50).join(',')).join(' ')}" fill="none" stroke="${RADAR.league}" stroke-width="1.6" stroke-dasharray="${RADAR.dash.league}" stroke-linecap="round"/></g>`;
  // draw back to front: the main player last, on top
  const order = series.map((_, k) => k).reverse();
  let hits = '';
  order.forEach(k => {
    const s = series[k];
    if (!s.values.some(v => v != null)) return;
    let h = `<g class="rdr-s" data-s="${k}"><polygon points="${L.map((_, i) => pt(i, s.values[i]).join(',')).join(' ')}" fill="${s.fill || 'none'}" stroke="${s.colour}" stroke-width="${s.width}" stroke-linejoin="round"${s.dash ? ` stroke-dasharray="${s.dash}"` : ''}/>`;
    L.forEach((l, i) => {
      const v = s.values[i];
      if (v == null) return;
      const [x, y] = pt(i, v);
      if (s.dots) h += `<circle cx="${x}" cy="${y}" r="3.6" fill="${s.colour}"/>`;
      const raw = s.raw && s.raw[i] != null && s.raw[i] !== '' ? ` · ${s.raw[i]}` : '';
      const tip = `${s.name}\n${axes[i]}${raw} · P${Math.round(v)}`;
      hits += `<circle class="rdr-hit" data-s="${k}" cx="${x}" cy="${y}" r="9" fill="transparent" data-tip="${esc(tip)}"/>`;
    });
    g += h + '</g>';
  });
  g += `<g class="rdr-hits">${hits}</g>`;
  let t = '';
  L.forEach((l, i) => {
    const b = boxes[i];
    const al = l.cos > 0.25 ? 'start' : l.cos < -0.25 ? 'end' : 'middle';
    const x = al === 'start' ? b.x1 : al === 'end' ? b.x2 : (b.x1 + b.x2) / 2;
    const col = l.v == null ? '#5D6470' : pcol(l.v);
    t += `<text x="${x.toFixed(1)}" y="${(b.y1 + LH / 2).toFixed(1)}" font-size="${FS}" font-weight="600" text-anchor="${al}" dominant-baseline="central" fill="#15171C">`
      + l.lines.map((ln, k) => `<tspan x="${x.toFixed(1)}"${k ? ` dy="${LH}"` : ''}>${esc(ln)}</tspan>`
        + (k === l.lines.length - 1 ? `<tspan class="rdr-v" fill="${col}" font-weight="700"> ${esc(l.vtxt)}</tspan>` : '')).join('')
      + '</text>';
  });
  const vx = Math.floor(minX - 4), vy = Math.floor(minY - 4);
  const vw = Math.ceil(maxX - minX + 8), vh = Math.ceil(maxY - minY + 8);
  const svg = `<svg class="rdr-svg" viewBox="${vx} ${vy} ${vw} ${vh}" data-vb="${vx} ${vy} ${vw} ${vh}" width="${vw}" height="${vh}" role="img" aria-label="Radar chart">${g}${t}</svg>`;
  return {svg, w: vw, h: vh};
}

/** Place every label outside a circle of radius R, centred on 0,0: each label's box is
 *  anchored continuously by its angle, then pushed outward until it touches neither the
 *  chart nor any other label; a second pass pulls each one back in as far as it can go. */
function _layout(L, R) {
  const PAD = 12;
  const boxAt = (l, off) => {
    const x = (R + off) * l.cos, y = (R + off) * l.sin;
    const x1 = x - l.w * (1 - l.cos) / 2, y1 = y - l.h * (1 - l.sin) / 2;
    return {x1, y1, x2: x1 + l.w, y2: y1 + l.h, off};
  };
  const hit = (a, b) => a.x1 < b.x2 + PAD && b.x1 < a.x2 + PAD && a.y1 < b.y2 + 4 && b.y1 < a.y2 + 4;
  const clearOfChart = b => {
    const nx = Math.max(b.x1, Math.min(0, b.x2)), ny = Math.max(b.y1, Math.min(0, b.y2));
    return Math.hypot(nx, ny) > R + 6;
  };
  const fits = (b, others) => clearOfChart(b) && !others.some(o => o && hit(o, b));
  const boxes = [];
  L.forEach((l, i) => {
    let b;
    for (let off = 10; off < 240; off += 4) { b = boxAt(l, off); if (fits(b, boxes)) break; }
    boxes[i] = b;
  });
  for (let pass = 0; pass < 2; pass++) {
    L.forEach((l, i) => {
      const others = boxes.filter((_, j) => j !== i);
      for (let off = 10; off < boxes[i].off; off += 4) {
        const b = boxAt(l, off);
        if (fits(b, others)) { boxes[i] = b; break; }
      }
    });
  }
  let minX = -R, maxX = R, minY = -R, maxY = R;
  boxes.forEach(b => { minX = Math.min(minX, b.x1); maxX = Math.max(maxX, b.x2); minY = Math.min(minY, b.y1); maxY = Math.max(maxY, b.y2); });
  return {boxes, minX, maxX, minY, maxY};
}

function _render(fig) {
  const spec = _specs.get(fig.dataset.rdr);
  const stage = fig.querySelector('.rdr-stage');
  if (!spec || !stage) return;
  const W = Math.floor(stage.clientWidth);
  if (W < 40 || Math.abs(W - (+fig.dataset.w || 0)) < 6) return;
  fig.dataset.w = W;
  const d = _draw(spec, W);
  stage.innerHTML = d.svg;
  _applyOff(fig);
  Object.assign(fig, {_s: 1, _tx: 0, _ty: 0});
  fig.classList.remove('zoomed');
}

function _applyOff(fig) {
  const off = new Set((fig.dataset.off || '').split(',').filter(Boolean));
  fig.querySelectorAll('.rdr-s, .rdr-hit').forEach(g => { g.style.display = off.has(g.dataset.s) ? 'none' : ''; });
  fig.querySelectorAll('.rdr-v').forEach(v => { v.style.display = off.has('0') ? 'none' : ''; });
  fig.querySelectorAll('.rdr-key').forEach(k => {
    const on = !off.has(k.dataset.s);
    k.setAttribute('aria-pressed', String(on)); k.classList.toggle('off', !on);
  });
}

// Zoom / pan: the svg keeps its size and its viewBox moves (nothing overflows the card).
// s = scale, tx/ty = pan in screen px (<= 0); applied in one animation frame.
function _setVB(fig, s, tx, ty) {
  const svg = fig.querySelector('.rdr-svg');
  const [bx, by, bw, bh] = svg.dataset.vb.split(' ').map(Number);
  const k = bw / (svg.clientWidth || bw);
  svg.setAttribute('viewBox', s > 1.001
    ? `${(bx - tx * k / s).toFixed(2)} ${(by - ty * k / s).toFixed(2)} ${(bw / s).toFixed(2)} ${(bh / s).toFixed(2)}`
    : svg.dataset.vb);
}
function _zoom(fig, s, tx, ty, animate = false) {
  const svg = fig.querySelector('.rdr-svg');
  if (!svg) return;
  const w = svg.clientWidth || +svg.getAttribute('width'), h = svg.clientHeight || +svg.getAttribute('height');
  s = Math.max(1, Math.min(6, s));
  tx = Math.min(0, Math.max(w * (1 - s), tx));
  ty = Math.min(0, Math.max(h * (1 - s), ty));
  const from = {s: fig._s || 1, tx: fig._tx || 0, ty: fig._ty || 0};
  Object.assign(fig, {_s: s, _tx: tx, _ty: ty});
  fig.classList.toggle('zoomed', s > 1.001);
  if (fig._raf) cancelAnimationFrame(fig._raf);
  const t0 = performance.now(), D = animate ? 160 : 0;
  const step = now => {
    const a = D ? Math.min(1, (now - t0) / D) : 1, e = 1 - Math.pow(1 - a, 3);
    _setVB(fig, from.s + (s - from.s) * e, from.tx + (tx - from.tx) * e, from.ty + (ty - from.ty) * e);
    fig._raf = a < 1 ? requestAnimationFrame(step) : 0;
  };
  fig._raf = requestAnimationFrame(step);
}
function _zoomAt(fig, factor, ev, animate) {
  const svg = fig.querySelector('.rdr-svg');
  if (!svg) return;
  const s = fig._s || 1, tx = fig._tx || 0, ty = fig._ty || 0;
  const r = svg.getBoundingClientRect();
  const px = ev ? ev.clientX - r.left : r.width / 2, py = ev ? ev.clientY - r.top : r.height / 2;
  const ns = Math.max(1, Math.min(6, s * factor));
  _zoom(fig, ns, px - (px - tx) * ns / s, py - (py - ty) * ns / s, animate);
}

let _tip = null;
function _showTip(text, ev) {
  if (!_tip) { _tip = document.createElement('div'); _tip.className = 'tip'; _tip.setAttribute('role', 'tooltip'); document.body.appendChild(_tip); }
  _tip.textContent = text;
  _tip.hidden = false;
  const m = 14, w = _tip.offsetWidth, h = _tip.offsetHeight;
  let x = ev.clientX + m, y = ev.clientY + m;
  if (x + w > innerWidth - 8) x = ev.clientX - w - m;
  if (y + h > innerHeight - 8) y = ev.clientY - h - m;
  _tip.style.transform = `translate(${Math.round(x)}px,${Math.round(y)}px)`;
}
const _hideTip = () => { if (_tip) _tip.hidden = true; };

function _installRadar() {
  if (window.__lofcRadar) return;
  window.__lofcRadar = true;
  const ro = new ResizeObserver(entries => entries.forEach(e => _render(e.target.closest('.rdr'))));
  const seen = new WeakSet();
  const scan = () => document.querySelectorAll('.rdr[data-rdr]').forEach(fig => {
    if (seen.has(fig)) return;
    seen.add(fig);
    _render(fig);
    ro.observe(fig.querySelector('.rdr-stage'));
  });
  new MutationObserver(scan).observe(document.documentElement, {childList: true, subtree: true});
  scan();
  // legend + zoom buttons
  document.addEventListener('click', ev => {
    const k = ev.target.closest('.rdr-key');
    if (k) {
      const fig = k.closest('.rdr');
      const off = new Set((fig.dataset.off || '').split(',').filter(Boolean));
      off.has(k.dataset.s) ? off.delete(k.dataset.s) : off.add(k.dataset.s);
      fig.dataset.off = [...off].join(',');
      _applyOff(fig);
      return;
    }
    const z = ev.target.closest('.rdr-tools button');
    if (z) {
      const fig = z.closest('.rdr');
      if (z.dataset.z === 'reset') _zoom(fig, 1, 0, 0, true);
      else _zoomAt(fig, z.dataset.z === 'in' ? 1.5 : 1 / 1.5, null, true);
    }
  });
  document.addEventListener('dblclick', ev => {
    const fig = ev.target.closest('.rdr-stage') && ev.target.closest('.rdr');
    if (fig) { ev.preventDefault(); _zoom(fig, 1, 0, 0, true); }
  });
  // Wheel: a pinch (ctrl+wheel) always zooms; a plain wheel zooms once the chart was clicked
  // or is already zoomed, so scrolling down the page past a chart never gets stuck in it.
  document.addEventListener('wheel', ev => {
    const fig = ev.target.closest && ev.target.closest('.rdr-stage') && ev.target.closest('.rdr');
    if (!fig || !(ev.ctrlKey || fig.classList.contains('active') || fig.classList.contains('zoomed'))) return;
    ev.preventDefault();
    _zoomAt(fig, Math.exp(-ev.deltaY * (ev.ctrlKey ? 0.01 : 0.0025)), ev, false);
  }, {passive: false});
  // drag to pan; two fingers pinch
  const ptrs = new Map();
  let drag = null;
  document.addEventListener('pointerdown', ev => {
    const stage = ev.target.closest && ev.target.closest('.rdr-stage');
    if (!stage) return;
    const fig = stage.closest('.rdr');
    document.querySelectorAll('.rdr.active').forEach(f => f !== fig && f.classList.remove('active'));
    fig.classList.add('active');
    ptrs.set(ev.pointerId, {x: ev.clientX, y: ev.clientY});
    if (ptrs.size === 2) {
      const [a, b] = [...ptrs.values()];
      drag = {fig, pinch: Math.hypot(a.x - b.x, a.y - b.y)};
    } else if ((fig._s || 1) > 1.001 || ev.pointerType === 'touch') {
      drag = {fig, x: ev.clientX, y: ev.clientY, tx: fig._tx || 0, ty: fig._ty || 0};
      stage.setPointerCapture(ev.pointerId);
      fig.classList.add('dragging');
    }
  });
  document.addEventListener('pointermove', ev => {
    if (ptrs.has(ev.pointerId)) ptrs.set(ev.pointerId, {x: ev.clientX, y: ev.clientY});
    if (drag) {
      if (drag.pinch && ptrs.size === 2) {
        const [a, b] = [...ptrs.values()], d = Math.hypot(a.x - b.x, a.y - b.y);
        _zoomAt(drag.fig, d / drag.pinch, {clientX: (a.x + b.x) / 2, clientY: (a.y + b.y) / 2}, false);
        drag.pinch = d;
      } else if (!drag.pinch) {
        _zoom(drag.fig, drag.fig._s || 1, drag.tx + ev.clientX - drag.x, drag.ty + ev.clientY - drag.y, false);
      }
      _hideTip();
      return;
    }
    const t = ev.target.closest && ev.target.closest('[data-tip]');
    if (t) _showTip(t.dataset.tip, ev); else _hideTip();
  }, {passive: true});
  const end = ev => {
    ptrs.delete(ev.pointerId);
    if (drag) { drag.fig.classList.remove('dragging'); if (ptrs.size < 2) drag = null; }
  };
  document.addEventListener('pointerup', end);
  document.addEventListener('pointercancel', end);
  document.addEventListener('pointerout', ev => {
    if (!ev.relatedTarget || !ev.relatedTarget.closest || !ev.relatedTarget.closest('[data-tip]')) _hideTip();
    const fig = ev.target.closest && ev.target.closest('.rdr');
    if (fig && (!ev.relatedTarget || !fig.contains(ev.relatedTarget))) fig.classList.remove('active');
  });
  addEventListener('scroll', _hideTip, {passive: true});
  document.addEventListener('focusin', ev => {
    const t = ev.target.closest && ev.target.closest('[data-tip]');
    if (!t) return;
    const r = t.getBoundingClientRect();
    _showTip(t.dataset.tip, {clientX: r.left, clientY: r.bottom});
  });
  document.addEventListener('focusout', ev => { if (ev.target.closest && ev.target.closest('[data-tip]')) _hideTip(); });
}
// ---- table column alignment (owner bug 2026-11-09) -------------------------------------------
// A rating column (cells holding a .chip) is centred, heading included, so the chip sits under
// its heading at every width; a numeric column (cells .n) gets a right-aligned heading. Runs on
// every table as it is drawn (before paint), so no page has to remember it.
function _alignTable(t) {
  const hr = t.tHead && t.tHead.rows.length ? t.tHead.rows[t.tHead.rows.length - 1] : null;
  if (!hr || [...hr.cells].some(c => c.colSpan > 1)) return;
  const n = hr.cells.length;
  const rows = [...(t.tBodies[0] ? t.tBodies[0].rows : [])].filter(r => r.cells.length === n
    && !r.classList.contains('sec') && ![...r.cells].some(c => c.colSpan > 1));
  if (!rows.length) return;
  const sample = rows.slice(0, 12);
  for (let i = 0; i < n; i++) {
    const cells = sample.map(r => r.cells[i]);
    const chipCol = cells.some(c => c.querySelector('.chip'))
      && cells.every(c => c.querySelector('.chip') || !(c.textContent || '').trim() || /^[—–-]$/.test(c.textContent.trim()));
    if (chipCol) {
      hr.cells[i].classList.add('c'); hr.cells[i].classList.remove('n');
      rows.forEach(r => { r.cells[i].classList.add('c'); r.cells[i].classList.remove('n'); });
    } else if (cells.filter(c => c.classList.contains('n')).length > cells.length / 2) {
      hr.cells[i].classList.add('n');
    }
  }
}
// Help text on headings and score tiles: the shared instant tooltip (data-tip) with a small ⓘ,
// never the browser's slow title; reachable by keyboard (focus shows it).
function _helpTips(root) {
  root.querySelectorAll('main th[title], main .score[title], main .tile[title], main .hlp[title], main .chip[title]').forEach(el => {
    el.dataset.tip = el.getAttribute('title');
    el.removeAttribute('title');
    el.classList.add('has-help');
    if (el.matches('.hlp, .chip')) return;              // already its own marker
    if (!el.hasAttribute('tabindex') && !el.querySelector('button')) el.tabIndex = 0;
    if (el.querySelector('.hlp, .hlp-i')) return;
    const host = el.matches('th') ? (el.querySelector('button') || el) : (el.querySelector('.k') || el);
    host.insertAdjacentHTML('beforeend', '<span class="hlp-i" aria-hidden="true">ⓘ</span>');
  });
}
let _alignQueued = false;
function _alignAll() {
  _alignQueued = false;
  _helpTips(document);
  document.querySelectorAll('main table').forEach(_alignTable);
}
function _installAlign() {
  if (window.__lofcAlign) return;
  window.__lofcAlign = true;
  new MutationObserver(() => { if (!_alignQueued) { _alignQueued = true; queueMicrotask(_alignAll); } })
    .observe(document.documentElement, {childList: true, subtree: true});
  _alignAll();
}

// ---- card prefetch on intent (TASKS 2.36 S-C) ------------------------------------------------
// A pointer resting ~80 ms on (or a touch starting on) a link to a player card asks the server to
// build that card now (header X-LOFC-Prefetch); the card page's own request then takes the built
// answer (lofc.web.prefetch). One request at a time, cancelled when the pointer leaves, read-only
// GETs only, and never the same card twice within 30 s.
const _pfDone = new Map();
let _pf = null;            // {url, ctrl, timer}
function _cardApi(el) {
  const href = el.getAttribute('data-href') || el.getAttribute('href') || '';
  const m = href.match(/^\/player\/(\d+)\/(\d+)\/(\d+)(\?.*)?$/);
  if (!m) return null;
  const q = new URLSearchParams(m[4] || ''), out = new URLSearchParams();
  if (q.get('rank_as')) out.set('rank_as', q.get('rank_as'));
  if (['1', 'true', 'on'].includes((q.get('money') || '').toLowerCase())) out.set('money', '1');
  const s = out.toString();
  return `/api/card/${m[1]}/${m[2]}/${m[3]}${s ? '?' + s : ''}`;
}
function _pfCancel() {
  if (!_pf) return;
  clearTimeout(_pf.timer);
  if (_pf.ctrl) _pf.ctrl.abort();
  _pf = null;
}
function _pfStart(el, delay) {
  const url = _cardApi(el);
  if (!url || (_pf && _pf.url === url)) return;
  const t = _pfDone.get(url);
  if (t && Date.now() - t < 30000) return;
  _pfCancel();
  const me = {url, ctrl: null, timer: 0, el};
  me.timer = setTimeout(() => {
    me.ctrl = new AbortController();
    fetch(url, {headers: {'X-LOFC-Prefetch': '1', 'Accept': 'application/json'}, credentials: 'same-origin',
                signal: me.ctrl.signal})
      .then(r => { if (r.ok) _pfDone.set(url, Date.now()); return r.text(); })
      .catch(() => {})
      .finally(() => { if (_pf === me) _pf = null; });
  }, delay);
  _pf = me;
}
function _installPrefetch() {
  if (window.__lofcPrefetch || document.getElementById('v-card')) return;
  window.__lofcPrefetch = true;
  const target = ev => ev.target.closest && ev.target.closest('[data-href^="/player/"], a[href^="/player/"]');
  document.addEventListener('pointerover', ev => { const el = target(ev); if (el) _pfStart(el, 80); }, {passive: true});
  document.addEventListener('pointerout', ev => {
    const el = target(ev);
    if (el && _pf && _pf.el === el && !(ev.relatedTarget && el.contains(ev.relatedTarget))) {
      _pfCancel();     // the server keeps any card it has started; a later click still takes it
    }
  }, {passive: true});
  document.addEventListener('touchstart', ev => { const el = target(ev); if (el) _pfStart(el, 0); }, {passive: true});
}

if (typeof document !== 'undefined') {
  const start = () => { _installRadar(); _installAlign(); _installPrefetch(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
}

/** fetch JSON. POST/PUT/PATCH/DELETE get the X-LOFC-Request header the server requires;
 *  a 401 sends the browser to /login. Resolves to the parsed body; rejects on other errors
 *  with an Error carrying .status and .body. opts.json is sent as a JSON body. */
export async function api(url, opts = {}) {
  const method = (opts.method || (opts.json !== undefined ? 'POST' : 'GET')).toUpperCase();
  const headers = {'Accept': 'application/json', ...(opts.headers || {})};
  if (method !== 'GET' && method !== 'HEAD') headers['X-LOFC-Request'] = '1';
  let body = opts.body;
  if (opts.json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.json); }
  const res = await fetch(url, {method, headers, body, credentials: 'same-origin', signal: opts.signal});
  if (res.status === 401) { window.location.href = '/login'; throw Object.assign(new Error('not signed in'), {status: 401}); }
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw Object.assign(new Error(`HTTP ${res.status}`), {status: res.status, body: data});
  return data;
}

// ---- URL state: filters + the open player live in the query string (shareable, back/forward).
/** Current query string as a plain object. */
export const readState = () => Object.fromEntries(new URLSearchParams(window.location.search));

/** Merge `patch` into the query string (null/''/undefined removes a key) and push a history
 *  entry (replace:true swaps instead). Does not reload. */
export function writeState(patch, {replace = false} = {}) {
  const q = new URLSearchParams(window.location.search);
  for (const [k, v] of Object.entries(patch)) {
    if (v == null || v === '') q.delete(k); else q.set(k, String(v));
  }
  const url = window.location.pathname + (q.toString() ? '?' + q.toString() : '');
  window.history[replace ? 'replaceState' : 'pushState']({}, '', url);
}

/** Run `fn(state)` on back/forward. Returns an unsubscribe function. */
export function onStateChange(fn) {
  const h = () => fn(readState());
  window.addEventListener('popstate', h);
  return () => window.removeEventListener('popstate', h);
}
