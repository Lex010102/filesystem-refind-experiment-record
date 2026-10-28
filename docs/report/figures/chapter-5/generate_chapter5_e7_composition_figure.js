#!/usr/bin/env node

/*
 * Editable diagram for the RQ3 E7 composition path (Figure 5.4).
 *
 * This is an explanatory architecture figure. It contains no measured result
 * and performs no network or model call. The file writes an SVG source and a
 * PNG preview with the same stem.
 */

const fs = require("node:fs");
const path = require("node:path");
const sharp = require("sharp");

const OUT = __dirname;
const STEM = "figure-5-4-e7-composition";
const W = 1800;
const H = 1330;

const C = {
  bg: "#FEFEFE",
  navy: "#102F50",
  muted: "#5F7890",
  border: "#A9BBC9",
  grid: "#DDE5EB",
  teal: "#0A918A",
  tealPale: "#DDF4F1",
  violet: "#5263D8",
  violetPale: "#E9EBFF",
  amber: "#CF8115",
  amberPale: "#FCEBD2",
  bluePale: "#EAF1F7",
  white: "#FFFFFF",
};

function esc(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function lineText(x, y, value, options = {}) {
  const {
    size = 26,
    weight = 600,
    fill = C.navy,
    anchor = "middle",
  } = options;
  return `<text x="${x}" y="${y}" text-anchor="${anchor}" font-family="Arial, Helvetica, sans-serif" font-size="${size}" font-weight="${weight}" fill="${fill}" text-rendering="geometricPrecision">${esc(value)}</text>`;
}

function box(x, y, width, height, options = {}) {
  const {
    fill = C.white,
    stroke = C.border,
    strokeWidth = 2.5,
    radius = 18,
    shadow = false,
  } = options;
  return `<rect x="${x}" y="${y}" width="${width}" height="${height}" rx="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"${shadow ? ' filter="url(#shadow)"' : ""}/>`;
}

function arrowPath(d, colour = C.navy, width = 4, marker = "arrow-navy") {
  return `<path d="${d}" fill="none" stroke="${colour}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round" marker-end="url(#${marker})"/>`;
}

function stageBox(x, y, width, height, title, detail, options = {}) {
  const {
    stroke = C.border,
    fill = C.white,
    titleColour = C.navy,
    detailColour = C.muted,
    titleSize = 28,
    detailSize = 20,
  } = options;
  return [
    box(x, y, width, height, { fill, stroke, strokeWidth: 2.5, radius: 17 }),
    lineText(x + width / 2, y + 34, title, { size: titleSize, weight: 700, fill: titleColour }),
    lineText(x + width / 2, y + 62, detail, { size: detailSize, weight: 500, fill: detailColour }),
  ].join("\n");
}

function parentPanel(x, colour, pale, heading, storageTitle, storageDetail, retrievalTitle, retrievalDetail, bundleTitle, bundleDetail) {
  const width = 780;
  const innerX = x + 70;
  const innerWidth = 640;
  return [
    box(x, 260, width, 430, { fill: pale, stroke: colour, strokeWidth: 3, radius: 24, shadow: true }),
    `<path d="M ${x + 24} 260 H ${x + width - 24} Q ${x + width} 260 ${x + width} 284 V 330 H ${x} V 284 Q ${x} 260 ${x + 24} 260 Z" fill="${colour}"/>`,
    lineText(x + width / 2, 306, heading, { size: 31, weight: 700, fill: C.white }),
    stageBox(innerX, 355, innerWidth, 80, storageTitle, storageDetail, { stroke: colour, fill: C.white }),
    arrowPath(`M ${x + width / 2} 435 V 465`, colour, 4, colour === C.teal ? "arrow-teal" : "arrow-violet"),
    stageBox(innerX, 475, innerWidth, 80, retrievalTitle, retrievalDetail, { stroke: colour, fill: C.white }),
    arrowPath(`M ${x + width / 2} 555 V 585`, colour, 4, colour === C.teal ? "arrow-teal" : "arrow-violet"),
    stageBox(innerX, 595, innerWidth, 74, bundleTitle, bundleDetail, { stroke: colour, fill: C.white, titleSize: 27, detailSize: 19 }),
  ].join("\n");
}

function buildSvg() {
  const parts = [];
  parts.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`);
  parts.push(`<defs>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="150%">
      <feDropShadow dx="0" dy="7" stdDeviation="8" flood-color="#102F50" flood-opacity="0.12"/>
    </filter>
    <marker id="arrow-navy" viewBox="0 0 12 12" refX="10" refY="6" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 12 6 L 0 12 z" fill="${C.navy}"/></marker>
    <marker id="arrow-teal" viewBox="0 0 12 12" refX="10" refY="6" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 12 6 L 0 12 z" fill="${C.teal}"/></marker>
    <marker id="arrow-violet" viewBox="0 0 12 12" refX="10" refY="6" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 12 6 L 0 12 z" fill="${C.violet}"/></marker>
    <marker id="arrow-amber" viewBox="0 0 12 12" refX="10" refY="6" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 12 6 L 0 12 z" fill="${C.amber}"/></marker>
  </defs>`);
  parts.push(`<rect width="${W}" height="${H}" fill="${C.bg}"/>`);

  parts.push(lineText(900, 76, "How E7 Is Constructed", { size: 54, weight: 750 }));
  parts.push(lineText(900, 122, "Two representation-appropriate retrieval paths are fused after retrieval", { size: 25, weight: 500, fill: C.muted }));

  parts.push(box(630, 155, 540, 70, { fill: C.bluePale, stroke: C.navy, strokeWidth: 2.5, radius: 35, shadow: true }));
  parts.push(lineText(900, 200, "Same question q", { size: 29, weight: 700 }));
  parts.push(arrowPath("M 900 225 V 238 H 470 V 258", C.navy, 3.5));
  parts.push(arrowPath("M 900 225 V 238 H 1330 V 258", C.navy, 3.5));

  parts.push(parentPanel(
    80,
    C.teal,
    C.tealPale,
    "E2 · Raw-dialogue evidence path",
    "S1 · Flat Raw Sessions",
    "original 30-session dialogue",
    "R2 · ReFind-Style Raw-Chat Retrieval",
    "lexical retrieval over raw exchanges and sessions",
    "E2 EvidenceBundle",
    "raw exchange windows · ≤ 16,000 characters",
  ));

  parts.push(parentPanel(
    940,
    C.violet,
    C.violetPale,
    "E6 · Curated-memory evidence path",
    "S3 · Agent-Curated Memory",
    "curated facts organised by entity and topic",
    "R3 · Curated-Memory Retrieval",
    "retrieval adapted to fact units and topic groups",
    "E6 EvidenceBundle",
    "curated fact windows · ≤ 16,000 characters",
  ));

  parts.push(arrowPath("M 470 669 V 710 L 730 765", C.teal, 5, "arrow-teal"));
  parts.push(arrowPath("M 1330 669 V 710 L 1070 765", C.violet, 5, "arrow-violet"));

  parts.push(box(500, 765, 800, 115, { fill: C.amberPale, stroke: C.amber, strokeWidth: 3, radius: 24, shadow: true }));
  parts.push(lineText(900, 808, "Deterministic fusion", { size: 32, weight: 750, fill: C.navy }));
  parts.push(lineText(900, 842, "verify parent identity · exact-deduplicate · order-preserving interleave", { size: 21, weight: 500, fill: C.muted }));
  parts.push(box(715, 856, 370, 46, { fill: C.white, stroke: C.amber, strokeWidth: 2, radius: 23 }));
  parts.push(lineText(900, 887, "No new retrieval or query", { size: 19, weight: 700, fill: C.amber }));

  parts.push(arrowPath("M 900 902 V 930", C.amber, 4.5, "arrow-amber"));
  parts.push(box(570, 935, 660, 88, { fill: C.bluePale, stroke: C.navy, strokeWidth: 2.7, radius: 20, shadow: true }));
  parts.push(lineText(900, 973, "E7 fused EvidenceBundle", { size: 29, weight: 750 }));
  parts.push(lineText(900, 1003, "raw + curated evidence · ≤ 32,000 characters", { size: 20, weight: 500, fill: C.muted }));

  parts.push(arrowPath("M 900 1023 V 1064", C.navy, 4.5));
  parts.push(box(680, 1070, 440, 82, { fill: C.white, stroke: C.navy, strokeWidth: 2.7, radius: 20, shadow: true }));
  parts.push(lineText(900, 1106, "Shared Answerer", { size: 29, weight: 750 }));
  parts.push(lineText(900, 1135, "one invocation", { size: 20, weight: 500, fill: C.muted }));

  parts.push(arrowPath("M 900 1152 V 1194", C.navy, 4.5));
  parts.push(box(715, 1200, 370, 68, { fill: C.navy, stroke: C.navy, strokeWidth: 2.5, radius: 34, shadow: true }));
  parts.push(lineText(900, 1244, "E7 candidate answer", { size: 27, weight: 750, fill: C.white }));

  parts.push(lineText(900, 1310, "E7 is a post-retrieval fusion condition—not a new memory store or retriever.", { size: 21, weight: 600, fill: C.muted }));
  parts.push("</svg>");
  return parts.join("\n");
}

async function main() {
  const svg = buildSvg();
  const svgPath = path.join(OUT, `${STEM}.svg`);
  const pngPath = path.join(OUT, `${STEM}.png`);
  fs.writeFileSync(svgPath, svg, "utf8");
  await sharp(Buffer.from(svg)).png().toFile(pngPath);
  process.stdout.write(`${svgPath}\n${pngPath}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
