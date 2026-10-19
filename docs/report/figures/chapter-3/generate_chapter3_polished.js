#!/usr/bin/env node

/*
 * Deterministic vector source for the polished Chapter 3 report figures.
 *
 * Figures 3.1 and 3.5 deliberately reuse the Chapter 1–2 visual language:
 * a 16:9 white canvas, navy/teal/amber palette, rounded cards, restrained
 * shadows, and Arial/Helvetica typography. The SVGs remain fully editable;
 * the PNGs are publication-ready previews rendered from the same source.
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
  red: "#D84A49",
  redPale: "#FBE3E3",
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

function tspans(lines, x, lineHeight = 1.16) {
  const values = Array.isArray(lines) ? lines : [lines];
  return values
    .map((line, index) => {
      const dy = index === 0 ? 0 : `${lineHeight}em`;
      return `<tspan x="${x}" dy="${dy}">${esc(line)}</tspan>`;
    })
    .join("");
}

function text(x, y, lines, options = {}) {
  const {
    size = 25,
    weight = 700,
    fill = C.navy,
    anchor = "middle",
    lineHeight = 1.16,
    italic = false,
    letterSpacing = 0,
  } = options;
  return `<text x="${x}" y="${y}" text-anchor="${anchor}" font-family="Arial, Helvetica, sans-serif" font-size="${size}" font-weight="${weight}" fill="${fill}" font-style="${italic ? "italic" : "normal"}" letter-spacing="${letterSpacing}" text-rendering="geometricPrecision">${tspans(lines, x, lineHeight)}</text>`;
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

function centeredLabel(x, y, w, h, lines, options = {}) {
  const size = options.size ?? 21;
  const lineHeight = options.lineHeight ?? 1.08;
  const values = Array.isArray(lines) ? lines : [lines];
  const firstBaseline = y + h / 2 + size * 0.35 - ((values.length - 1) * size * lineHeight) / 2;
  return text(x + w / 2, firstBaseline, values, { ...options, size, lineHeight });
}

function nodeBox(x, y, w, h, lines, options = {}) {
  const {
    fill = C.white,
    stroke = C.border,
    strokeWidth = 2.3,
    size = 21,
    weight = 750,
    iconName = "",
    accent = C.teal,
    shadow = false,
  } = options;
  let out = card(x, y, w, h, { fill, stroke, strokeWidth, radius: 14, shadow });
  const textX = iconName ? x + 72 : x + w / 2;
  if (iconName) out += icon(iconName, x + 39, y + h / 2, 0.44, C.navy, accent);
  const values = Array.isArray(lines) ? lines : [lines];
  const lineHeight = 1.06;
  const firstBaseline = y + h / 2 + size * 0.35 - ((values.length - 1) * size * lineHeight) / 2;
  out += text(textX, firstBaseline, values, {
    size,
    weight,
    anchor: iconName ? "start" : "middle",
    lineHeight,
  });
  return out;
}

function pill(x, y, w, h, label, color, pale, options = {}) {
  const { size = 18, iconName = "" } = options;
  let out = card(x, y, w, h, { fill: pale, stroke: color, strokeWidth: 2, radius: h / 2, shadow: false });
  if (iconName) out += statusIcon(x + 25, y + h / 2, 15, color, iconName);
  out += text(x + (iconName ? 47 : w / 2), y + h / 2 + 6, label, {
    size,
    weight: 750,
    fill: color,
    anchor: iconName ? "start" : "middle",
  });
  return out;
}

function statusIcon(cx, cy, r, color, kind = "check") {
  const mark = kind === "check"
    ? `<path d="M ${cx - 7} ${cy} l 5 6 l 11 -13" fill="none" stroke="#fff" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>`
    : `<path d="M ${cx} ${cy - 8} v 10 M ${cx} ${cy + 8} v 1" fill="none" stroke="#fff" stroke-width="4.5" stroke-linecap="round"/>`;
  return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${color}"/>${mark}`;
}

function arrow(x1, y1, x2, y2, color = C.teal2, width = 4, marker = "arrowTeal", dash = "") {
  return `<path d="M ${x1} ${y1} L ${x2} ${y2}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round"${dash ? ` stroke-dasharray="${dash}"` : ""} marker-end="url(#${marker})"/>`;
}

function pathArrow(d, color = C.teal2, width = 4, marker = "arrowTeal", dash = "") {
  return `<path d="${d}" fill="none" stroke="${color}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"${dash ? ` stroke-dasharray="${dash}"` : ""} marker-end="url(#${marker})"/>`;
}

function icon(kind, cx, cy, scale = 1, color = C.navy, accent = C.teal) {
  const sw = 4.5 * scale;
  if (kind === "chat") {
    return `<g fill="none" stroke="${color}" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round"><rect x="${cx - 34 * scale}" y="${cy - 24 * scale}" width="${68 * scale}" height="${45 * scale}" rx="${10 * scale}"/><path d="M ${cx - 14 * scale} ${cy + 21 * scale} l ${-10 * scale} ${14 * scale} l ${2 * scale} ${-16 * scale}"/><circle cx="${cx - 16 * scale}" cy="${cy - 2 * scale}" r="${3 * scale}" fill="${accent}" stroke="none"/><circle cx="${cx}" cy="${cy - 2 * scale}" r="${3 * scale}" fill="${accent}" stroke="none"/><circle cx="${cx + 16 * scale}" cy="${cy - 2 * scale}" r="${3 * scale}" fill="${accent}" stroke="none"/></g>`;
  }
  if (kind === "database") {
    return `<g fill="none" stroke="${color}" stroke-width="${sw}" stroke-linejoin="round"><ellipse cx="${cx}" cy="${cy - 22 * scale}" rx="${32 * scale}" ry="${13 * scale}" fill="${C.white}"/><path d="M ${cx - 32 * scale} ${cy - 22 * scale} v ${48 * scale} c 0 ${8 * scale} ${64 * scale} ${8 * scale} ${64 * scale} 0 v ${-48 * scale}" fill="${C.card}"/><path d="M ${cx - 32 * scale} ${cy} c 0 ${8 * scale} ${64 * scale} ${8 * scale} ${64 * scale} 0 M ${cx - 32 * scale} ${cy + 20 * scale} c 0 ${8 * scale} ${64 * scale} ${8 * scale} ${64 * scale} 0"/></g>`;
  }
  if (kind === "folder") {
    return `<g stroke="${color}" stroke-width="${sw}" stroke-linejoin="round"><path d="M ${cx - 38 * scale} ${cy - 24 * scale} h ${26 * scale} l ${10 * scale} ${10 * scale} h ${40 * scale} v ${43 * scale} h ${-74 * scale} z" fill="${C.card}"/><path d="M ${cx - 34 * scale} ${cy - 8 * scale} h ${70 * scale} l ${-7 * scale} ${37 * scale} h ${-70 * scale} z" fill="${accent}" opacity="0.75"/></g>`;
  }
  if (kind === "search") {
    return `<g fill="none" stroke="${color}" stroke-width="${sw}" stroke-linecap="round"><circle cx="${cx - 8 * scale}" cy="${cy - 8 * scale}" r="${25 * scale}"/><path d="M ${cx + 10 * scale} ${cy + 10 * scale} l ${25 * scale} ${25 * scale}" stroke="${accent}"/></g>`;
  }
  if (kind === "docs") {
    return `<g fill="${C.white}" stroke="${color}" stroke-width="${sw}" stroke-linejoin="round"><rect x="${cx - 32 * scale}" y="${cy - 30 * scale}" width="${52 * scale}" height="${62 * scale}" rx="${5 * scale}"/><rect x="${cx - 17 * scale}" y="${cy - 18 * scale}" width="${52 * scale}" height="${62 * scale}" rx="${5 * scale}"/><path d="M ${cx - 5 * scale} ${cy - 1 * scale} h ${28 * scale} M ${cx - 5 * scale} ${cy + 12 * scale} h ${28 * scale} M ${cx - 5 * scale} ${cy + 25 * scale} h ${20 * scale}" fill="none" stroke="${accent}"/></g>`;
  }
  if (kind === "chip") {
    let pins = "";
    for (const offset of [-22, -7, 8, 23]) {
      pins += `<path d="M ${cx + offset * scale} ${cy - 39 * scale} v ${10 * scale} M ${cx + offset * scale} ${cy + 29 * scale} v ${10 * scale}"/>`;
      pins += `<path d="M ${cx - 39 * scale} ${cy + offset * scale} h ${10 * scale} M ${cx + 29 * scale} ${cy + offset * scale} h ${10 * scale}"/>`;
    }
    return `<g fill="none" stroke="${color}" stroke-width="${sw}" stroke-linecap="round"><rect x="${cx - 29 * scale}" y="${cy - 29 * scale}" width="${58 * scale}" height="${58 * scale}" rx="${7 * scale}"/><rect x="${cx - 15 * scale}" y="${cy - 15 * scale}" width="${30 * scale}" height="${30 * scale}" rx="${4 * scale}" fill="${accent}" stroke="none"/>${pins}</g>`;
  }
  if (kind === "file") {
    return `<g fill="${C.white}" stroke="${color}" stroke-width="${sw}" stroke-linejoin="round" stroke-linecap="round"><path d="M ${cx - 27 * scale} ${cy - 36 * scale} h ${33 * scale} l ${22 * scale} ${22 * scale} v ${53 * scale} h ${-55 * scale} z"/><path d="M ${cx + 6 * scale} ${cy - 36 * scale} v ${22 * scale} h ${22 * scale}" fill="none"/><path d="M ${cx - 13 * scale} ${cy - 2 * scale} h ${27 * scale} M ${cx - 13 * scale} ${cy + 12 * scale} h ${27 * scale} M ${cx - 13 * scale} ${cy + 26 * scale} h ${19 * scale}" fill="none" stroke="${accent}"/></g>`;
  }
  if (kind === "merge") {
    return `<g fill="none" stroke="${color}" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round"><path d="M ${cx - 34 * scale} ${cy - 24 * scale} H ${cx - 12 * scale} C ${cx + 2 * scale} ${cy - 24 * scale}, ${cx + 2 * scale} ${cy}, ${cx + 16 * scale} ${cy} H ${cx + 34 * scale}"/><path d="M ${cx - 34 * scale} ${cy + 24 * scale} H ${cx - 12 * scale} C ${cx + 2 * scale} ${cy + 24 * scale}, ${cx + 2 * scale} ${cy}, ${cx + 16 * scale} ${cy}"/><circle cx="${cx + 33 * scale}" cy="${cy}" r="${7 * scale}" fill="${accent}" stroke="none"/></g>`;
  }
  if (kind === "score") {
    return `<g fill="none" stroke="${color}" stroke-width="${sw}" stroke-linecap="round"><path d="M ${cx - 32 * scale} ${cy + 29 * scale} V ${cy - 29 * scale} M ${cx - 32 * scale} ${cy + 29 * scale} H ${cx + 35 * scale}"/><rect x="${cx - 20 * scale}" y="${cy + 2 * scale}" width="${11 * scale}" height="${27 * scale}" fill="${accent}" stroke="none"/><rect x="${cx - 2 * scale}" y="${cy - 12 * scale}" width="${11 * scale}" height="${41 * scale}" fill="${accent}" opacity="0.8" stroke="none"/><rect x="${cx + 16 * scale}" y="${cy - 26 * scale}" width="${11 * scale}" height="${55 * scale}" fill="${accent}" opacity="0.6" stroke="none"/></g>`;
  }
  return `<circle cx="${cx}" cy="${cy}" r="${28 * scale}" fill="${accent}" stroke="${color}" stroke-width="${sw}"/>`;
}

function base(title, subtitle) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <defs>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="5" stdDeviation="6" flood-color="#0F2D4E" flood-opacity="0.13"/></filter>
    <linearGradient id="navyBand" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#173E67"/><stop offset="1" stop-color="#0F2D4E"/></linearGradient>
    <linearGradient id="tealBand" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#13A099"/><stop offset="1" stop-color="#087F7A"/></linearGradient>
    <linearGradient id="amberBand" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#E8A33A"/><stop offset="1" stop-color="#CF821E"/></linearGradient>
    <linearGradient id="violetBand" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#6374E6"/><stop offset="1" stop-color="#4656C5"/></linearGradient>
    <marker id="arrowNavy" viewBox="0 0 12 12" markerWidth="16" markerHeight="16" refX="11" refY="6" orient="auto" markerUnits="userSpaceOnUse"><path d="M 1 1 L 11 6 L 1 11 Z" fill="${C.navy}"/></marker>
    <marker id="arrowTeal" viewBox="0 0 12 12" markerWidth="16" markerHeight="16" refX="11" refY="6" orient="auto" markerUnits="userSpaceOnUse"><path d="M 1 1 L 11 6 L 1 11 Z" fill="${C.teal2}"/></marker>
    <marker id="arrowAmber" viewBox="0 0 12 12" markerWidth="16" markerHeight="16" refX="11" refY="6" orient="auto" markerUnits="userSpaceOnUse"><path d="M 1 1 L 11 6 L 1 11 Z" fill="${C.amber}"/></marker>
    <marker id="arrowViolet" viewBox="0 0 12 12" markerWidth="16" markerHeight="16" refX="11" refY="6" orient="auto" markerUnits="userSpaceOnUse"><path d="M 1 1 L 11 6 L 1 11 Z" fill="${C.violet}"/></marker>
  </defs>
  <rect width="${W}" height="${H}" fill="${C.bg}"/>
  ${text(W / 2, 64, title, { size: 54, weight: 800 })}
  ${text(W / 2, 104, subtitle, { size: 23, weight: 500, fill: C.slate })}
`;
}

function panel(x, y, w, h, title, gradient, options = {}) {
  const { fill = C.card, border = C.border, titleSize = 25 } = options;
  return [
    card(x, y, w, h, { fill, stroke: border, strokeWidth: 2.5, radius: 20, shadow: true }),
    `<path d="M ${x + 20} ${y} H ${x + w - 20} Q ${x + w} ${y} ${x + w} ${y + 20} V ${y + 68} H ${x} V ${y + 20} Q ${x} ${y} ${x + 20} ${y} Z" fill="url(#${gradient})"/>`,
    text(x + w / 2, y + 44, title, { size: titleSize, weight: 800, fill: C.white }),
  ].join("");
}

function figure31() {
  let svg = base(
    "System Architecture and Evidence Paths",
    "Three memory representations and three retrieval systems converge on one evidence and answering interface",
  );

  // Full Context is drawn as a clean outer bypass above the selective path.
  svg += pathArrow("M 165 224 V 145 H 1435 V 264", C.amber, 4, "arrowAmber", "10 8");
  svg += pill(925, 122, 385, 48, "Full Context: all 30 raw sessions", C.amber, C.amberPale, { size: 18, iconName: "alert" });

  // Canonical input.
  svg += card(45, 224, 240, 142, { fill: C.card2, stroke: C.navy, strokeWidth: 3, radius: 18 });
  svg += icon("chat", 165, 267, 0.53, C.navy, C.teal);
  svg += text(165, 318, ["Canonical conversation", "+ source map"], { size: 21, weight: 800, lineHeight: 1.08 });

  // Storage representations and retrieval systems.
  svg += panel(330, 185, 300, 352, "Memory representations", "navyBand", { fill: C.card2, border: C.navy, titleSize: 24 });
  svg += nodeBox(355, 275, 250, 66, ["S1", "Flat raw", "sessions"], { iconName: "database", size: 15 });
  svg += nodeBox(355, 359, 250, 66, ["S2", "Foldered raw", "sessions"], { iconName: "folder", size: 15 });
  svg += nodeBox(355, 443, 250, 66, ["S3", "Agent-curated", "memory"], { iconName: "file", size: 15 });

  svg += panel(675, 185, 300, 352, "Retrieval systems", "tealBand", { fill: C.tealPale, border: C.teal, titleSize: 24 });
  svg += nodeBox(700, 275, 250, 66, ["R1", "Agentic", "filesystem"], { iconName: "folder", size: 15, accent: C.teal });
  svg += nodeBox(700, 359, 250, 66, ["R2", "Raw-chat", "retrieval"], { iconName: "search", size: 15, accent: C.teal });
  svg += nodeBox(700, 443, 250, 66, ["R3", "Curated-memory", "retrieval"], { iconName: "search", size: 15, accent: C.violet });

  svg += arrow(287, 295, 323, 295, C.teal2, 4.5, "arrowTeal");
  svg += arrow(634, 352, 668, 352, C.teal2, 4.5, "arrowTeal");
  svg += pill(430, 558, 460, 44, "E1–E6: compatible storage–retrieval pairings", C.navy, C.white, { size: 17 });

  // Shared evidence contract and answer path.
  svg += card(1020, 266, 250, 132, { fill: C.tealPale, stroke: C.teal, strokeWidth: 3, radius: 18 });
  svg += icon("docs", 1068, 325, 0.50, C.navy, C.teal);
  svg += text(1182, 317, ["EvidenceBundle", "≤ 16,000 characters"], { size: 18, weight: 800, anchor: "middle", lineHeight: 1.12 });
  svg += arrow(978, 332, 1013, 332, C.teal2, 4.5, "arrowTeal");

  svg += card(1320, 266, 235, 132, { fill: C.card, stroke: C.navy, strokeWidth: 3, radius: 18 });
  svg += icon("chip", 1373, 328, 0.50, C.navy, C.teal);
  svg += text(1472, 338, ["Shared", "Answerer"], { size: 22, weight: 800, lineHeight: 1.04 });
  svg += arrow(1277, 332, 1313, 332, C.teal2, 4.5, "arrowTeal");

  svg += nodeBox(1320, 475, 235, 78, "Candidate answer", { fill: C.white, stroke: C.navy, strokeWidth: 2.7, size: 18, iconName: "file", shadow: true });
  svg += arrow(1438, 405, 1438, 468, C.navy, 4, "arrowNavy");
  svg += nodeBox(1320, 649, 235, 92, ["Offline evaluation", "quality • evidence", "cost"], { fill: C.violetPale, stroke: C.violet, strokeWidth: 2.7, size: 15, iconName: "score", accent: C.violet, shadow: true });
  svg += arrow(1438, 560, 1438, 642, C.violet, 4, "arrowViolet");

  // E7 reuses two already-produced EvidenceBundles; it does not retrieve again.
  svg += card(1000, 500, 275, 202, { fill: C.violetPale, stroke: C.violet, strokeWidth: 2.7, radius: 18 });
  svg += `<rect x="1000" y="500" width="275" height="55" rx="18" fill="url(#violetBand)"/><rect x="1000" y="537" width="275" height="18" fill="url(#violetBand)"/>`;
  svg += text(1138, 536, "E7 dual-source fusion", { size: 23, weight: 800, fill: C.white });
  svg += pill(1022, 574, 105, 40, "E2 bundle", C.teal, C.white, { size: 16 });
  svg += pill(1148, 574, 105, 40, "E6 bundle", C.violet, C.white, { size: 16 });
  svg += text(1138, 602, "+", { size: 22, weight: 800, fill: C.navy });
  svg += arrow(1138, 616, 1138, 628, C.violet, 3.5, "arrowViolet");
  svg += pill(1035, 634, 206, 40, "Deterministic fusion", C.navy, C.white, { size: 16 });
  svg += text(1138, 693, "Deduplicate • interleave", { size: 16, weight: 700, fill: C.slate });
  svg += pathArrow("M 1245 654 H 1296 V 376 H 1313", C.violet, 4, "arrowViolet");
  svg += pill(1028, 719, 220, 42, "No new retrieval", C.violet, C.white, { size: 17, iconName: "check" });

  // Shared system contract.
  svg += card(45, 777, 1225, 78, { fill: C.card2, stroke: C.border, strokeWidth: 2, radius: 18, shadow: false });
  svg += icon("chip", 103, 816, 0.42, C.navy, C.teal);
  svg += text(142, 811, "Same Answerer contract", { size: 21, weight: 800, anchor: "start" });
  svg += text(399, 811, "•", { size: 23, fill: C.slate });
  svg += text(435, 811, "condition-blind prompt", { size: 20, weight: 700, anchor: "start", fill: C.slate });
  svg += text(700, 811, "•", { size: 23, fill: C.slate });
  svg += text(736, 811, "frozen provenance", { size: 20, weight: 700, anchor: "start", fill: C.slate });
  svg += text(955, 811, "•", { size: 23, fill: C.slate });
  svg += text(991, 811, "offline scoring", { size: 20, weight: 700, anchor: "start", fill: C.slate });
  svg += text(657, 844, "Only the evidence-access path changes across the compared conditions", { size: 18, weight: 650, fill: C.slate });

  return `${svg}</svg>`;
}

function figure35() {
  let svg = base(
    "Dual-Source Fusion and Full Context",
    "Both paths use the shared Answerer; only evidence access changes",
  );

  // Paired panels.
  svg += panel(48, 145, 714, 505, "E7  ·  Dual-Source Fusion", "tealBand", { fill: C.tealPale, border: C.teal, titleSize: 29 });
  svg += panel(838, 145, 714, 505, "Full Context  ·  Complete Visibility", "amberBand", { fill: C.amberPale, border: C.amber, titleSize: 29 });

  // E7 panel: two frozen bundles are reused and deterministically merged.
  svg += nodeBox(88, 245, 285, 92, ["E2 EvidenceBundle", "raw-dialogue path"], { fill: C.white, stroke: C.teal, strokeWidth: 2.5, iconName: "docs", size: 18, accent: C.teal });
  svg += nodeBox(437, 245, 285, 92, ["E6 EvidenceBundle", "curated-memory path"], { fill: C.white, stroke: C.violet, strokeWidth: 2.5, iconName: "docs", size: 18, accent: C.violet });
  svg += `<path d="M 230 342 V 365 H 405 M 580 342 V 365 H 405" fill="none" stroke="${C.navy}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>`;
  svg += `<line x1="405" y1="365" x2="405" y2="382" stroke="${C.navy}" stroke-width="3.5" stroke-linecap="round"/>`;
  svg += nodeBox(225, 382, 360, 92, ["Deterministic fusion", "deduplicate • interleave"], { fill: C.white, stroke: C.navy, strokeWidth: 2.7, size: 20, shadow: true });
  svg += pill(100, 528, 270, 46, "No new retrieval", C.teal, C.white, { size: 18, iconName: "check" });
  svg += pill(439, 528, 270, 46, "Up to 32,000 characters", C.violet, C.white, { size: 18, iconName: "check" });
  svg += text(405, 604, ["Tests complementarity—and possible interference—", "between two evidence sources"], { size: 17, weight: 650, fill: C.slate, lineHeight: 1.1 });

  // Full Context panel: a chronological long prompt replaces selective retrieval.
  svg += nodeBox(890, 233, 610, 82, "All 30 S1 raw sessions", { fill: C.white, stroke: C.amber, strokeWidth: 2.5, iconName: "database", size: 21, accent: C.amber });
  svg += `<line x1="1195" y1="315" x2="1195" y2="363" stroke="${C.amber}" stroke-width="4" stroke-linecap="round"/>`;
  svg += nodeBox(890, 363, 610, 82, "Chronological full-history prompt", { fill: C.white, stroke: C.amber, strokeWidth: 2.5, iconName: "docs", size: 21, accent: C.amber });
  svg += pill(884, 495, 200, 46, "No retriever", C.amber, C.white, { size: 17 });
  svg += pill(1094, 495, 275, 46, "No selective 16k limit", C.amber, C.white, { size: 15 });
  svg += pill(1379, 495, 132, 46, "Not an oracle", C.red, C.white, { size: 14 });
  svg += text(1195, 582, ["Complete visibility removes retrieval omission,", "but not attention or evidence-utilisation errors"], { size: 19, weight: 650, fill: C.slate, lineHeight: 1.12 });

  // Both panels converge on the same Answerer instance and output contract.
  svg += `<path d="M 405 650 V 674 H 760 V 694" fill="none" stroke="${C.teal2}" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>`;
  svg += `<path d="M 1195 650 V 674 H 840 V 694" fill="none" stroke="${C.amber}" stroke-width="4.5" stroke-linecap="round" stroke-linejoin="round"/>`;
  svg += card(615, 694, 370, 88, { fill: C.card, stroke: C.navy, strokeWidth: 3, radius: 18 });
  svg += icon("chip", 680, 738, 0.52, C.navy, C.teal);
  svg += text(825, 747, "Shared Answerer", { size: 28, weight: 800 });
  svg += `<line x1="985" y1="738" x2="1080" y2="738" stroke="${C.navy}" stroke-width="4.5" stroke-linecap="round"/>`;
  svg += nodeBox(1080, 694, 300, 88, "Candidate answer", { fill: C.white, stroke: C.navy, strokeWidth: 2.7, iconName: "file", size: 22, shadow: true });

  svg += card(265, 817, 1070, 54, { fill: C.card2, stroke: C.border, strokeWidth: 2, radius: 18, shadow: false });
  svg += text(800, 852, "Same question and answering objective  •  Different evidence-access regime", { size: 22, weight: 800 });

  return `${svg}</svg>`;
}

const outputs = [
  ["figure-3-1-overall-system-architecture", figure31()],
  ["figure-3-5-e7-fusion-vs-full-context", figure35()],
];

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  for (const [stem, svg] of outputs) {
    fs.writeFileSync(path.join(OUT, `${stem}.svg`), svg, "utf8");
    await sharp(Buffer.from(svg))
      .resize(1672, 941, { fit: "fill" })
      .flatten({ background: C.bg })
      .png({ compressionLevel: 9, adaptiveFiltering: true })
      .toFile(path.join(OUT, `${stem}.png`));
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
