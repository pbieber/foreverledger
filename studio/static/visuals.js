// Item cards for the video: the item's icon and in-game style tooltip, with a gold
// amount beside it in green for a gain or red for a loss. One drawing serves the
// screen and the exported PNG, which has a transparent background for overlaying.
import { COINS } from "./coins.js";

export const QUALITY_COLORS = ["#9d9d9d", "#ffffff", "#1eff00", "#0070dd", "#a335ee", "#ff8000", "#e6cc80", "#00ccff"];
const TEXT_COLORS = { q: "#ffd100", ...Object.fromEntries(QUALITY_COLORS.map((c, i) => [`q${i}`, c])) };
const GAIN = "#3fe07a";
const LOSS = "#ff5252";
// The game's tooltip typeface where it is installed, otherwise the studio's own.
const FONT = "'Friz Quadrata TT','Friz Quadrata','Segoe UI Variable Text','Segoe UI',system-ui,sans-serif";
const L = {
  margin: 14, icon: 46, iconGap: 6, padX: 11, padY: 9, radius: 5,
  title: 16, titleLine: 21, body: 13.5, bodyLine: 18, columnGap: 22, minInner: 150, maxInner: 300,
  value: 30, valuePadX: 14, valuePadY: 8, valueGap: 16, coin: 0.82,
};
export const EXPORT_SCALE = 3;

const images = new Map();
function loadImage(src) {
  if (!images.has(src)) {
    const image = new Image();
    image.src = src;
    images.set(src, image.decode().then(() => image, () => null));
  }
  return images.get(src);
}

// The gold amount exactly as typed, in its non-zero pieces: 1,204g 5s, never rounded.
export function valueParts(copper) {
  const abs = Math.abs(Math.round(copper));
  const parts = [[Math.floor(abs / 10000), "gold"], [Math.floor(abs / 100) % 100, "silver"], [abs % 100, "copper"]]
    .filter(([amount]) => amount).map(([amount, coin]) => ({ text: amount.toLocaleString("en-US"), coin }));
  return parts.length ? parts : [{ text: "0", coin: "gold" }];
}

export function valueWords(copper) {
  if (!copper) return "no amount";
  return `${copper > 0 ? "plus" : "minus"} ${valueParts(copper).map((p) => `${p.text} ${p.coin}`).join(" ")}`;
}

// Tooltip lines the card shows, after its choices about item level and sell price.
export function shownLines(item, visual) {
  const lines = item.lines.length ? item.lines : [{ left: [{ text: item.name, color: `q${item.quality}` }], right: [] }];
  return lines.filter((line, i) => {
    if (i === 0) return true;
    if (line.sell && !visual.sell) return false;
    const text = line.left.map((s) => s.text).join("");
    return visual.ilvl || !/^Item Level\b/.test(text);
  });
}

function fontFor(size, bold) {
  return `${bold ? 600 : 400} ${size}px ${FONT}`;
}

// Splits a side's spans into words, spaces and coins, each with its own width.
function tokens(context, spans, size) {
  const coinSize = size * L.coin;
  const out = [];
  for (const span of spans) {
    if (span.coin) {
      context.font = fontFor(size, size === L.title);
      out.push({ text: span.text, coin: span.coin, width: context.measureText(span.text).width + 2 + coinSize });
      continue;
    }
    for (const piece of span.text.split(/(\s+)/)) {
      if (!piece) continue;
      context.font = fontFor(size, size === L.title);
      out.push({ text: piece, space: /^\s+$/.test(piece), color: TEXT_COLORS[span.color] ?? "#ffffff", width: context.measureText(piece).width });
    }
  }
  return out;
}

const widthOf = (list) => list.reduce((sum, t) => sum + t.width, 0);

// Fills rows up to a width, breaking at spaces. A word wider than a row gets its own.
function wrap(list, width) {
  const rows = [[]];
  let used = 0;
  for (const token of list) {
    const row = rows[rows.length - 1];
    if (token.space && !row.length) continue;
    if (!token.space && row.length && used + token.width > width) {
      while (row.length && row[row.length - 1].space) used -= row.pop().width;
      rows.push([token]);
      used = token.width;
      continue;
    }
    row.push(token);
    used += token.width;
  }
  return rows.filter((row, i) => row.length || i === 0);
}

function layout(context, item, visual) {
  const lines = shownLines(item, visual).map((line, i) => {
    const size = i === 0 ? L.title : L.body;
    return { size, height: i === 0 ? L.titleLine : L.bodyLine, left: tokens(context, line.left, size), right: tokens(context, line.right, size) };
  });
  const natural = Math.max(...lines.map((line) => widthOf(line.left) + (line.right.length ? L.columnGap + widthOf(line.right) : 0)));
  const inner = Math.ceil(Math.min(L.maxInner, Math.max(L.minInner, natural)));
  let height = 0;
  for (const line of lines) {
    const room = line.right.length ? inner - L.columnGap - widthOf(line.right) : inner;
    line.rows = wrap(line.left, Math.max(room, inner * 0.4));
    line.top = height;
    height += line.rows.length * line.height;
  }
  return { lines, inner, height };
}

async function drawTokens(context, list, x, baseline, size) {
  const coinSize = size * L.coin;
  for (const token of list) {
    context.font = fontFor(size, size === L.title);
    if (token.coin) {
      context.fillStyle = "#ffffff";
      context.fillText(token.text, x, baseline);
      const coin = await loadImage(COINS[token.coin]);
      const textWidth = token.width - 2 - coinSize;
      if (coin) context.drawImage(coin, x + textWidth + 2, baseline - coinSize * 0.86, coinSize, coinSize);
    } else if (!token.space) {
      context.fillStyle = token.color;
      context.fillText(token.text, x, baseline);
    }
    x += token.width;
  }
}

function roundedBox(context, x, y, width, height, radius) {
  context.beginPath();
  context.roundRect(x, y, width, height, radius);
  context.fillStyle = "rgba(6, 9, 22, 0.94)";
  context.fill();
  context.lineWidth = 1.5;
  context.strokeStyle = "rgba(190, 196, 210, 0.75)";
  context.stroke();
}

function measureValue(context, copper) {
  const parts = valueParts(copper);
  const coinSize = L.value * L.coin;
  context.font = fontFor(L.value, true);
  const sign = copper > 0 ? "+" : "−";
  const signWidth = context.measureText(sign).width + 2;
  const pieces = parts.map((p) => ({ ...p, width: context.measureText(p.text).width }));
  const width = signWidth + pieces.reduce((sum, p) => sum + p.width + 3 + coinSize, 0) + (pieces.length - 1) * 7;
  return { sign, signWidth, pieces, coinSize, width: width + L.valuePadX * 2, height: L.value + L.valuePadY * 2 };
}

async function drawValue(context, copper, value, x, y) {
  roundedBox(context, x, y, value.width, value.height, L.radius);
  const baseline = y + L.valuePadY + L.value * 0.84;
  let at = x + L.valuePadX;
  context.font = fontFor(L.value, true);
  context.fillStyle = copper > 0 ? GAIN : LOSS;
  context.fillText(value.sign, at, baseline);
  at += value.signWidth;
  for (const piece of value.pieces) {
    context.fillStyle = copper > 0 ? GAIN : LOSS;
    context.fillText(piece.text, at, baseline);
    at += piece.width + 3;
    const coin = await loadImage(COINS[piece.coin]);
    if (coin) context.drawImage(coin, at, baseline - value.coinSize * 0.86, value.coinSize, value.coinSize);
    at += value.coinSize + 7;
  }
}

// Draws the card onto a new canvas at `scale` (1 is the size of the game's tooltip).
export async function drawVisual(item, visual, scale = 1) {
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  const box = layout(context, item, visual);
  const tipWidth = box.inner + L.padX * 2, tipHeight = box.height + L.padY * 2;
  const value = visual.copper ? measureValue(context, visual.copper) : null;
  const tipX = L.margin + L.icon + L.iconGap, tipY = L.margin;
  const below = visual.place === "below";
  let width = tipX + tipWidth + L.margin, height = tipY + tipHeight + L.margin;
  let valueX = 0, valueY = 0;
  if (value && below) {
    valueX = tipX;
    valueY = tipY + tipHeight + L.valueGap / 2;
    width = Math.max(width, valueX + value.width + L.margin);
    height = valueY + value.height + L.margin;
  } else if (value) {
    valueX = tipX + tipWidth + L.valueGap;
    valueY = tipY + Math.max(0, (Math.min(tipHeight, 160) - value.height) / 2);
    width = valueX + value.width + L.margin;
    height = Math.max(height, valueY + value.height + L.margin);
  }
  canvas.width = Math.ceil(width * scale);
  canvas.height = Math.ceil(height * scale);
  context.scale(scale, scale);
  context.textBaseline = "alphabetic";

  // The icon, framed in its quality colour.
  const frame = QUALITY_COLORS[item.quality] ?? QUALITY_COLORS[1];
  context.fillStyle = "#000000";
  context.fillRect(L.margin, L.margin, L.icon, L.icon);
  const icon = item.icon ? await loadImage(item.icon) : null;
  if (icon) context.drawImage(icon, L.margin + 2, L.margin + 2, L.icon - 4, L.icon - 4);
  context.lineWidth = 2;
  context.strokeStyle = frame;
  context.strokeRect(L.margin + 1, L.margin + 1, L.icon - 2, L.icon - 2);

  roundedBox(context, tipX, tipY, tipWidth, tipHeight, L.radius);
  const left = tipX + L.padX, right = tipX + tipWidth - L.padX;
  for (const line of box.lines) {
    for (const [i, row] of line.rows.entries()) {
      const baseline = tipY + L.padY + line.top + i * line.height + line.size * 1.02;
      await drawTokens(context, row, left, baseline, line.size);
      if (i === 0 && line.right.length) await drawTokens(context, line.right, right - widthOf(line.right), baseline, line.size);
    }
  }
  if (value) await drawValue(context, visual.copper, value, valueX, valueY);
  return canvas;
}

export async function visualBlob(item, visual) {
  const canvas = await drawVisual(item, visual, EXPORT_SCALE);
  const blob = await new Promise((resolve) => { canvas.toBlob(resolve, "image/png"); });
  if (!blob) throw new Error("The image could not be created");
  return { blob, width: canvas.width, height: canvas.height };
}
