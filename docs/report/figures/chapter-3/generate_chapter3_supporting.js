#!/usr/bin/env node

/*
 * Deterministic editable source for the optional Chapter 3 storage figure.
 *
 * Figure 3.2 is intentionally maintained as a Markdown text/code block and
 * is not generated as SVG or PNG. Figure 3.6 is an optional
 * storage-organisation figure based on the
 * frozen S1/S2/S3 stores used in the experiment.
 */

const fs = require("node:fs");
const path = require("node:path");
const sharp = require("sharp");

const OUT = __dirname;
const W = 1600;
const H = 900;
const C = {
  bg: "#FEFEFE",
  navy: "#0F2D4E",
  navy2: "#173E67",
  teal: "#0A8C86",
  teal2: "#2D9D96",
  tealPale: "#DDF3F1",
  amber: "#DA902D",
  amberPale: "#FCE9CF",
  violet: "#4D60D6",
  violetPale: "#E8EAFE",
  slate: "#60788E",
  border: "#A8BAC9",
  card: "#F1F5F8",
  card2: "#E9F0F5",
  white: "#FFFFFF",
};

function esc(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function tspans(lines, x, lineHeight = 1.18) {
  const values = Array.isArray(lines) ? lines : [lines];
  return values
    .map((line, index) => `<tspan x="${x}" dy="${index === 0 ? 0 : `${lineHeight}em`}">${esc(line)}</tspan>`)
    .join("");
}

function text(x, y, lines, options = {}) {
  const {
    size = 24,
    weight = 700,
    fill = C.navy,
    anchor = "middle",
    family = "Arial, Helvetica, sans-serif",
    lineHeight = 1.18,
    italic = false,
  } = options;
  return `<text x="${x}" y="${y}" text-anchor="${anchor}" font-family="${family}" font-size="${size}" font-weight="${weight}" fill="${fill}" font-style="${italic ? "italic" : "normal"}" text-rendering="geometricPrecision">${tspans(lines, x, lineHeight)}</text>`;
}

function card(x, y, w, h, options = {}) {
  const {
    fill = C.card,
    stroke = C.border,
    strokeWidth = 2.5,
    radius = 18,
    shadow = true,
    dash = "",
  } = options;
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"${dash ? ` stroke-dasharray="${dash}"` : ""}${shadow ? ' filter="url(#shadow)"' : ""}/>`;
}

function line(x1, y1, x2, y2, options = {}) {
  const { color = C.teal2, width = 4, marker = "arrowTeal", dash = "" } = options;
  return `<path d="M ${x1} ${y1} L ${x2} ${y2}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round"${dash ? ` stroke-dasharray="${dash}"` : ""}${marker ? ` marker-end="url(#${marker})"` : ""}/>`;
}

function pathLine(d, options = {}) {
  const { color = C.teal2, width = 4, marker = "arrowTeal", dash = "" } = options;
  return `<path d="${d}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"${dash ? ` stroke-dasharray="${dash}"` : ""}${marker ? ` marker-end="url(#${marker})"` : ""}/>`;
}

function defs() {
  return `<defs>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="5" stdDeviation="6" flood-color="#0F2D4E" flood-opacity="0.13"/></filter>
    <linearGradient id="navyBand" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#173E67"/><stop offset="1" stop-color="#0F2D4E"/></linearGradient>
    <linearGradient id="tealBand" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#13A099"/><stop offset="1" stop-color="#087F7A"/></linearGradient>
    <linearGradient id="amberBand" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#E8A33A"/><stop offset="1" stop-color="#CF821E"/></linearGradient>
    <marker id="arrowNavy" viewBox="0 0 10 10" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M 1 1 L 9 5 L 1 9 z" fill="${C.navy}"/></marker>
    <marker id="arrowTeal" viewBox="0 0 10 10" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M 1 1 L 9 5 L 1 9 z" fill="${C.teal2}"/></marker>
    <marker id="arrowAmber" viewBox="0 0 10 10" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="userSpaceOnUse"><path d="M 1 1 L 9 5 L 1 9 z" fill="${C.amber}"/></marker>
  </defs>`;
}

function base(title, subtitle) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  ${defs()}
  <rect width="${W}" height="${H}" fill="${C.bg}"/>
  ${text(W / 2, 64, title, { size: 54, weight: 800 })}
  ${text(W / 2, 104, subtitle, { size: 23, weight: 500, fill: C.slate })}`;
}

function laneCard(x, y, w, h, titleLabel, band, fill, stroke, bodyLines, options = {}) {
  const { mono = false, bodySize = 20 } = options;
  let out = card(x, y, w, h, { fill, stroke, strokeWidth: 2.6, radius: 18, shadow: true });
  out += `<path d="M ${x + 18} ${y} H ${x + w - 18} Q ${x + w} ${y} ${x + w} ${y + 18} V ${y + 58} H ${x} V ${y + 18} Q ${x} ${y} ${x + 18} ${y} Z" fill="url(#${band})"/>`;
  out += text(x + w / 2, y + 39, titleLabel, { size: 25, weight: 800, fill: C.white });
  const family = mono ? "Menlo, Consolas, monospace" : "Arial, Helvetica, sans-serif";
  out += text(x + 26, y + 92, bodyLines, { size: bodySize, weight: mono ? 500 : 650, fill: C.navy, anchor: "start", family, lineHeight: 1.34 });
  return out;
}

function figure36() {
  let svg = base(
    "Three Frozen Memory Representations",
    "One canonical conversation is serialised as flat sessions, organised sessions, or curated memory",
  );

  svg += card(455, 120, 690, 72, { fill: C.card2, stroke: C.navy, strokeWidth: 3, radius: 17 });
  svg += text(800, 151, "Canonical conversation", { size: 25, weight: 800 });
  svg += text(800, 178, "30 sessions  ·  568 source turns  ·  common source map", { size: 18, weight: 600, fill: C.slate });

  const xs = [40, 540, 1040];
  const centers = xs.map((x) => x + 240);
  const top = 260;
  const w = 480;
  const h = 484;
  svg += pathLine(`M 800 192 V 218 H ${centers[0]} V ${top - 8}`, { color: C.navy, width: 3.5, marker: "arrowNavy" });
  svg += line(800, 192, 800, top - 8, { color: C.teal2, width: 3.5, marker: "arrowTeal" });
  svg += pathLine(`M 800 192 V 218 H ${centers[2]} V ${top - 8}`, { color: C.amber, width: 3.5, marker: "arrowAmber" });

  svg += laneCard(xs[0], top, w, h, "S1  Flat Raw Sessions", "navyBand", C.card, C.border,
    [
      "/memories/",
      "├── session-01.md",
      "├── session-02.md",
      "├── …",
      "└── session-30.md",
      "",
      "30 flat Markdown files",
      "114,456 bytes",
    ], { mono: true, bodySize: 20 });
  svg += text(xs[0] + 240, top + 452, ["Raw chronological turns", "+ canonical [SxTy] locators"], { size: 18, weight: 700, fill: C.slate, lineHeight: 1.12 });

  svg += laneCard(xs[1], top, w, h, "S2  Foldered Raw Sessions", "tealBand", C.tealPale, C.teal,
    [
      "/memories/",
      "├── cars-and-auto-work/       11",
      "├── music-and-performance/    14",
      "├── photography/               2",
      "└── travel-and-outdoors/       3",
      "",
      "30 files  ·  4 folders",
      "114,456 bytes",
    ], { mono: true, bodySize: 18 });
  svg += text(xs[1] + 240, top + 442, ["All file bodies are byte-identical to S1", "Only relative paths change"], { size: 17, weight: 800, fill: C.teal, lineHeight: 1.14 });

  svg += laneCard(xs[2], top, w, h, "S3  Agent-Curated Memory", "amberBand", C.amberPale, C.amber,
    [
      "/memories/",
      "├── calvin.md",
      "│   ├── # Entity",
      "│   ├── ## Topic groups (18)",
      "│   └── - Fact [source locator(s)]",
      "└── dave.md",
      "    ├── ## Topic groups (17)",
      "    └── - Fact [source locator(s)]",
    ], { mono: true, bodySize: 17 });
  svg += text(xs[2] + 240, top + 442, ["2 files  ·  35 topic groups  ·  390 facts", "Curated and provenance-bearing"], { size: 17, weight: 800, fill: C.amber, lineHeight: 1.14 });

  const branchLabels = [
    [centers[0], "verbatim serialisation", C.navy],
    [centers[1], "same bodies, new paths", C.teal],
    [centers[2], "incremental agent curation", C.amber],
  ];
  for (const [cx, label, color] of branchLabels) {
    svg += `<rect x="${cx - 112}" y="207" width="224" height="32" rx="16" fill="${C.bg}"/>`;
    svg += text(cx, 229, label, { size: 16, weight: 700, fill: color });
  }

  svg += card(275, 786, 1050, 66, { fill: C.card2, stroke: C.navy, strokeWidth: 2.5, radius: 18, shadow: false });
  svg += text(800, 815, "Common provenance contract", { size: 21, weight: 800 });
  svg += text(800, 840, "Retained [SxTy] locators resolve to the same canonical conversation through the shared source map.", { size: 17, weight: 550, fill: C.slate });
  svg += text(1530, 862, "Figure 3.6 (optional)", { size: 15, weight: 600, fill: C.slate, anchor: "end" });
  return `${svg}</svg>`;
}

const outputs = [
  ["figure-3-6-storage-organization", figure36()],
];

async function main() {
  for (const [name, svg] of outputs) {
    const svgPath = path.join(OUT, `${name}.svg`);
    const pngPath = path.join(OUT, `${name}.png`);
    fs.writeFileSync(svgPath, svg);
    await sharp(Buffer.from(svg)).resize({ width: 1672 }).png().toFile(pngPath);
  }
  console.log(`Generated ${outputs.length} Chapter 3 supporting figures in ${OUT}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
