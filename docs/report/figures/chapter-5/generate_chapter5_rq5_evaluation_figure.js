#!/usr/bin/env node

/*
 * Deterministic vector source for Figure 5.8.
 *
 * The program reads only the passed RQ5 evaluation-audit cross-tabulation,
 * verifies the audit and PASSED marker, and writes an editable SVG, a PNG
 * preview, and a data-lineage record. It performs no statistical estimation,
 * model call, or network call.
 */

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const sharp = require("sharp");

const OUT = __dirname;
const ROOT = path.resolve(OUT, "../../../..");
const AUDIT_DIR = path.join(ROOT, "artifacts/chapter5-main60-analysis-v1/rq5-evaluation-audit");
const INPUT = path.join(AUDIT_DIR, "judge-f1-crosstab.csv");
const AUDIT = path.join(AUDIT_DIR, "audit.json");
const PASSED = path.join(AUDIT_DIR, "RQ5-EVALUATION.PASSED");

const STEM = "figure-5-8-token-f1-llm-judge-alignment";
const LINEAGE = "figure-5-8-data-lineage.json";
const W = 2000;
const H = 1125;

const C = {
  background: "#FEFEFE",
  navy: "#102F4F",
  slate: "#61788D",
  border: "#AEBBC6",
  light: "#EAF7F5",
  dark: "#087F78",
  white: "#FFFFFF",
};

const LABELS = ["correct", "partial", "incorrect"];
const DISPLAY_LABELS = {
  correct: "Correct",
  partial: "Partial",
  incorrect: "Incorrect",
};
const BIN_KEYS = [
  "[0.00,0.10)",
  "[0.10,0.25)",
  "[0.25,0.50)",
  "[0.50,0.75)",
  "[0.75,1.00]",
];
const BINS = [
  "[0.00, 0.10)",
  "[0.10, 0.25)",
  "[0.25, 0.50)",
  "[0.50, 0.75)",
  "[0.75, 1.00]",
];
const EXPECTED_COUNTS = {
  correct: [92, 157, 203, 68, 130],
  partial: [31, 18, 14, 11, 0],
  incorrect: [142, 32, 2, 0, 0],
};
const EXPECTED_LABEL_TOTALS = { correct: 650, partial: 74, incorrect: 176 };
const EXPECTED_BIN_TOTALS = [265, 207, 219, 79, 130];

function fail(message) {
  throw new Error(message);
}

function sha256(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function escapeXml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function parseCsv(content) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < content.length; index += 1) {
    const character = content[index];
    if (quoted) {
      if (character === '"' && content[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        field += character;
      }
    } else if (character === '"') {
      quoted = true;
    } else if (character === ",") {
      row.push(field);
      field = "";
    } else if (character === "\n") {
      row.push(field.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += character;
    }
  }
  if (field.length || row.length) {
    row.push(field.replace(/\r$/, ""));
    rows.push(row);
  }
  const header = rows[0] ?? [];
  return rows.slice(1)
    .filter((values) => values.some((value) => value !== ""))
    .map((values, rowIndex) => {
      if (values.length !== header.length) fail(`CSV row ${rowIndex + 2} has an invalid field count`);
      return Object.fromEntries(header.map((name, columnIndex) => [name, values[columnIndex]]));
    });
}

function loadData() {
  for (const required of [INPUT, AUDIT, PASSED]) {
    if (!fs.existsSync(required)) fail(`Missing required input: ${path.relative(ROOT, required)}`);
  }

  const audit = JSON.parse(fs.readFileSync(AUDIT, "utf8"));
  const passed = JSON.parse(fs.readFileSync(PASSED, "utf8"));
  if (audit.status !== "passed" || passed.status !== "passed") fail("The evaluation audit must be passed");
  if (audit.protocol_version !== "chapter5-main60-rq5-evaluation-v1") fail("Unexpected protocol version");
  if (passed.protocol_version !== audit.protocol_version || passed.audit_id !== audit.audit_id) {
    fail("PASSED marker does not identify the audited evaluation run");
  }
  if (passed.audit_sha256 !== sha256(AUDIT)) fail("PASSED marker audit hash does not match audit.json");
  if (audit.output_sha256?.["judge-f1-crosstab.csv"] !== sha256(INPUT)) {
    fail("Input table hash does not match the passed audit");
  }

  const rows = parseCsv(fs.readFileSync(INPUT, "utf8"));
  if (rows.length !== 15) fail(`Expected 15 cross-tabulation rows; found ${rows.length}`);

  const matrix = Object.fromEntries(LABELS.map((label) => [label, []]));
  for (const label of LABELS) {
    for (const bin of BIN_KEYS) {
      const matches = rows.filter((row) => row.judge_label === label && row.f1_bin === bin);
      if (matches.length !== 1) fail(`Expected one row for ${label}/${bin}; found ${matches.length}`);
      const row = matches[0];
      const count = Number(row.count);
      const shareOfLabel = Number(row.share_of_label);
      const labelTotal = Number(row.label_total);
      const binTotal = Number(row.bin_total);
      if (![count, shareOfLabel, labelTotal, binTotal].every(Number.isFinite)) {
        fail(`Non-numeric value for ${label}/${bin}`);
      }
      matrix[label].push({ count, shareOfLabel, labelTotal, binTotal });
    }
  }

  for (const label of LABELS) {
    const entries = matrix[label];
    const counts = entries.map((entry) => entry.count);
    const total = counts.reduce((sum, value) => sum + value, 0);
    if (JSON.stringify(counts) !== JSON.stringify(EXPECTED_COUNTS[label])) fail(`Count mismatch for ${label}`);
    if (total !== EXPECTED_LABEL_TOTALS[label]) fail(`Label total mismatch for ${label}`);
    if (entries.some((entry) => entry.labelTotal !== total)) fail(`Reported label total mismatch for ${label}`);
    const shareSum = entries.reduce((sum, entry) => sum + entry.shareOfLabel, 0);
    if (Math.abs(shareSum - 1) > 1e-12) fail(`Within-label shares do not sum to one for ${label}`);
  }

  for (let binIndex = 0; binIndex < BIN_KEYS.length; binIndex += 1) {
    const total = LABELS.reduce((sum, label) => sum + matrix[label][binIndex].count, 0);
    if (total !== EXPECTED_BIN_TOTALS[binIndex]) fail(`Bin total mismatch for ${BIN_KEYS[binIndex]}`);
    if (LABELS.some((label) => matrix[label][binIndex].binTotal !== total)) {
      fail(`Reported bin total mismatch for ${BIN_KEYS[binIndex]}`);
    }
  }

  const grandTotal = Object.values(EXPECTED_LABEL_TOTALS).reduce((sum, value) => sum + value, 0);
  if (grandTotal !== 900 || EXPECTED_BIN_TOTALS.reduce((sum, value) => sum + value, 0) !== grandTotal) {
    fail("Grand total mismatch");
  }
  return { audit, passed, matrix, grandTotal };
}

function mixHex(light, dark, t) {
  const clamp = Math.max(0, Math.min(1, t));
  const parse = (hex) => [1, 3, 5].map((index) => Number.parseInt(hex.slice(index, index + 2), 16));
  const a = parse(light);
  const b = parse(dark);
  const mixed = a.map((value, index) => Math.round(value + (b[index] - value) * clamp));
  return `#${mixed.map((value) => value.toString(16).padStart(2, "0")).join("")}`;
}

function text(x, y, value, options = {}) {
  const {
    size = 24,
    weight = 500,
    fill = C.navy,
    anchor = "middle",
    opacity = 1,
  } = options;
  return `<text x="${x}" y="${y}" text-anchor="${anchor}" font-family="Arial, Helvetica, sans-serif" font-size="${size}" font-weight="${weight}" fill="${fill}" fill-opacity="${opacity}" text-rendering="geometricPrecision">${escapeXml(value)}</text>`;
}

function rect(x, y, width, height, options = {}) {
  const {
    fill = C.white,
    stroke = "none",
    strokeWidth = 0,
    radius = 0,
  } = options;
  return `<rect x="${x}" y="${y}" width="${width}" height="${height}" rx="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
}

function buildSvg(data) {
  const parts = [];
  parts.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`);
  parts.push("<title>Token F1 distribution by frozen LLM judge label</title>");
  parts.push("<desc>A three-by-five teal heatmap shows the distribution of Token F1 scores within the Correct, Partial, and Incorrect frozen LLM judge labels for 900 answers. Each cell reports an answer count and the percentage within that judge label.</desc>");
  parts.push(`<defs><linearGradient id="share-scale" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="${C.light}"/><stop offset="100%" stop-color="${C.dark}"/></linearGradient></defs>`);
  parts.push(rect(0, 0, W, H, { fill: C.background }));

  parts.push(text(W / 2, 86, "Token F1 distribution by frozen LLM judge label", { size: 56, weight: 700 }));
  parts.push(text(W / 2, 139, "Cells report answer count and within-label share across 900 frozen answers", { size: 28, fill: C.slate }));

  const gridX = 480;
  const gridY = 292;
  const cellW = 270;
  const cellH = 176;
  const gap = 8;

  parts.push(text(gridX + ((BINS.length * cellW) - gap) / 2, 178, "Token F1 range", { size: 24, weight: 600 }));
  parts.push(text(gridX - 38, 222, "Frozen LLM judge label", { size: 23, weight: 600, fill: C.slate, anchor: "end" }));
  for (let column = 0; column < BINS.length; column += 1) {
    const x = gridX + column * cellW + (cellW - gap) / 2;
    parts.push(text(x, 218, BINS[column], { size: 24, weight: 600 }));
    parts.push(text(x, 253, `bin N = ${EXPECTED_BIN_TOTALS[column]}`, { size: 19, fill: C.slate }));
  }

  for (let rowIndex = 0; rowIndex < LABELS.length; rowIndex += 1) {
    const label = LABELS[rowIndex];
    const y = gridY + rowIndex * cellH;
    const centerY = y + (cellH - gap) / 2;
    parts.push(text(gridX - 38, centerY - 10, DISPLAY_LABELS[label], { size: 31, weight: 700, anchor: "end" }));
    parts.push(text(gridX - 38, centerY + 27, `N = ${EXPECTED_LABEL_TOTALS[label]}`, { size: 21, fill: C.slate, anchor: "end" }));

    for (let column = 0; column < BINS.length; column += 1) {
      const entry = data.matrix[label][column];
      const percentage = entry.shareOfLabel * 100;
      const x = gridX + column * cellW;
      const fill = mixHex(C.light, C.dark, percentage / 100);
      const foreground = percentage >= 46 ? C.white : C.navy;
      parts.push(rect(x, y, cellW - gap, cellH - gap, {
        fill,
        stroke: C.white,
        strokeWidth: 2,
        radius: 8,
      }));
      parts.push(text(x + (cellW - gap) / 2, centerY - 12, String(entry.count), {
        size: 42,
        weight: 700,
        fill: foreground,
      }));
      parts.push(text(x + (cellW - gap) / 2, centerY + 31, `${percentage.toFixed(1)}%`, {
        size: 24,
        weight: 600,
        fill: foreground,
      }));
    }
  }

  const legendX = 690;
  const legendY = 892;
  const legendW = 620;
  parts.push(text(legendX - 25, legendY + 22, "Within-label share", { size: 22, weight: 600, anchor: "end" }));
  parts.push(rect(legendX, legendY, legendW, 28, { fill: "url(#share-scale)", stroke: C.border, strokeWidth: 1, radius: 3 }));
  parts.push(text(legendX, legendY + 62, "0%", { size: 19, fill: C.slate, anchor: "start" }));
  parts.push(text(legendX + legendW / 2, legendY + 62, "50%", { size: 19, fill: C.slate }));
  parts.push(text(legendX + legendW, legendY + 62, "100%", { size: 19, fill: C.slate, anchor: "end" }));

  parts.push(text(W / 2, 1010, "Percentages are rounded; each row sums to 100% before rounding", { size: 23, fill: C.slate }));
  parts.push(text(W / 2, 1052, "The bins visualise lexical–semantic disagreement; they do not define evaluator error", { size: 22, fill: C.slate }));
  parts.push("</svg>");
  return parts.join("\n");
}

async function main() {
  const data = loadData();
  const svg = buildSvg(data);
  const svgPath = path.join(OUT, `${STEM}.svg`);
  const pngPath = path.join(OUT, `${STEM}.png`);
  const lineagePath = path.join(OUT, LINEAGE);
  fs.writeFileSync(svgPath, `${svg}\n`, "utf8");
  await sharp(Buffer.from(svg)).png({ compressionLevel: 9 }).toFile(pngPath);

  const lineage = {
    figure: "Figure 5.8",
    title: "Token F1 distribution by frozen LLM judge label",
    generated_at_utc: new Date().toISOString(),
    protocol_version: data.audit.protocol_version,
    audit_id: data.audit.audit_id,
    normalization: "within frozen LLM judge label; each row sums to 100%",
    population: data.grandTotal,
    label_totals: EXPECTED_LABEL_TOTALS,
    bin_totals: Object.fromEntries(BINS.map((bin, index) => [bin, EXPECTED_BIN_TOTALS[index]])),
    input: path.relative(ROOT, INPUT),
    input_sha256: sha256(INPUT),
    audit: path.relative(ROOT, AUDIT),
    audit_sha256: sha256(AUDIT),
    passed_marker: path.relative(ROOT, PASSED),
    passed_marker_sha256: sha256(PASSED),
    outputs: {
      [`${STEM}.svg`]: sha256(svgPath),
      [`${STEM}.png`]: sha256(pngPath),
    },
  };
  fs.writeFileSync(lineagePath, `${JSON.stringify(lineage, null, 2)}\n`, "utf8");
  process.stdout.write(`${JSON.stringify(lineage, null, 2)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exitCode = 1;
});
