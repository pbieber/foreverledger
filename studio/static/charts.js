// The three ledger figures, drawn as one self-contained SVG so that what you see on
// screen is exactly what a PNG export contains. Money is integer copper throughout.
import { COINS } from "./coins.js";
import { writeMp4 } from "./mp4.js";

export const CHARTS = {
  start: "Starting point",
  auction: "Auction house activity",
  value: "Total value",
  costs: "Cost breakdown",
  revenue: "Revenue breakdown",
  item: "Item analysis",
};

const C = {
  surface: "#11151c", grid: "#232a35", axis: "#323b49",
  text: "#e7eaf0", text2: "#aab3c2", text3: "#7d8798",
  gain: "#26a69a", loss: "#ef5350", neutral: "#56647a", neutralStrong: "#8593a8",
  sold: "#3987e5", spent: "#d95926", spentLight: "#f2a27c", value: "#d9a441",
  farmed: "#26a69a", crafted: "#9b7ae0", bought: "#d95926",
};
const FONT = "'Segoe UI Variable Text','Segoe UI',system-ui,-apple-system,sans-serif";
const SOURCE_TAGS = { forever: "FOREVER", tbc: "TBC ANNIVERSARY" };
const COPPER_PER_GOLD = 10000;

const number = new Intl.NumberFormat("en-US");
const clamp = (v, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
const trim = (v) => Number(v.toFixed(1));

// ---------- Money ----------

// Splits copper into the pieces worth showing: {text, coin} in reading order.
export function moneyParts(copper, { signed = false } = {}) {
  const sign = copper < 0 ? "−" : signed && copper > 0 ? "+" : "";
  const abs = Math.abs(Math.round(copper));
  const g = Math.floor(abs / COPPER_PER_GOLD), s = Math.floor((abs % COPPER_PER_GOLD) / 100), c = abs % 100;
  if (g >= 1000) return [{ text: `${sign}${number.format(g)}`, coin: "gold" }];
  if (g >= 1) return [{ text: `${sign}${g}`, coin: "gold" }, ...(s ? [{ text: String(s), coin: "silver" }] : [])];
  if (s >= 1) return [{ text: `${sign}${s}`, coin: "silver" }, ...(c ? [{ text: String(c), coin: "copper" }] : [])];
  if (c >= 1) return [{ text: `${sign}${c}`, coin: "copper" }];
  return [{ text: "0", coin: "gold" }];
}

// For screen readers, where a coin picture can't be used.
export function moneyWords(copper, options) {
  return moneyParts(copper, options).map((p) => `${p.text} ${p.coin}`).join(" ");
}

// The same money for ordinary HTML: tooltips and tables.
export function moneyNode(copper, options) {
  const wrap = document.createElement("span");
  wrap.className = "money";
  moneyParts(copper, options).forEach((part) => {
    wrap.append(part.text);
    const coin = document.createElement("img");
    coin.className = "coin";
    coin.src = COINS[part.coin];
    coin.alt = part.coin;
    wrap.append(coin);
  });
  return wrap;
}

const measurer = document.createElement("canvas").getContext("2d");
function measure(value, size, weight = 400) {
  measurer.font = `${weight} ${size}px ${FONT}`;
  return measurer.measureText(value).width;
}

export function formatTime(seconds, span = 0) {
  const d = new Date(seconds * 1000);
  const day = d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  const clock = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  if (span > 0) {
    if (span < 36 * 3600) return clock;
    return span < 8 * 86400 ? `${day} ${clock}` : day;
  }
  return `${day} ${clock}`;
}

// ---------- Vertical axis ----------

function niceNumber(value) {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) {
    if (value <= step * power) return Math.max(1, Math.ceil(step * power));
  }
  return Math.ceil(10 * power);
}

// Where the axis starts, from the episode's choice. A start above all the data can't
// show anything, so it is ignored and reported rather than drawing an empty chart.
export function resolveAxisStart(setting, lo, hi) {
  const mode = setting?.mode ?? "zero";
  if (mode === "custom") {
    const start = Math.round((setting.gold || 0) * COPPER_PER_GOLD);
    return start >= hi && hi > 0 ? { start: 0, ignored: true } : { start, ignored: false };
  }
  if (mode === "fit") {
    const span = hi - lo || hi * 0.1 || COPPER_PER_GOLD;
    const step = niceNumber(span / 2);
    return { start: Math.max(0, Math.floor((lo - span * 0.8) / step) * step), ignored: false };
  }
  return { start: 0, ignored: false };
}

// Four gridlines on round steps from the start, with a little headroom above the data.
function axisScale(start, hi) {
  const step = niceNumber((Math.max(hi, start + 1) - start) * 1.08 / 4);
  return { start, step, max: start + step * 4, ticks: [0, 1, 2, 3, 4].map((i) => start + step * i) };
}

function axisLabel(value, top) {
  if (value === 0) return { text: "0", coin: null };
  if (top >= COPPER_PER_GOLD) {
    const g = value / COPPER_PER_GOLD;
    const text = g >= 1e6 ? `${trim(g / 1e6)}M` : g >= 10000 ? `${trim(g / 1000)}K` : number.format(trim(g));
    return { text, coin: "gold" };
  }
  if (top >= 100) return { text: String(trim(value / 100)), coin: "silver" };
  return { text: String(value), coin: "copper" };
}

// ---------- SVG pieces ----------

const escapeXml = (value) => String(value).replace(/[&<>"']/g, (ch) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" }[ch]));

function text(x, y, value, { size = 13, weight = 400, fill = C.text, anchor = "start", tabular = false } = {}) {
  const style = tabular ? ' style="font-variant-numeric:tabular-nums"' : "";
  return `<text x="${x}" y="${y}" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}"${style}>${escapeXml(value)}</text>`;
}

function line(x1, y1, x2, y2, stroke = C.grid, width = 1) {
  return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${width}"/>`;
}

const COIN_SCALE = 0.84;
// The coin art is only 16 pixels, so beside a big number it stays small to stay sharp.
const HERO_COIN_SCALE = 0.5;
const coinSize = (size, scale = COIN_SCALE) => size * scale;

// A coin sits centered on small text, or on the baseline beside a big number.
function coinImage(x, baseline, coin, size, scale = COIN_SCALE, onBaseline = false) {
  const px = coinSize(size, scale);
  const y = onBaseline ? baseline - px : baseline - size * 0.33 - px / 2;
  return `<image x="${x}" y="${y}" width="${px}" height="${px}" href="${COINS[coin]}"/>`;
}

// A run of text and money on one baseline. Segments are strings or {copper, signed}.
function runPieces(segments) {
  return segments.flatMap((segment) => (typeof segment === "string"
    ? [{ text: segment }]
    : moneyParts(segment.copper, { signed: segment.signed })));
}

function runWidth(segments, size, weight, coinScale) {
  const gap = size * 0.16, between = size * 0.3;
  return runPieces(segments).reduce((sum, piece) => sum + measure(piece.text, size, weight)
    + (piece.coin ? gap + coinSize(size, coinScale) + between : 0), 0);
}

// Coins are placed from the measured width of the text before them, so this text must
// use the same proportional digits as the measurement or a coin can land on a narrow 1.
function run(x, y, segments, { size = 13, weight = 400, fill = C.text, anchor = "start", coinScale = COIN_SCALE, coinOnBaseline = false } = {}) {
  const gap = size * 0.16, between = size * 0.3;
  const pieces = runPieces(segments);
  const trailing = pieces.at(-1)?.coin ? between : 0;
  const width = runWidth(segments, size, weight, coinScale) - trailing;
  let cursor = anchor === "end" ? x - width : anchor === "middle" ? x - width / 2 : x;
  let out = "";
  pieces.forEach((piece) => {
    out += text(cursor, y, piece.text, { size, weight, fill });
    cursor += measure(piece.text, size, weight);
    if (piece.coin) {
      out += coinImage(cursor + gap, y, piece.coin, size, coinScale, coinOnBaseline);
      cursor += gap + coinSize(size, coinScale) + between;
    }
  });
  return out;
}

const reveal = (at, content) => `<g data-reveal="${at}">${content}</g>`;

function fit(value, width, size) {
  if (measure(value, size) <= width) return value;
  let cut = value.length;
  while (cut > 1 && measure(`${value.slice(0, cut).trimEnd()}…`, size) > width) cut--;
  return `${value.slice(0, cut).trimEnd()}…`;
}

function columnPath(x, top, width, bottom, radius) {
  const r = Math.min(radius, width / 2, Math.max(0, bottom - top));
  return `M${x} ${bottom}V${top + r}Q${x} ${top} ${x + r} ${top}H${x + width - r}Q${x + width} ${top} ${x + width} ${top + r}V${bottom}Z`;
}

// A horizontal bar, rounded only at its growing end.
function rowPath(x, y, width, height, radius) {
  const r = Math.min(radius, width, height / 2);
  return `M${x} ${y}H${x + width - r}Q${x + width} ${y} ${x + width} ${y + r}V${y + height - r}Q${x + width} ${y + height} ${x + width - r} ${y + height}H${x}Z`;
}

function layoutFor(options) {
  const { width: W, height: H, tall } = options;
  const s = options.scale;
  // A vertical image keeps its content clear of the Shorts interface.
  const pad = tall
    ? { left: 72, right: 150, top: 170, bottom: 400 }
    : { left: 24 * s, right: 24 * s, top: 20 * s, bottom: 18 * s };
  return { W, H, s, tall, pad, innerW: W - pad.left - pad.right, innerH: H - pad.top - pad.bottom };
}

// `icon` puts an item's picture before the title: a data URI, or null for an empty frame.
function header(L, ctx, title, subtitle, icon) {
  const { pad, s, W } = L;
  const titleSize = 20 * s, subSize = 13 * s, tagSize = 11 * s;
  const tag = SOURCE_TAGS[ctx.source];
  let out = "", left = pad.left;
  if (icon !== undefined) {
    const box = titleSize + subSize + 6 * s;
    if (icon) out += `<image x="${left}" y="${pad.top}" width="${box}" height="${box}" href="${escapeXml(icon)}"/>`;
    out += `<rect x="${left}" y="${pad.top}" width="${box}" height="${box}" rx="${3 * s}" fill="none" stroke="${C.axis}"/>`;
    left += box + 12 * s;
  }
  const room = (L.tall ? W - pad.right : W - pad.right - (tag ? measure(tag, tagSize, 600) + 32 * s : 0)) - left;
  // Measuring is done at regular weight, so the bold title keeps a little spare room.
  out += text(left, pad.top + titleSize * 0.8, fit(title, room * 0.93, titleSize), { size: titleSize, weight: 600 });
  out += text(left, pad.top + titleSize + subSize + 6 * s, fit(subtitle, room, subSize), { size: subSize, fill: C.text2 });
  const belowTitle = pad.top + titleSize + subSize + 22 * s;
  if (!tag) return { svg: out, bottom: belowTitle };
  const tagWidth = measure(tag, tagSize, 600) + 16 * s;
  const tagX = L.tall ? pad.left : W - pad.right - tagWidth;
  const tagY = L.tall ? belowTitle : pad.top;
  out += `<rect x="${tagX}" y="${tagY}" width="${tagWidth}" height="${tagSize + 10 * s}" rx="${3 * s}" fill="none" stroke="${C.axis}"/>`;
  out += text(tagX + tagWidth / 2, tagY + tagSize + 2.5 * s, tag, { size: tagSize, weight: 600, fill: C.text2, anchor: "middle" });
  return { svg: out, bottom: L.tall ? tagY + tagSize + 10 * s + 28 * s : belowTitle };
}

function hero(L, y, money, tone, at) {
  const size = 34 * L.s;
  const fill = tone === "gain" ? C.gain : tone === "loss" ? C.loss : C.text;
  return { svg: reveal(at, run(L.pad.left, y + size * 0.82, [money], { size, weight: 600, fill, coinScale: HERO_COIN_SCALE, coinOnBaseline: true })), bottom: y + size + 12 * L.s };
}

// Splits what is left under the header into the plot and the list beside or below it.
function regions(L, top, { sideShare = 0.36, tallPlotShare = 0.58 } = {}) {
  const bottom = L.H - L.pad.bottom;
  if (L.tall) {
    const available = bottom - top;
    const plotH = available * tallPlotShare;
    return {
      plot: { x: L.pad.left, y: top, w: L.innerW, h: plotH },
      side: { x: L.pad.left, y: top + plotH + 36 * L.s, w: L.innerW, h: available - plotH - 36 * L.s },
    };
  }
  const sideW = L.innerW * sideShare, gap = 34 * L.s;
  return {
    plot: { x: L.pad.left, y: top, w: L.innerW - sideW - gap, h: bottom - top },
    side: { x: L.W - L.pad.right - sideW, y: top, w: sideW, h: bottom - top },
  };
}

// A list of label and money rows. Rows appear one after another between two moments.
function sideList(area, sections, s, revealFrom, revealTo) {
  const rowCount = sections.reduce((n, sec) => n + Math.max(sec.rows.length, sec.empty ? 1 : 0) + (sec.heading ? 1 : 0), 0);
  const gaps = (sections.length - 1) * 12 * s;
  const rowH = Math.min(32 * s, Math.max(20 * s, (area.h - gaps) / Math.max(1, rowCount)));
  const size = Math.min(15 * s, rowH * 0.56);
  const totalRows = sections.reduce((n, sec) => n + sec.rows.length, 0);
  let y = area.y, out = "", index = 0;
  sections.forEach((section) => {
    if (section.heading) {
      out += text(area.x, y + rowH * 0.62, section.heading, { size: size * 0.86, weight: 600, fill: C.text3 });
      y += rowH;
      out += line(area.x, y - 1, area.x + area.w, y - 1, C.axis);
    }
    if (!section.rows.length && section.empty) {
      out += text(area.x, y + rowH * 0.66, section.empty, { size, fill: C.text3 });
      y += rowH;
    }
    section.rows.forEach((row) => {
      const fill = row.tone === "gain" ? C.gain : row.tone === "loss" ? C.loss : row.strong ? C.text : C.text2;
      const money = [{ copper: row.copper, signed: row.signed ?? true }];
      const weight = 600;
      const reserve = runWidth(money, size, weight) + 12 * s;
      let labelX = area.x;
      let rowSvg = "";
      if ("icon" in row) {
        const box = rowH * 0.76, boxY = y + (rowH - box) / 2 - 1;
        if (row.icon) rowSvg += `<image x="${area.x}" y="${boxY}" width="${box}" height="${box}" href="${escapeXml(row.icon)}"/>`;
        rowSvg += `<rect x="${area.x}" y="${boxY}" width="${box}" height="${box}" rx="${2 * s}" fill="none" stroke="${C.axis}"/>`;
        labelX += box + 8 * s;
      } else if (row.swatch) {
        const box = size * 0.7;
        rowSvg += `<rect x="${area.x}" y="${y + rowH * 0.66 - size * 0.33 - box / 2}" width="${box}" height="${box}" rx="${2 * s}" fill="${row.swatch}"/>`;
        labelX += box + 8 * s;
      }
      rowSvg += text(labelX, y + rowH * 0.66, fit(row.label, area.x + area.w - labelX - reserve, size), {
        size, fill: row.strong ? C.text : C.text2, weight: row.strong ? 600 : 400 });
      rowSvg += run(area.x + area.w, y + rowH * 0.66, money, { size, weight, fill, anchor: "end" });
      y += rowH;
      if (row !== section.rows[section.rows.length - 1]) rowSvg += line(area.x, y - 0.5, area.x + area.w, y - 0.5);
      const at = totalRows > 1 ? revealFrom + ((revealTo - revealFrom) * index) / (totalRows - 1) : revealFrom;
      out += reveal(at.toFixed(3), rowSvg);
      index++;
    });
    y += 12 * s;
  });
  return out;
}

function yAxis(area, scale, s, axisW) {
  let out = "";
  const size = 12 * s;
  scale.ticks.forEach((tick, i) => {
    const y = area.y + area.h - (i / 4) * area.h;
    out += line(area.x + axisW, y, area.x + area.w, y, i === 0 ? C.axis : C.grid);
    const label = axisLabel(tick, scale.max);
    const right = area.x + axisW - 8 * s;
    if (label.coin) {
      const px = coinSize(size);
      out += coinImage(right - px, y + size * 0.35, label.coin, size);
      out += text(right - px - size * 0.2, y + size * 0.35, label.text, { size, fill: C.text3, anchor: "end", tabular: true });
    } else {
      out += text(right, y + size * 0.35, label.text, { size, fill: C.text3, anchor: "end", tabular: true });
    }
  });
  return out;
}

function timeAxis(area, start, end, s, axisW) {
  const size = 12 * s, x0 = area.x + axisW, width = area.w - axisW;
  const span = Math.max(1, end - start), count = width > 500 * s ? 5 : 3;
  let out = "";
  for (let i = 0; i <= count; i++) {
    const moment = start + (span * i) / count;
    const x = x0 + (width * i) / count;
    const anchor = i === 0 ? "start" : i === count ? "end" : "middle";
    out += text(x, area.y + area.h + size + 6 * s, formatTime(moment, span), { size, fill: C.text3, anchor, tabular: true });
  }
  return out;
}

function shell(L, content) {
  return `<svg class="figure" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${L.W} ${L.H}" width="${L.W}" height="${L.H}" font-family="${FONT}" role="img"><rect width="${L.W}" height="${L.H}" fill="${C.surface}"/>${content}</svg>`;
}

function emptyMessage(area, message, s) {
  return text(area.x + area.w / 2, area.y + area.h / 2, message, { size: 14 * s, fill: C.text3, anchor: "middle" });
}

function subtitleFor(ctx, start, end) {
  return `${ctx.windowLabel}  ·  ${formatTime(start)} to ${formatTime(end)}`;
}

// ---------- Starting point ----------

function startFigure(data, ctx, options) {
  const L = layoutFor(options), s = L.s;
  const d = data.start;
  const head = header(L, ctx, CHARTS.start, subtitleFor(ctx, data.window.start, data.window.end));
  const tone = d.change > 0 ? "gain" : d.change < 0 ? "loss" : null;
  const big = hero(L, head.bottom, { copper: d.change, signed: true }, tone, 0.7);
  const { plot, side } = regions(L, big.bottom + 6 * s, { tallPlotShare: 0.46 });
  const labelBand = 26 * s, axisW = 62 * s;
  const area = { x: plot.x, y: plot.y + 20 * s, w: plot.w, h: plot.h - 20 * s - labelBand };
  const axis = resolveAxisStart(options.axis, Math.min(d.start, d.end), Math.max(d.start, d.end));
  const scale = axisScale(axis.start, Math.max(d.start, d.end));
  const yOf = (v) => area.y + area.h - ((Math.max(v, scale.start) - scale.start) / (scale.max - scale.start)) * area.h;
  let out = yAxis(area, scale, s, axisW);

  // Each column grows in turn: the start, then the change on top of it, then the end.
  const up = d.change >= 0;
  const columns = [
    { key: "start", label: "Start", fixed: yOf(scale.start), target: yOf(d.start), fill: C.neutral, copper: d.start, signed: false, phase: [0, 0.35] },
    { key: "change", label: up ? "Increase" : "Decrease", fixed: yOf(d.start), target: yOf(d.end), fill: up ? C.gain : C.loss, copper: d.change, signed: true, phase: [0.35, 0.7] },
    { key: "end", label: "End", fixed: yOf(scale.start), target: yOf(d.end), fill: C.neutralStrong, copper: d.end, signed: false, phase: [0.7, 1] },
  ];
  const slot = (area.w - axisW) / 3, barW = Math.min(slot * 0.5, 84 * s);
  const hits = [], bars = [];
  columns.forEach((col, i) => {
    const x = area.x + axisW + slot * i + (slot - barW) / 2;
    const growsDown = i === 1 && !up;
    let top = Math.min(col.fixed, col.target), bottom = Math.max(col.fixed, col.target);
    // A tiny change still shows, and still grows in its own direction.
    if (bottom - top < 2) {
      if (growsDown) bottom = top + 2; else top = bottom - 2;
    }
    const radius = 4 * s;
    out += `<path data-bar="${i}" d="${columnPath(x, top, barW, bottom, radius)}" fill="${col.fill}"/>`;
    bars.push({ x, width: barW, fixed: growsDown ? top : bottom, moving: growsDown ? bottom : top, radius, from: col.phase[0], to: col.phase[1] });
    if (i < 2) {
      const level = yOf(i === 0 ? d.start : d.end);
      out += reveal(col.phase[1], line(x + barW, level, x + slot, level, C.text3));
    }
    out += reveal(col.phase[1] - 0.02, run(x + barW / 2, top - 7 * s, [{ copper: col.copper, signed: col.signed }], { size: 14 * s, weight: 600, anchor: "middle" }));
    out += text(x + barW / 2, area.y + area.h + 18 * s, col.label, { size: 13 * s, fill: C.text2, anchor: "middle" });
    hits.push({ x: x - (slot - barW) / 4, y: area.y, w: barW + (slot - barW) / 2, h: area.h, title: col.label, copper: col.copper, signed: col.signed });
  });

  const row = (r, rowTone) => ({ label: r.label, copper: r.value, tone: rowTone });
  const sections = [
    { heading: "Top income", rows: d.income.map((r) => row(r, "gain")), empty: "None in this window" },
    { heading: "Top losses", rows: d.losses.map((r) => row(r, "loss")), empty: "None in this window" },
    { rows: [
      ...(d.other ? [{ label: "Everything else", copper: d.other }] : []),
      { label: "Net change", copper: d.change, strong: true, tone },
    ] },
  ];
  out += sideList(side, sections, s, 0.4, 0.95);
  return { svg: shell(L, head.svg + big.svg + out), hover: { kind: "bars", hits, s }, anim: { kind: "bars", bars }, axis };
}

// ---------- Line charts ----------

// The lines sit in a group clipped to the plot. Widening the clip draws them left to
// right, and a dot rides the tip of each line.
function lineChart(id, area, series, points, start, end, scale, s, axisW) {
  const x0 = area.x + axisW, width = area.w - axisW, span = Math.max(1, end - start);
  const xOf = (t) => x0 + ((t - start) / span) * width;
  const yOf = (v) => area.y + area.h - ((Math.max(v, scale.start) - scale.start) / (scale.max - scale.start)) * area.h;
  const clipId = `reveal-${id}`;
  let lines = "", dots = "";
  const heads = [];
  series.forEach((sr, index) => {
    const xy = points.map((p) => [xOf(p.time), yOf(p[sr.key])]);
    const path = xy.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join("L");
    if (sr.area) {
      const fillId = `fill-${id}-${sr.key}`;
      lines += `<defs><linearGradient id="${fillId}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${sr.color}" stop-opacity=".30"/><stop offset="1" stop-color="${sr.color}" stop-opacity=".02"/></linearGradient></defs>`;
      lines += `<path d="M${xy[0][0].toFixed(1)} ${yOf(scale.start)}L${path}L${xy[xy.length - 1][0].toFixed(1)} ${yOf(scale.start)}Z" fill="url(#${fillId})"/>`;
    }
    lines += `<path d="M${path}" fill="none" stroke="${sr.color}" stroke-width="${2 * s}" stroke-linejoin="round" stroke-linecap="round"/>`;
    const [lastX, lastY] = xy[xy.length - 1];
    dots += `<circle data-head="${index}" cx="${lastX}" cy="${lastY}" r="${4 * s}" fill="${sr.color}" stroke="${C.surface}" stroke-width="${2 * s}"/>`;
    heads.push(xy);
  });
  const pad = 3 * s;
  const svg = `<defs><clipPath id="${clipId}"><rect data-clip="1" x="${x0 - pad}" y="${area.y - pad}" width="${width + pad * 2}" height="${area.h + pad * 2}"/></clipPath></defs><g clip-path="url(#${clipId})">${lines}</g>${dots}`;
  return { svg, xOf, yOf, anim: { kind: "lines", x0, width, pad, heads } };
}

function windowMark(area, ctx, data, start, end, s, axisW) {
  // Shows where this episode's own window begins when the chart runs from earlier.
  if (data.range !== "to_date" || data.window.start <= start || data.window.kind === "all") return "";
  const x = area.x + axisW + ((data.window.start - start) / Math.max(1, end - start)) * (area.w - axisW);
  const size = 12 * s;
  const roomOnRight = x + measure(ctx.windowLabel, size) + 6 * s < area.x + area.w;
  return line(x, area.y, x, area.y + area.h, C.text3) + text(x + (roomOnRight ? 6 * s : -6 * s), area.y + size, ctx.windowLabel, {
    size, fill: C.text2, anchor: roomOnRight ? "start" : "end" });
}

function legend(items, x, y, s) {
  let out = "", cursor = x;
  const size = 13 * s;
  items.forEach((item) => {
    out += `<line x1="${cursor}" y1="${y - size * 0.32}" x2="${cursor + 16 * s}" y2="${y - size * 0.32}" stroke="${item.color}" stroke-width="${2 * s}" stroke-linecap="round"/>`;
    const segments = [`${item.label}  `, { copper: item.copper }];
    out += run(cursor + 22 * s, y, segments, { size, fill: C.text2 });
    cursor += 22 * s + runWidth(segments, size, 400) + 18 * s;
  });
  return out;
}

function auctionFigure(data, ctx, options) {
  const L = layoutFor(options), s = L.s;
  const d = data.auction;
  const head = header(L, ctx, CHARTS.auction, subtitleFor(ctx, d.start, d.end));
  const tone = d.net > 0 ? "gain" : d.net < 0 ? "loss" : null;
  const big = hero(L, head.bottom, { copper: d.net, signed: true }, tone, 0.85);
  const { plot, side } = regions(L, big.bottom + 6 * s);
  const legendBand = 26 * s, axisBand = 28 * s, axisW = 68 * s;
  const area = { x: plot.x, y: plot.y + legendBand, w: plot.w, h: plot.h - legendBand - axisBand };
  const series = [{ key: "sold", label: "Sold", color: C.sold }, { key: "spent", label: "Spent", color: C.spent }];
  const totals = { sold: d.sold, spent: d.spent };
  let out = legend(series.map((sr) => ({ label: sr.label, copper: totals[sr.key], color: sr.color })), plot.x + axisW, plot.y + 13 * s, s);
  let hover = null, anim = null, axis = { start: 0, ignored: false };
  if (!d.has_activity) {
    out += yAxis(area, axisScale(0, COPPER_PER_GOLD), s, axisW) + emptyMessage({ ...area, x: area.x + axisW, w: area.w - axisW }, "No auction house activity in this range", s);
  } else {
    const values = d.points.flatMap((p) => [p.sold, p.spent]);
    const hi = Math.max(...values);
    axis = resolveAxisStart(options.axis, Math.min(...values), hi);
    const scale = axisScale(axis.start, hi);
    out += yAxis(area, scale, s, axisW) + timeAxis(area, d.start, d.end, s, axisW);
    out += windowMark(area, ctx, data, d.start, d.end, s, axisW);
    const chart = lineChart("auction", area, series, d.points, d.start, d.end, scale, s, axisW);
    out += chart.svg;
    anim = chart.anim;
    hover = { kind: "line", s, area: { ...area, x: area.x + axisW, w: area.w - axisW }, points: d.points.map((p) => ({
      x: chart.xOf(p.time), title: formatTime(p.time),
      rows: series.map((sr) => ({ color: sr.color, label: sr.label, copper: p[sr.key], y: chart.yOf(p[sr.key]) })),
    })) };
  }
  const rows = d.top.map((r) => ({
    label: r.quantity ? `${r.name} (${number.format(r.quantity)})` : r.name,
    copper: r.net, tone: r.net > 0 ? "gain" : r.net < 0 ? "loss" : null, icon: r.icon ?? null,
  }));
  out += sideList(side, [{ heading: "Top 5 items by net gain", rows, empty: "No items in this range" }], s, 0.45, 0.95);
  return { svg: shell(L, head.svg + big.svg + out), hover, anim, axis };
}

function valueFigure(data, ctx, options) {
  const L = layoutFor(options), s = L.s;
  const d = data.value;
  const head = header(L, ctx, CHARTS.value, subtitleFor(ctx, d.start, d.end));
  const axisBand = 28 * s, axisW = 68 * s;
  if (!d.points.length) {
    const area = { x: L.pad.left, y: head.bottom, w: L.innerW, h: L.H - L.pad.bottom - head.bottom };
    return { svg: shell(L, head.svg + emptyMessage(area, "No valuations recorded in this range", s)), hover: null, anim: null, axis: { start: 0, ignored: false } };
  }
  const big = hero(L, head.bottom, { copper: d.last }, null, 0.85);
  const top = big.bottom + 8 * s;
  const area = { x: L.pad.left, y: top, w: L.innerW, h: L.H - L.pad.bottom - top - axisBand };
  const series = [{ key: "total", label: "Total value", color: C.value, area: true }];
  const totals = d.points.map((p) => p.total);
  const hi = Math.max(...totals);
  const axis = resolveAxisStart(options.axis, Math.min(...totals), hi);
  const scale = axisScale(axis.start, hi);
  let out = yAxis(area, scale, s, axisW) + timeAxis(area, d.start, d.end, s, axisW);
  out += windowMark(area, ctx, data, d.start, d.end, s, axisW);
  const chart = lineChart("value", area, series, d.points, d.start, d.end, scale, s, axisW);
  out += chart.svg;
  const hover = { kind: "line", s, area: { ...area, x: area.x + axisW, w: area.w - axisW }, points: d.points.map((p) => ({
    x: chart.xOf(p.time), title: formatTime(p.time),
    rows: [
      { color: C.value, label: "Total value", copper: p.total, y: chart.yOf(p.total) },
      { label: "Gold", copper: p.gold },
      { label: "Other assets", copper: p.assets },
      { label: "Equipped gear", copper: p.equipped },
    ],
  })) };
  return { svg: shell(L, head.svg + big.svg + out), hover, anim: chart.anim, axis };
}

// ---------- Cost and revenue breakdowns ----------

// What differs between the two breakdowns; the drawing, picker and table are shared.
// `details` are the parts listed under a row in the table, `side` the list beside the bars.
const plain = (list) => list.map((row) => ({ signed: false, ...row }));
const BREAKDOWNS = {
  costs: {
    column: "Cost", totalLabel: "Total costs", color: C.spent, partColor: C.spentLight,
    empty: "No costs recorded in this window", noneChosen: "None of these characters spent anything in this window",
    nouns: { class_training: ["lesson", "lessons"], profession_training: ["lesson", "lessons"], repair: ["repair", "repairs"],
      flight: ["flight", "flights"], ah_fees: ["listing lost", "listings lost"], ah_purchases: ["purchase", "purchases"] },
    details: {
      ah_fees: [{ label: "Unsold listing fees", key: "listing_fees" }, { label: "Auction house cut", key: "ah_cut" }],
      ah_purchases: [{ label: "Bought", key: "bought", when: (p) => p.bid_refunds },
        { label: "Bids sent back", key: "bid_refunds", sign: -1, when: (p) => p.bid_refunds }],
    },
    side: (p, groups) => [
      { heading: "Auction house costs", rows: plain([
        { label: "Unsold listing fees", copper: p.listing_fees, ...(groups ? {} : { swatch: C.spent }) },
        { label: "Auction house cut", copper: p.ah_cut, ...(groups ? {} : { swatch: C.spentLight }) },
      ]) },
      ...(groups ? [] : [{ heading: "Auction house purchases", rows: plain([
        { label: "Bought", copper: p.bought },
        ...(p.bid_refunds ? [{ label: "Bids sent back", copper: -p.bid_refunds }] : []),
      ]) }]),
    ],
  },
  revenue: {
    column: "Revenue", totalLabel: "Total revenue", color: C.sold,
    empty: "No revenue recorded in this window", noneChosen: "None of these characters earned anything in this window",
    nouns: { ah_sales: ["sale", "sales"], loot: ["pickup", "pickups"], quest: ["quest", "quests"], vendor_sale: ["sale", "sales"],
      players: ["payment", "payments"] },
    details: {
      ah_sales: [{ label: "Auction house cut", key: "ah_cut", sign: -1 }, { label: "Deposits back", key: "deposits_back", sign: 1 },
        { label: "Collected", key: "collected" }],
    },
    // Sales count at the buyer's price; this shows how that became the gold collected.
    side: (p) => [{ heading: "Auction house sales", rows: plain([
      { label: "Sold for", copper: p.sold_for },
      { label: "Auction house cut", copper: -p.ah_cut, signed: true },
      { label: "Deposits back", copper: p.deposits_back, signed: true },
      { label: "Collected", copper: p.collected },
    ]) }],
  },
};
const countText = (kind, key, count) => `${number.format(count)} ${BREAKDOWNS[kind].nouns[key][count === 1 ? 0 : 1]}`;

// One colour per character, checked for colour-blind separation on this surface.
// A ninth character is never a made-up colour: past eight, the rest share grey.
export const CHARACTER_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];

// The colour groups a breakdown's settings ask for, or null for all characters
// together. None chosen means all. A character's colour follows its fixed place among
// everyone with money in the window, so ticking another never repaints it. With more
// than eight there aren't enough colours for that: then the chosen take them in
// order, and past eight the seven with the most keep theirs.
export function breakdownGroups(breakdown, settings) {
  if (!settings?.split) return null;
  const all = breakdown.characters ?? [];
  const chosen = settings.characters?.length ? all.filter((c) => settings.characters.includes(c.id)) : all;
  const coloured = chosen.length <= CHARACTER_COLORS.length ? chosen
    : chosen.filter((c) => [...chosen].sort((a, b) => b.total - a.total).slice(0, CHARACTER_COLORS.length - 1).includes(c));
  const colourOf = (c, i) => CHARACTER_COLORS[all.length <= CHARACTER_COLORS.length ? all.indexOf(c) : i];
  const groups = coloured.map((c, i) => ({ id: c.id, name: c.name, ids: [c.id], color: colourOf(c, i) }));
  const rest = chosen.filter((c) => !coloured.includes(c));
  if (rest.length) groups.push({ id: "other", name: `${rest.length} other characters`, ids: rest.map((c) => c.id), color: C.neutralStrong });
  return groups;
}

// The rows, total and parts the chart shows, for everyone or per group.
function breakdownView(kind, d, settings) {
  const groups = breakdownGroups(d, settings), config = BREAKDOWNS[kind];
  if (!groups) {
    const rows = d.rows.map((row) => ({ ...row, segments: (row.parts ?? [{ value: row.value }])
      .map((part, k) => ({ value: part.value, label: part.label, color: k === 0 ? config.color : config.partColor })) }));
    return { groups, rows, total: d.total, parts: d.parts };
  }
  const sumOf = (ids, pick) => ids.reduce((sum, id) => sum + (pick(id) || 0), 0);
  const rows = d.rows.map((row) => {
    const segments = groups.map((g) => ({ value: sumOf(g.ids, (id) => row.by_character?.[id]), label: g.name, color: g.color }));
    return { ...row, segments, value: segments.reduce((sum, seg) => sum + seg.value, 0) };
  }).sort((a, b) => b.value - a.value); // Stable, so equal rows keep the usual order.
  const ids = groups.flatMap((g) => g.ids);
  const parts = Object.fromEntries(Object.keys(d.parts).map((key) => [key, sumOf(ids, (id) => d.parts_by_character?.[id]?.[key])]));
  groups.forEach((g) => { g.total = rows.reduce((sum, row) => sum + row.segments[groups.indexOf(g)].value, 0); });
  return { groups, rows, total: rows.reduce((sum, row) => sum + row.value, 0), parts };
}

// One labelled bar per cost or source of revenue, largest first, growing in turn. All
// together, auction house costs stack their two parts; split by character, every bar
// stacks the chosen characters. Either way the colours are keyed beside the bars.
function breakdownFigure(kind, data, ctx, options) {
  const L = layoutFor(options), s = L.s;
  const d = data[kind], config = BREAKDOWNS[kind];
  const view = breakdownView(kind, d, options.axis), { groups, rows, parts: p } = view;
  const head = header(L, ctx, CHARTS[kind], subtitleFor(ctx, d.start, d.end));
  const big = hero(L, head.bottom, { copper: view.total }, null, 0.85);
  const { plot, side } = regions(L, big.bottom + 6 * s, { tallPlotShare: groups ? 0.5 : 0.6 });
  const axis = { start: 0, ignored: false };
  let out = "", anim = null, hover = null;
  if (!d.has_activity || !view.total) {
    out += emptyMessage(plot, d.has_activity ? config.noneChosen : config.empty, s);
  } else {
    const rowH = plot.h / rows.length;
    const size = Math.min(15 * s, rowH * 0.3), barH = Math.min(16 * s, rowH * 0.3), radius = 3 * s, gap = 2 * s;
    const max = Math.max(1, ...rows.map((row) => row.value));
    const bars = [], hits = [];
    rows.forEach((row, i) => {
      const y = plot.y + rowH * i, baseline = y + size, barY = baseline + 8 * s;
      const from = 0.08 + (0.6 * i) / Math.max(1, rows.length - 1), to = Math.min(1, from + 0.3);
      out += text(plot.x, baseline, row.label, { size, fill: C.text2 });
      out += reveal((to - 0.02).toFixed(3), run(plot.x + plot.w, baseline, [{ copper: row.value }], { size, weight: 600, anchor: "end" }));
      out += `<rect x="${plot.x}" y="${barY}" width="${plot.w}" height="${barH}" rx="${radius}" fill="${C.grid}"/>`;
      const segments = row.segments.filter((segment) => segment.value > 0);
      // A tiny cost still shows as a sliver.
      const full = row.value > 0 ? Math.max(2 * s, (plot.w * row.value) / max) : 0;
      let x = plot.x, at = from;
      segments.forEach((segment, k) => {
        const last = k === segments.length - 1;
        const width = (full * segment.value) / row.value, until = at + ((to - from) * segment.value) / row.value;
        // A thin gap of background between stacked pieces keeps neighbours apart.
        const drawn = last ? width : Math.max(Math.min(width, 1 * s), width - gap);
        const r = last ? radius : 0;
        out += `<path data-hbar="${bars.length}" d="${rowPath(x, barY, drawn, barH, r)}" fill="${segment.color}"/>`;
        bars.push({ x, y: barY, width: drawn, height: barH, radius: r, from: at, to: until });
        x += width;
        at = until;
      });
      const tip = groups || row.parts
        ? [{ copper: row.value, label: "in all" }, ...row.segments.filter((seg) => seg.value).map((seg) => ({ copper: seg.value, label: seg.label, color: seg.color }))]
        : [{ copper: row.value, label: countText(kind, row.key, row.count) }];
      hits.push({ x: plot.x, y, w: plot.w, h: rowH, title: row.label, copper: row.value, rows: tip });
    });
    anim = { kind: "hbars", bars };
    hover = { kind: "bars", hits, s };
  }
  const total = { rows: plain([{ label: config.totalLabel, copper: view.total, strong: true }]) };
  // A Short has little room below the bars, so a long character list replaces the detail.
  const sections = groups
    ? [{ heading: "Characters", rows: plain(groups.map((g) => ({ label: g.name, copper: g.total, swatch: g.color }))) },
      ...(L.tall && groups.length > 4 ? [] : config.side(p, groups)), total]
    : [...config.side(p, null), total];
  out += sideList(side, sections, s, 0.45, 0.95);
  return { svg: shell(L, head.svg + big.svg + out), hover, anim, axis };
}

// ---------- Item analysis ----------

const plural = (count, one, many) => `${number.format(count)} ${count === 1 ? one : many}`;

// A small label, a big count or sum of money, and a note under it.
function statTile(x, y, w, s, tile, at) {
  const labelSize = 13 * s, valueSize = 26 * s, noteSize = 12 * s;
  let out = text(x, y + labelSize, tile.label, { size: labelSize, weight: 600, fill: C.text3 });
  const baseline = y + labelSize + 10 * s + valueSize * 0.8;
  out += tile.copper == null
    ? text(x, baseline, tile.value, { size: valueSize, weight: 600 })
    : run(x, baseline, [{ copper: tile.copper }], { size: valueSize, weight: 600, coinScale: 0.6, coinOnBaseline: true });
  out += text(x, baseline + noteSize + 10 * s, fit(tile.note, w - 8 * s, noteSize), { size: noteSize, fill: C.text2 });
  return reveal(at.toFixed(3), out);
}

function spentNote(d) {
  if (d.materials_unknown) return "Some materials have no cost on record";
  if (d.spent.materials && d.spent.bought) return "Buying it, and materials to craft it";
  if (d.spent.materials) return "Materials to craft it";
  return d.spent.purchases ? "Buying it outright" : "Nothing bought";
}

// What one item sold for, where every one of them came from, and what they cost.
// Four figures appear in turn, then a bar for each way it was gained.
function itemFigure(data, ctx, options) {
  const L = layoutFor(options), s = L.s;
  const d = data.item, { sold, gained, spent } = d;
  const head = header(L, ctx, d.name, `${CHARTS.item}  ·  ${subtitleFor(ctx, d.start, d.end)}`, d.icon ?? null);
  const each = sold.price_from === "vendor" ? "Each, from a vendor" : "Each";
  const tiles = [
    { label: "Sold", value: number.format(sold.quantity), note: sold.quantity
      ? [sold.auction ? `${number.format(sold.auction)} at auction` : "", sold.vendor ? `${number.format(sold.vendor)} to vendors` : ""].filter(Boolean).join(", ")
      : "None in this window" },
    { label: "Highest price", copper: sold.highest, value: "–", note: sold.highest == null ? "No sales" : each },
    { label: "Lowest price", copper: sold.lowest, value: "–", note: sold.lowest == null ? "No sales" : each },
    { label: "Spent", copper: spent.total, note: spentNote(d) },
  ];
  const cols = L.tall ? 2 : 4, gap = 24 * s, tileH = 80 * s, rowGap = 14 * s;
  const tileW = (L.innerW - gap * (cols - 1)) / cols;
  let out = "";
  tiles.forEach((tile, i) => {
    const x = L.pad.left + (i % cols) * (tileW + gap), y = head.bottom + Math.floor(i / cols) * (tileH + rowGap);
    out += statTile(x, y, tileW, s, tile, 0.04 + i * 0.07);
  });
  const { plot, side } = regions(L, head.bottom + (tiles.length / cols) * (tileH + rowGap) + 8 * s, { tallPlotShare: 0.42 });

  const headSize = 13 * s;
  out += text(plot.x, plot.y + headSize, "Where they came from", { size: headSize, weight: 600, fill: C.text3 });
  const area = { x: plot.x, y: plot.y + headSize + 16 * s, w: plot.w, h: plot.h - headSize - 16 * s };
  const sources = [
    { label: "Farmed", count: gained.farmed, color: C.farmed, tip: "looted by your own characters" },
    { label: "Crafted", count: gained.crafted, color: C.crafted, tip: plural(gained.crafts, "craft", "crafts") },
    { label: gained.unknown_purchases ? `Bought, plus ${plural(gained.unknown_purchases, "purchase", "purchases")} of unknown size` : "Bought",
      count: gained.bought, color: C.bought, tip: plural(spent.purchases, "purchase", "purchases") },
  ];
  const bars = [], hits = [];
  if (!sources.some((row) => row.count) && !gained.unknown_purchases) {
    out += emptyMessage(area, "Not farmed, crafted or bought in this window", s);
  } else {
    const rowH = Math.min(area.h / sources.length, 72 * s);
    const size = Math.min(15 * s, rowH * 0.3), barH = Math.min(16 * s, rowH * 0.3), radius = 3 * s;
    const max = Math.max(1, ...sources.map((row) => row.count));
    sources.forEach((row, i) => {
      const y = area.y + rowH * i, baseline = y + size, barY = baseline + 8 * s;
      const from = 0.32 + 0.12 * i, to = from + 0.3;
      const count = number.format(row.count);
      out += text(area.x, baseline, fit(row.label, area.w - measure(count, size, 600) - 16 * s, size), { size, fill: C.text2 });
      out += reveal((to - 0.02).toFixed(3), text(area.x + area.w, baseline, count, { size, weight: 600, anchor: "end" }));
      out += `<rect x="${area.x}" y="${barY}" width="${area.w}" height="${barH}" rx="${radius}" fill="${C.grid}"/>`;
      const width = row.count > 0 ? Math.max(2 * s, (area.w * row.count) / max) : 0;
      out += `<path data-hbar="${bars.length}" d="${width ? rowPath(area.x, barY, width, barH, radius) : ""}" fill="${row.color}"/>`;
      bars.push({ x: area.x, y: barY, width, height: barH, radius, from, to });
      hits.push({ x: area.x, y, w: area.w, h: rowH, title: row.label, text: count, rows: [{ text: count, label: row.tip, color: row.color }] });
    });
  }

  const plain = (row) => ({ ...row, signed: false });
  const reagents = d.recipe?.reagents ?? [];
  const listed = reagents.slice(0, reagents.length > 4 ? 3 : 4);
  const rest = reagents.slice(listed.length);
  const spentRows = [
    ...(spent.purchases ? [plain({ label: `Buying it (${plural(spent.purchases, "purchase", "purchases")})`, copper: spent.bought })] : []),
    ...listed.map((r) => plain({ label: `${r.name} ×${number.format(r.used)}`, copper: r.cost, icon: r.icon ?? null })),
    ...(rest.length ? [plain({ label: `${rest.length} other materials`, copper: rest.reduce((sum, r) => sum + r.cost, 0) })] : []),
    ...(gained.crafts && !d.recipe ? [plain({ label: "Materials: recipe not seen", copper: 0 })] : []),
    plain({ label: "Total spent", copper: spent.total, strong: true }),
  ];
  const tone = d.net > 0 ? "gain" : d.net < 0 ? "loss" : null;
  out += sideList(side, [
    { heading: "Spent", rows: spentRows },
    { rows: [plain({ label: "Sales after the auction house cut", copper: sold.revenue }),
      { label: "Sales minus spending", copper: d.net, signed: true, strong: true, tone }] },
  ], s, 0.5, 0.95);
  return { svg: shell(L, head.svg + out), hover: { kind: "bars", hits, s }, anim: { kind: "hbars", bars }, axis: { start: 0, ignored: false } };
}

const BUILDERS = { start: startFigure, auction: auctionFigure, value: valueFigure, item: itemFigure,
  costs: (...args) => breakdownFigure("costs", ...args), revenue: (...args) => breakdownFigure("revenue", ...args) };
const SCREEN = { start: { width: 1200, height: 500 }, auction: { width: 1200, height: 500 }, value: { width: 1200, height: 460 }, costs: { width: 1200, height: 500 }, revenue: { width: 1200, height: 500 }, item: { width: 1200, height: 500 } };
const EXPORT_SIZES = { short: { width: 1080, height: 1920, tall: true, scale: 2.1 }, long: { width: 1920, height: 1080, tall: false, scale: 1.6 } };

// `tall` shows the vertical layout on screen, exactly as a Short's image has it.
export function renderForScreen(kind, data, ctx, { tall = false, axis } = {}) {
  const size = tall ? EXPORT_SIZES.short : { ...SCREEN[kind], scale: 1, tall: false };
  return BUILDERS[kind](data, ctx, { ...size, axis });
}

export function svgForExport(kind, data, ctx, format, axis) {
  return BUILDERS[kind](data, ctx, { ...EXPORT_SIZES[format], axis }).svg;
}

export function saveBlob(blob, filename) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 60000);
}

async function drawSvg(svg, context) {
  const image = new Image();
  image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  try {
    await image.decode();
  } catch {
    throw new Error("The chart could not be drawn as an image");
  }
  context.drawImage(image, 0, 0, context.canvas.width, context.canvas.height);
}

function canvasFor(format) {
  const canvas = document.createElement("canvas");
  canvas.width = EXPORT_SIZES[format].width;
  canvas.height = EXPORT_SIZES[format].height;
  return canvas;
}

export async function exportPng(kind, data, ctx, format, axis, filename) {
  const canvas = canvasFor(format);
  await drawSvg(svgForExport(kind, data, ctx, format, axis), canvas.getContext("2d"));
  const blob = await new Promise((resolve) => { canvas.toBlob(resolve, "image/png"); });
  if (!blob) throw new Error("The image could not be created");
  saveBlob(blob, filename);
}

// ---------- Video ----------

export const VIDEO_HOLD_SECONDS = 2; // The finished chart stays up, so there's time to read it.
const VIDEO_FPS = 60;
const VIDEO_BITRATE = 16_000_000;
const KEY_FRAME_SECONDS = 2;
const VIDEO_TIMESCALE = 6000;
const H264_CODECS = ["avc1.64002A", "avc1.4D002A", "avc1.42002A"]; // High, then Main, then Baseline.

async function findEncoderConfig(width, height) {
  if (typeof VideoEncoder === "undefined") {
    throw new Error("Video export needs a browser that can encode video, such as Chrome or Edge");
  }
  for (const codec of H264_CODECS) {
    for (const hardwareAcceleration of ["no-preference", "prefer-software"]) {
      const config = { codec, width, height, framerate: VIDEO_FPS, bitrate: VIDEO_BITRATE, hardwareAcceleration,
        latencyMode: "quality", avc: { format: "avc" } };
      const { supported } = await VideoEncoder.isConfigSupported(config).catch(() => ({ supported: false }));
      if (supported) return config;
    }
  }
  throw new Error("This browser has no H.264 video encoder");
}

export class VideoCancelled extends Error {}

// Draws every frame in turn rather than recording the screen, so the result is the
// same however busy the computer is. Returns an MP4 Blob.
export async function renderVideo(kind, data, ctx, format, axis, seconds, { onProgress = () => {}, signal } = {}) {
  const { width, height } = EXPORT_SIZES[format];
  const config = await findEncoderConfig(width, height);
  const built = BUILDERS[kind](data, ctx, { ...EXPORT_SIZES[format], axis });
  const svg = new DOMParser().parseFromString(built.svg, "image/svg+xml").documentElement;
  const showFrame = createFrames(svg, built.anim);
  const serializer = new XMLSerializer();
  const canvas = canvasFor(format);
  const context = canvas.getContext("2d", { alpha: false });

  const samples = [];
  let description, colour, failure;
  const encoder = new VideoEncoder({
    output(chunk, metadata) {
      if (metadata?.decoderConfig) {
        description = description ?? metadata.decoderConfig.description;
        colour = colour ?? metadata.decoderConfig.colorSpace;
      }
      const bytes = new Uint8Array(chunk.byteLength);
      chunk.copyTo(bytes);
      samples.push({ data: bytes, key: chunk.type === "key", timestamp: chunk.timestamp });
    },
    error(err) { failure = err; },
  });
  encoder.configure(config);

  const animationFrames = Math.max(1, Math.round(seconds * VIDEO_FPS));
  const totalFrames = animationFrames + Math.round(VIDEO_HOLD_SECONDS * VIDEO_FPS);
  const frameMicroseconds = 1e6 / VIDEO_FPS;
  try {
    for (let i = 0; i < totalFrames; i++) {
      if (signal?.aborted) throw new VideoCancelled();
      if (failure) throw failure;
      // The hold shows one finished picture, so it only needs drawing once.
      if (i <= animationFrames) {
        showFrame(i / animationFrames);
        await drawSvg(serializer.serializeToString(svg), context);
      }
      const frame = new VideoFrame(canvas, { timestamp: Math.round(i * frameMicroseconds), duration: Math.round(frameMicroseconds) });
      encoder.encode(frame, { keyFrame: i % (KEY_FRAME_SECONDS * VIDEO_FPS) === 0 });
      frame.close();
      while (encoder.encodeQueueSize > 8 && !failure) await new Promise((resolve) => { setTimeout(resolve, 2); });
      onProgress((i + 1) / totalFrames);
    }
    await encoder.flush();
    if (failure) throw failure;
  } finally {
    if (encoder.state !== "closed") encoder.close();
  }
  if (!description) throw new Error("The video encoder gave no format details");
  if (samples.some((sample, i) => i > 0 && sample.timestamp <= samples[i - 1].timestamp)) {
    throw new Error("The video encoder reordered its frames, which this export can't store");
  }
  const bytes = writeMp4({ width, height, timescale: VIDEO_TIMESCALE, frameDuration: VIDEO_TIMESCALE / VIDEO_FPS, samples,
    description: new Uint8Array(description.buffer ?? description, description.byteOffset ?? 0, description.byteLength), colour });
  return new Blob([bytes], { type: "video/mp4" });
}

// ---------- Animation ----------

const ease = (t) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);

function pointAt(xy, x) {
  if (x >= xy[xy.length - 1][0]) return xy[xy.length - 1];
  let i = 1;
  while (i < xy.length - 1 && xy[i][0] < x) i++;
  const [x0, y0] = xy[i - 1], [x1, y1] = xy[i];
  return [x, x1 === x0 ? y1 : y0 + ((y1 - y0) * (x - x0)) / (x1 - x0)];
}

// Draws one moment of a figure: 0 is empty and 1 is exactly the finished chart.
export function createFrames(svg, anim) {
  const reveals = [...svg.querySelectorAll("[data-reveal]")].map((el) => [el, Number(el.dataset.reveal)]);
  const bars = anim?.kind === "bars" ? anim.bars.map((bar, i) => [bar, svg.querySelector(`[data-bar="${i}"]`)]) : [];
  const rows = anim?.kind === "hbars" ? anim.bars.map((bar, i) => [bar, svg.querySelector(`[data-hbar="${i}"]`)]) : [];
  const clip = anim?.kind === "lines" ? svg.querySelector("[data-clip]") : null;
  const heads = anim?.kind === "lines" ? anim.heads.map((xy, i) => [xy, svg.querySelector(`[data-head="${i}"]`)]) : [];
  return (progress) => {
    const p = clamp(progress);
    reveals.forEach(([el, at]) => { el.style.opacity = p >= 1 ? 1 : clamp((p - at) / 0.05); });
    bars.forEach(([bar, el]) => {
      const local = ease(clamp((p - bar.from) / (bar.to - bar.from)));
      const moving = bar.fixed + (bar.moving - bar.fixed) * local;
      const top = Math.min(bar.fixed, moving), bottom = Math.max(bar.fixed, moving);
      el.setAttribute("d", bottom - top < 0.01 ? "" : columnPath(bar.x, top, bar.width, bottom, bar.radius));
    });
    rows.forEach(([bar, el]) => {
      const width = bar.width * ease(clamp((p - bar.from) / Math.max(0.001, bar.to - bar.from)));
      el.setAttribute("d", width < 0.01 ? "" : rowPath(bar.x, bar.y, width, bar.height, bar.radius));
    });
    if (clip) {
      const revealed = anim.width * ease(p);
      clip.setAttribute("width", p >= 1 ? anim.width + anim.pad * 2 : revealed + anim.pad);
      heads.forEach(([xy, el]) => {
        const [x, y] = pointAt(xy, anim.x0 + revealed);
        el.setAttribute("cx", x);
        el.setAttribute("cy", y);
        el.style.opacity = p > 0 ? 1 : 0;
      });
    }
  };
}

// ---------- Hover ----------

// Labels reach the DOM through textContent only.
export function attachHover(svgElement, hover, tooltip) {
  if (!hover) return;
  const NS = "http://www.w3.org/2000/svg";
  const viewWidth = svgElement.viewBox.baseVal.width;
  const scale = () => svgElement.getBoundingClientRect().width / viewWidth;

  function show(title, rows, clientX, clientY) {
    tooltip.replaceChildren();
    const head = document.createElement("div");
    head.className = "tip-title";
    head.textContent = title;
    tooltip.append(head);
    rows.forEach((row) => {
      const el = document.createElement("div");
      el.className = "tip-row";
      if (row.color) {
        const key = document.createElement("span");
        key.className = "tip-key";
        key.style.background = row.color;
        el.append(key);
      }
      // A row is money, or a count given as `text`.
      const value = row.text != null ? document.createElement("span") : moneyNode(row.copper, { signed: row.signed });
      if (row.text != null) value.textContent = row.text;
      value.classList.add("tip-value");
      el.append(value);
      if (row.label) {
        const label = document.createElement("span");
        label.className = "tip-label";
        label.textContent = row.label;
        el.append(label);
      }
      tooltip.append(el);
    });
    tooltip.hidden = false;
    const box = tooltip.getBoundingClientRect();
    tooltip.style.left = `${Math.min(window.innerWidth - box.width - 8, clientX + 14)}px`;
    tooltip.style.top = `${Math.max(8, clientY - box.height - 10)}px`;
  }
  const hide = () => { tooltip.hidden = true; };

  if (hover.kind === "bars") {
    hover.hits.forEach((hit) => {
      const rect = document.createElementNS(NS, "rect");
      for (const [key, value] of Object.entries({ x: hit.x, y: hit.y, width: hit.w, height: hit.h, fill: "transparent", tabindex: 0 })) rect.setAttribute(key, value);
      rect.setAttribute("aria-label", `${hit.title}: ${hit.text ?? moneyWords(hit.copper, { signed: hit.signed })}`);
      rect.style.outline = "none";
      const open = (x, y) => show(hit.title, hit.rows ?? [{ copper: hit.copper, signed: hit.signed }], x, y);
      rect.addEventListener("pointermove", (e) => open(e.clientX, e.clientY));
      rect.addEventListener("pointerleave", hide);
      rect.addEventListener("focus", () => { const b = rect.getBoundingClientRect(); open(b.left + b.width / 2, b.top + 40); });
      rect.addEventListener("blur", hide);
      svgElement.append(rect);
    });
    return;
  }

  const { area, points, s } = hover;
  const group = document.createElementNS(NS, "g");
  group.style.display = "none";
  const cross = document.createElementNS(NS, "line");
  cross.setAttribute("y1", area.y);
  cross.setAttribute("y2", area.y + area.h);
  cross.setAttribute("stroke", C.text3);
  cross.setAttribute("stroke-width", s);
  group.append(cross);
  const dots = points[0].rows.filter((r) => r.y !== undefined).map((r) => {
    const dot = document.createElementNS(NS, "circle");
    dot.setAttribute("r", 4 * s);
    dot.setAttribute("fill", r.color);
    dot.setAttribute("stroke", C.surface);
    dot.setAttribute("stroke-width", 2 * s);
    group.append(dot);
    return dot;
  });
  svgElement.append(group);
  const hit = document.createElementNS(NS, "rect");
  for (const [key, value] of Object.entries({ x: area.x, y: area.y, width: area.w, height: area.h, fill: "transparent" })) hit.setAttribute(key, value);
  svgElement.append(hit);
  hit.addEventListener("pointermove", (e) => {
    const bounds = svgElement.getBoundingClientRect();
    const x = (e.clientX - bounds.left) / scale();
    let nearest = points[0];
    for (const point of points) if (Math.abs(point.x - x) < Math.abs(nearest.x - x)) nearest = point;
    group.style.display = "";
    cross.setAttribute("x1", nearest.x);
    cross.setAttribute("x2", nearest.x);
    nearest.rows.filter((r) => r.y !== undefined).forEach((r, i) => {
      dots[i].setAttribute("cx", nearest.x);
      dots[i].setAttribute("cy", r.y);
    });
    show(nearest.title, nearest.rows, e.clientX, e.clientY);
  });
  hit.addEventListener("pointerleave", () => { group.style.display = "none"; hide(); });
}

// ---------- Tables ----------

// The same numbers as each chart, readable without hovering. A cell is text,
// {copper, signed} or {text, icon}.
export function tableFor(kind, data, settings) {
  const money = (copper, signed = false) => ({ copper, signed });
  if (kind === "start") {
    const d = data.start;
    return { columns: ["Line", "Amount"], numeric: [1], rows: [
      ["Gold at start", money(d.start)],
      ...d.all_rows.map((r) => [r.label, money(r.value, true)]),
      ["Gold at end", money(d.end)],
    ] };
  }
  if (kind === "auction") {
    const d = data.auction;
    return { columns: ["Item", "Quantity sold", "Sold", "Spent", "Net"], numeric: [1, 2, 3, 4],
      rows: d.top.map((r) => [{ text: r.name, icon: r.icon }, number.format(r.quantity), money(r.sold), money(r.spent), money(r.net, true)]) };
  }
  if (kind in BREAKDOWNS) {
    const d = data[kind], config = BREAKDOWNS[kind], view = breakdownView(kind, d, settings), { groups } = view;
    const indent = (label) => `   ${label}`;
    // The parts under a row, for the parts it has and only when they say something.
    const details = (r, parts) => (config.details[r.key] ?? []).filter((detail) => !detail.when || detail.when(parts));
    // A part that adds to or takes from its row shows its sign.
    const signed = (detail, copper) => money((detail.sign ?? 1) * copper, detail.sign !== undefined);
    if (groups) {
      // One column per character group, as the bars are stacked.
      const partOf = (g, key) => g.ids.reduce((sum, id) => sum + (d.parts_by_character?.[id]?.[key] || 0), 0);
      return { columns: [config.column, ...groups.map((g) => g.name), "Total"], numeric: groups.map((_, i) => i + 1).concat(groups.length + 1), rows: [
        ...view.rows.flatMap((r) => [
          [r.label, ...r.segments.map((seg) => money(seg.value)), money(r.value)],
          ...details(r, view.parts).map((detail) =>
            [indent(detail.label), ...groups.map((g) => signed(detail, partOf(g, detail.key))), signed(detail, view.parts[detail.key])]),
        ]),
        [config.totalLabel, ...groups.map((g) => money(g.total)), money(view.total)],
      ] };
    }
    return { columns: [config.column, "Amount", "How many"], numeric: [1, 2], rows: [
      ...d.rows.flatMap((r) => [
        [r.label, money(r.value), r.count ? countText(kind, r.key, r.count) : ""],
        ...details(r, d.parts).map((detail) => [indent(detail.label), signed(detail, d.parts[detail.key]), ""]),
      ]),
      ...(d.unpriced_returns ? [["Returned listings with no deposit on record", "", number.format(d.unpriced_returns)]] : []),
      [config.totalLabel, money(d.total), ""],
    ] };
  }
  if (kind === "item") {
    const d = data.item, { sold, gained, spent } = d;
    const price = (copper) => (copper == null ? "" : money(copper));
    const reagents = d.recipe?.reagents ?? [];
    const soldWhere = [sold.auction ? `${number.format(sold.auction)} at auction` : "", sold.vendor ? `${number.format(sold.vendor)} to vendors` : ""].filter(Boolean);
    return { columns: ["Line", "How many", "Amount", "Detail"], numeric: [1, 2], rows: [
      ["Sold", number.format(sold.quantity), money(sold.revenue), [...soldWhere, sold.auction ? "after the auction house cut" : ""].filter(Boolean).join(", ")],
      ["Highest price each", "", price(sold.highest), sold.price_from === "vendor" ? "Vendor sales" : sold.price_from ? "Auction sales, before the cut" : "No sales"],
      ["Lowest price each", "", price(sold.lowest), ""],
      ["Farmed", number.format(gained.farmed), "", "Looted by your own characters"],
      ["Crafted", number.format(gained.crafted), "", plural(gained.crafts, "craft", "crafts")],
      ["Bought", number.format(gained.bought), money(spent.bought), [plural(spent.purchases, "purchase", "purchases"),
        gained.unknown_purchases ? `${gained.unknown_purchases} with no quantity on record` : "",
        gained.inferred_purchases ? `${gained.inferred_purchases} read from gold spent at a vendor` : ""].filter(Boolean).join(", ")],
      ...(gained.crafts ? [["Materials to craft it", "", money(spent.materials), d.recipe
        ? `Recipe read from ${plural(d.recipe.seen, "craft", "crafts")}, making ${d.recipe.makes} each`
        : "Recipe not seen: no bag snapshot showed a clean craft"]] : []),
      ...reagents.map((r) => [`   ${r.name}`, number.format(r.used), money(r.cost), r.unit_cost == null
        ? `${r.per_craft} per craft. No cost on record: never bought, farmed or crafted`
        : `${r.per_craft} per craft, ${moneyWords(r.unit_cost)} each on average`]),
      ["Total spent", "", money(spent.total), d.materials_unknown ? "Some materials have no cost on record" : ""],
      ["Sales minus spending", "", money(d.net, true), ""],
    ] };
  }
  return { columns: ["Time", "Total value", "Gold", "Other assets", "Equipped gear"], numeric: [1, 2, 3, 4],
    rows: data.value.points.map((p) => [formatTime(p.time), money(p.total), money(p.gold), money(p.assets), money(p.equipped)]) };
}
