#!/usr/bin/env node

/*
 * Deterministic vector sources for the two monochrome Chapter 3 flowcharts.
 *
 * The SVG files remain fully editable. PNG files are rendered from the same
 * sources with Sharp so the report preview and the eventual LaTeX version stay
 * consistent.
 */

const fs = require("node:fs");
const path = require("node:path");
const sharp = require("sharp");

const OUT = __dirname;

const C = {
  bg: "#FAFAFA",
  white: "#FFFFFF",
  secondary: "#F2F2F2",
  lane: "#F7F7F7",
  header: "#E7E7E7",
  ink: "#333333",
  muted: "#666666",
  light: "#B8B8B8",
};

function esc(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function multiText(x, y, lines, options = {}) {
  const values = Array.isArray(lines) ? lines : [lines];
  const {
    size = 22,
    weight = 650,
    fill = C.ink,
    anchor = "middle",
    lineHeight = 1.12,
    family = "Arial, Helvetica, sans-serif",
  } = options;
  const spans = values
    .map((line, index) => {
      const dy = index === 0 ? 0 : `${lineHeight}em`;
      return `<tspan x="${x}" dy="${dy}">${esc(line)}</tspan>`;
    })
    .join("");
  return `<text x="${x}" y="${y}" text-anchor="${anchor}" font-family="${family}" font-size="${size}" font-weight="${weight}" fill="${fill}" text-rendering="geometricPrecision">${spans}</text>`;
}

function centeredText(x, y, w, h, lines, options = {}) {
  const values = Array.isArray(lines) ? lines : [lines];
  const size = options.size || 22;
  const lineHeight = options.lineHeight || 1.12;
  const total = (values.length - 1) * size * lineHeight;
  const baseline = y + h / 2 + size * 0.34 - total / 2;
  return multiText(x + w / 2, baseline, values, { ...options, size, lineHeight });
}

function box(x, y, w, h, lines, options = {}) {
  const {
    fill = C.white,
    stroke = C.ink,
    strokeWidth = 3.2,
    radius = 8,
    dash = "",
    textSize = 22,
    textWeight = 650,
  } = options;
  return [
    `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"${dash ? ` stroke-dasharray="${dash}"` : ""}/>` ,
    centeredText(x, y, w, h, lines, { size: textSize, weight: textWeight }),
  ].join("");
}

function line(x1, y1, x2, y2, options = {}) {
  const {
    stroke = C.ink,
    width = 3,
    dash = "",
    marker = "arrow",
  } = options;
  return `<path d="M ${x1} ${y1} L ${x2} ${y2}" fill="none" stroke="${stroke}" stroke-width="${width}" stroke-linecap="round"${dash ? ` stroke-dasharray="${dash}"` : ""}${marker ? ` marker-end="url(#${marker})"` : ""}/>`;
}

function pathLine(d, options = {}) {
  const {
    stroke = C.ink,
    width = 3,
    dash = "",
    marker = "arrow",
  } = options;
  return `<path d="${d}" fill="none" stroke="${stroke}" stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round"${dash ? ` stroke-dasharray="${dash}"` : ""}${marker ? ` marker-end="url(#${marker})"` : ""}/>`;
}

function base(width, height, title, subtitle) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="userSpaceOnUse">
      <path d="M 1 1 L 9 5 L 1 9 z" fill="${C.ink}"/>
    </marker>
    <marker id="arrowMuted" viewBox="0 0 10 10" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto" markerUnits="userSpaceOnUse">
      <path d="M 1 1 L 9 5 L 1 9 z" fill="${C.muted}"/>
    </marker>
  </defs>
  <rect width="${width}" height="${height}" fill="${C.bg}"/>
  ${multiText(width / 2, 62, title, { size: 46, weight: 800 })}
  ${multiText(width / 2, 103, subtitle, { size: 21, weight: 500, fill: C.muted })}`;
}

function laneHeader(x, y, w, label, sublabel) {
  return [
    `<rect x="${x}" y="${y}" width="${w}" height="62" rx="8" fill="${C.header}" stroke="${C.ink}" stroke-width="3.2"/>`,
    multiText(x + w / 2, y + 29, label, { size: 25, weight: 800 }),
    multiText(x + w / 2, y + 51, sublabel, { size: 15, weight: 500, fill: C.muted }),
  ].join("");
}

function figure33() {
  const W = 1800;
  const H = 1160;
  let svg = base(
    W,
    H,
    "Three Retrieval Systems",
    "The controllers differ in tools and search state, but all terminate at the same EvidenceBundle interface",
  );

  const lanes = [
    {
      x: 55,
      title: "R1",
      subtitle: "Agentic filesystem retrieval",
      nodes: [
        ["Question"],
        ["Filesystem retrieval agent"],
        ["list · grep · view · toc"],
        ["Inspect files and passages"],
        ["take_note or refine query"],
        ["Observation–action state"],
        ["finish_search"],
        ["EvidenceBundle"],
      ],
    },
    {
      x: 690,
      title: "R2",
      subtitle: "Raw-dialogue retrieval",
      nodes: [
        ["Question"],
        ["LLM query controller"],
        ["BM25 over exchange units"],
        ["Rank sessions with RRF"],
        ["Expand ±2 exchanges"],
        ["Exclude seen sessions"],
        ["finish_search"],
        ["EvidenceBundle"],
      ],
    },
    {
      x: 1325,
      title: "R3",
      subtitle: "Curated-memory retrieval",
      nodes: [
        ["Question"],
        ["LLM query controller"],
        ["BM25 over curated facts"],
        ["Rank H2 topic groups with RRF"],
        ["Expand ±2 fact entries"],
        ["Exclude seen topic groups"],
        ["finish_search"],
        ["EvidenceBundle"],
      ],
    },
  ];

  const nodeW = 420;
  const nodeH = 68;
  const rowY = [230, 337, 444, 551, 658, 765, 872, 979];

  for (const lane of lanes) {
    svg += `<rect x="${lane.x - 20}" y="134" width="${nodeW + 70}" height="950" rx="12" fill="${C.lane}" stroke="${C.light}" stroke-width="1.8"/>`;
    svg += laneHeader(lane.x, 151, nodeW, lane.title, lane.subtitle);

    lane.nodes.forEach((label, index) => {
      const isTerminal = index >= 6;
      svg += box(lane.x, rowY[index], nodeW, nodeH, label, {
        fill: isTerminal ? C.secondary : C.white,
        strokeWidth: isTerminal ? 3.6 : 3.2,
        textSize: index === 3 && lane.title === "R3" ? 19 : 21,
        textWeight: isTerminal ? 750 : 650,
      });
      if (index < lane.nodes.length - 1) {
        svg += line(
          lane.x + nodeW / 2,
          rowY[index] + nodeH,
          lane.x + nodeW / 2,
          rowY[index + 1] - 7,
          { width: 3 },
        );
      }
    });

    const loopX = lane.x + nodeW + 34;
    const loopStartY = rowY[5] + nodeH / 2;
    const loopEndY = rowY[1] + nodeH / 2;
    svg += pathLine(
      `M ${lane.x + nodeW} ${loopStartY} H ${loopX} V ${loopEndY} H ${lane.x + nodeW + 5}`,
      { stroke: C.muted, width: 2.4, dash: "8 7", marker: "arrowMuted" },
    );
    svg += `<g transform="translate(${loopX + 12} ${(loopStartY + loopEndY) / 2}) rotate(-90)">${multiText(0, 0, "repeat if evidence is insufficient", { size: 15, weight: 600, fill: C.muted })}</g>`;
  }

  svg += multiText(W / 2, 1127, "Shared contract: each system returns source-linked evidence before the condition-blind Answerer is called", {
    size: 20,
    weight: 650,
    fill: C.muted,
  });

  return `${svg}</svg>`;
}

function figure34() {
  const W = 1300;
  const H = 1410;
  let svg = base(
    W,
    H,
    "Evidence Validation and Answerer Handoff",
    "Observed spans are reconstructed from frozen sources before they can enter the final evidence interface",
  );

  const mainX = 115;
  const mainW = 565;
  const mainH = 76;
  const noteX = 840;
  const noteW = 360;
  const ys = [155, 278, 401, 524, 647, 770, 893, 1016, 1139];
  const labels = [
    ["Retriever observation"],
    ["Model selects observed range"],
    ["Host reopens frozen source"],
    ["Validate range and locator"],
    ["Resolve canonical source IDs"],
    ["Merge duplicates and overlaps"],
    ["Apply source order and", "16,000-character budget"],
    ["Final EvidenceBundle"],
    ["Condition-blind Answerer"],
  ];

  svg += `<rect x="84" y="132" width="628" height="1110" rx="14" fill="${C.lane}" stroke="${C.light}" stroke-width="1.8"/>`;

  labels.forEach((label, index) => {
    const isInterface = index >= 7;
    svg += box(mainX, ys[index], mainW, mainH, label, {
      fill: isInterface ? C.secondary : C.white,
      strokeWidth: isInterface ? 3.7 : 3.2,
      textSize: label.length > 1 ? 20 : 22,
      textWeight: isInterface ? 750 : 650,
    });
    if (index < labels.length - 1) {
      svg += line(
        mainX + mainW / 2,
        ys[index] + mainH,
        mainX + mainW / 2,
        ys[index + 1] - 7,
        { width: 3 },
      );
    }
  });

  const note1Y = 401;
  const note2Y = 524;
  const note3Y = 1103;

  svg += box(noteX, note1Y, noteW, 76, ["No model-written evidence"], {
    fill: C.secondary,
    stroke: C.muted,
    strokeWidth: 2.5,
    dash: "8 6",
    textSize: 19,
  });
  svg += line(mainX + mainW + 8, note1Y + 38, noteX - 8, note1Y + 38, {
    stroke: C.muted,
    width: 2.2,
    dash: "8 6",
    marker: "arrowMuted",
  });

  svg += box(noteX, note2Y, noteW, 76, ["Frozen source is authoritative"], {
    fill: C.secondary,
    stroke: C.muted,
    strokeWidth: 2.5,
    dash: "8 6",
    textSize: 19,
  });
  svg += line(mainX + mainW + 8, note2Y + 38, noteX - 8, note2Y + 38, {
    stroke: C.muted,
    width: 2.2,
    dash: "8 6",
    marker: "arrowMuted",
  });

  svg += box(noteX, note3Y, noteW, 148, ["Answerer cannot see", "condition ID · retrieval trace", "reference answer · gold evidence"], {
    fill: C.secondary,
    stroke: C.muted,
    strokeWidth: 2.5,
    dash: "8 6",
    textSize: 18,
    textWeight: 650,
  });
  svg += line(mainX + mainW + 8, ys[8] + mainH / 2, noteX - 8, note3Y + 74, {
    stroke: C.muted,
    width: 2.2,
    dash: "8 6",
    marker: "arrowMuted",
  });

  svg += box(205, 1290, 970, 74, ["Only validated, source-linked evidence crosses the Answerer boundary"], {
    fill: C.secondary,
    stroke: C.ink,
    strokeWidth: 3,
    textSize: 21,
    textWeight: 700,
  });
  svg += line(mainX + mainW / 2, ys[8] + mainH, mainX + mainW / 2, 1283, { width: 3 });

  return `${svg}</svg>`;
}

const outputs = [
  {
    stem: "figure-3-3-retrieval-system-flowcharts",
    svg: figure33(),
    pngWidth: 1800,
  },
  {
    stem: "figure-3-4-evidence-validation-and-answerer",
    svg: figure34(),
    pngWidth: 1300,
  },
];

async function main() {
  for (const item of outputs) {
    const svgPath = path.join(OUT, `${item.stem}.svg`);
    const pngPath = path.join(OUT, `${item.stem}.png`);
    fs.writeFileSync(svgPath, `${item.svg}\n`, "utf8");
    await sharp(Buffer.from(item.svg))
      .resize({ width: item.pngWidth })
      .png({ compressionLevel: 9 })
      .toFile(pngPath);
    process.stdout.write(`${path.basename(svgPath)}\n${path.basename(pngPath)}\n`);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
