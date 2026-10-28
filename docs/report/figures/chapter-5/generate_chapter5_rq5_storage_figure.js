#!/usr/bin/env node

/*
 * Deterministic vector source for Figure 5.6.
 *
 * The program reads only the passed RQ5 storage-audit table, verifies the
 * audit and PASSED gates, and writes an editable SVG, a PNG preview, and a
 * data-lineage record. It performs no estimation, model call, or network call.
 */

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const sharp = require("sharp");

const OUT = __dirname;
const ROOT = path.resolve(OUT, "../../../..");
const AUDIT_DIR = path.join(ROOT, "artifacts/chapter5-main60-analysis-v1/rq5-storage-audit");
const INPUT = path.join(AUDIT_DIR, "case-storage-linkage.csv");
const AUDIT = path.join(AUDIT_DIR, "audit.json");
const PASSED = path.join(AUDIT_DIR, "RQ5-STORAGE-AUDIT.PASSED");

const STEM = "figure-5-6-selective-error-storage-state";
const LINEAGE = "figure-5-6-data-lineage.json";
const W = 2000;
const H = 1125;

const C = {
  background: "#FEFEFE",
  navy: "#0F2D4E",
  slate: "#60788E",
  grid: "#DCE4EA",
  border: "#A8BAC9",
  teal: "#0A8C86",
  tealPale: "#DDF3F1",
  amber: "#F2B44B",
  violet: "#4D60D6",
  red: "#D95A5A",
  noAnnotation: "#A8BAC9",
  white: "#FFFFFF",
  pale: "#F5F8FA",
};

const STATES = [
  { key: "available", label: "Unambiguously available", short: "Available", color: C.teal, text: C.white },
  { key: "partial", label: "Partial support", short: "Partial", color: C.amber, text: C.navy },
  { key: "mismatch", label: "Source/reference mismatch", short: "Mismatch", color: C.violet, text: C.white },
  { key: "conflict", label: "Source conflict", short: "Conflict", color: C.red, text: C.white },
  { key: "no_annotation", label: "No official annotation", short: "No annotation", color: C.noAnnotation, text: C.navy },
];

const STORE_LABELS = {
  S1: ["S1", "Flat Raw Sessions"],
  S2: ["S2", "Foldered Raw Sessions"],
  S3: ["S3", "Agent-Curated Memory"],
  ALL: ["All selective paths", "E1–E6 aggregate"],
};

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

function stateKey(row) {
  const mapping = {
    available: "available",
    partial: "partial",
    available_with_reference_entity_mismatch: "mismatch",
    available_but_conflicting: "conflict",
    indeterminate: "no_annotation",
  };
  const key = mapping[row.store_availability_state];
  if (!key) fail(`Unexpected storage state: ${row.store_availability_state}`);
  if (key === "no_annotation" && row.evidence_eligible !== "False") {
    fail("Indeterminate storage state must correspond to a question without official evidence locators");
  }
  return key;
}

function loadData() {
  for (const required of [INPUT, AUDIT, PASSED]) {
    if (!fs.existsSync(required)) fail(`Missing required input: ${path.relative(ROOT, required)}`);
  }
  const audit = JSON.parse(fs.readFileSync(AUDIT, "utf8"));
  const passed = JSON.parse(fs.readFileSync(PASSED, "utf8"));
  if (audit.status !== "passed" || passed.status !== "passed") fail("The storage audit must be passed");
  if (audit.protocol_version !== "chapter5-main60-rq5-storage-audit-v1") fail("Unexpected protocol version");
  if (passed.protocol_version !== audit.protocol_version || passed.audit_id !== audit.audit_id) {
    fail("PASSED marker does not identify the audited storage run");
  }
  if (passed.audit_sha256 !== sha256(AUDIT)) fail("PASSED marker audit hash does not match audit.json");
  if (audit.output_sha256?.["case-storage-linkage.csv"] !== sha256(INPUT)) {
    fail("Input table hash does not match the passed audit");
  }
  if (audit.store_specific_decisive_losses !== 0) fail("Expected zero verified store-specific decisive losses");

  const rows = parseCsv(fs.readFileSync(INPUT, "utf8"));
  if (rows.length !== 205) fail(`Expected 205 selective error paths; found ${rows.length}`);
  const counts = {};
  for (const store of ["S1", "S2", "S3", "ALL"]) {
    counts[store] = Object.fromEntries(STATES.map((state) => [state.key, 0]));
  }
  for (const row of rows) {
    if (row.protocol_version !== audit.protocol_version) fail("Row protocol version differs from the audit");
    if (!["S1", "S2", "S3"].includes(row.store_id)) fail(`Unexpected store: ${row.store_id}`);
    if (!new Set(["partial", "incorrect"]).has(row.judge_label)) fail("Input contains a Strict-correct path");
    const key = stateKey(row);
    counts[row.store_id][key] += 1;
    counts.ALL[key] += 1;
  }

  const expected = {
    S1: { available: 41, partial: 14, mismatch: 10, conflict: 0, no_annotation: 5 },
    S2: { available: 41, partial: 15, mismatch: 10, conflict: 0, no_annotation: 5 },
    S3: { available: 37, partial: 16, mismatch: 6, conflict: 1, no_annotation: 4 },
    ALL: { available: 119, partial: 45, mismatch: 26, conflict: 1, no_annotation: 14 },
  };
  for (const store of Object.keys(expected)) {
    for (const state of STATES) {
      if (counts[store][state.key] !== expected[store][state.key]) {
        fail(`Count mismatch for ${store}/${state.key}`);
      }
    }
  }
  return { audit, passed, rows, counts };
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
    shadow = false,
  } = options;
  return `<rect x="${x}" y="${y}" width="${width}" height="${height}" rx="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"${shadow ? ' filter="url(#shadow)"' : ""}/>`;
}

function totalFor(counts) {
  return STATES.reduce((sum, state) => sum + counts[state.key], 0);
}

function percentage(count, total) {
  return 100 * count / total;
}

function buildSvg(data) {
  const parts = [];
  parts.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`);
  parts.push(`<defs><filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="6" stdDeviation="10" flood-color="#0F2D4E" flood-opacity="0.12"/></filter></defs>`);
  parts.push(rect(0, 0, W, H, { fill: C.background }));

  parts.push(text(W / 2, 82, "Stored Support in Selective-Path Errors", { size: 58, weight: 700 }));
  parts.push(text(W / 2, 132, "205 E1–E6 Strict-noncorrect answer paths; storage labels were fixed before outcome linkage", { size: 27, fill: C.slate }));

  const legendY = 205;
  const legend = [
    { x: 150, state: STATES[0] },
    { x: 520, state: STATES[1] },
    { x: 850, state: STATES[2] },
    { x: 1300, state: STATES[3] },
    { x: 1560, state: STATES[4] },
  ];
  for (const item of legend) {
    parts.push(rect(item.x, legendY - 19, 28, 28, { fill: item.state.color, radius: 5 }));
    parts.push(text(item.x + 42, legendY + 4, item.state.label, { size: 21, anchor: "start", weight: 600 }));
  }

  const chartX = 440;
  const chartWidth = 1390;
  const barHeight = 74;
  const rows = [
    { store: "S1", y: 302 },
    { store: "S2", y: 437 },
    { store: "S3", y: 572 },
    { store: "ALL", y: 735 },
  ];

  for (const tick of [0, 25, 50, 75, 100]) {
    const x = chartX + chartWidth * tick / 100;
    parts.push(`<line x1="${x}" y1="270" x2="${x}" y2="830" stroke="${tick === 50 ? C.slate : C.grid}" stroke-width="${tick === 50 ? 2.5 : 1.5}" ${tick === 50 ? 'stroke-dasharray="8 8"' : ""}/>`);
    parts.push(text(x, 260, `${tick}%`, { size: 18, fill: C.slate }));
  }

  for (const row of rows) {
    const counts = data.counts[row.store];
    const total = totalFor(counts);
    const [primary, secondary] = STORE_LABELS[row.store];
    const centerY = row.y + barHeight / 2;
    parts.push(text(395, centerY - 6, primary, { size: row.store === "ALL" ? 28 : 31, weight: 700, anchor: "end" }));
    parts.push(text(395, centerY + 24, `${secondary} · n=${total}`, { size: 19, fill: C.slate, anchor: "end", weight: 500 }));

    let currentX = chartX;
    const boundaries = [];
    for (const state of STATES) {
      const count = counts[state.key];
      if (count === 0) continue;
      const segmentWidth = chartWidth * count / total;
      parts.push(rect(currentX, row.y, segmentWidth, barHeight, {
        fill: state.color,
        stroke: C.white,
        strokeWidth: 2,
        radius: 0,
      }));
      const pct = percentage(count, total);
      if (segmentWidth >= 86) {
        const digits = row.store === "ALL" && state.key === "available" ? 2 : 1;
        const label = segmentWidth >= 145 ? `${count} · ${pct.toFixed(digits)}%` : `${count}`;
        parts.push(text(currentX + segmentWidth / 2, centerY + 8, label, {
          size: segmentWidth >= 145 ? 21 : 19,
          weight: 700,
          fill: state.text,
        }));
      } else {
        boundaries.push({ x: currentX + segmentWidth / 2, count, color: state.color });
      }
      currentX += segmentWidth;
    }
    if (row.store === "ALL") {
      parts.push(rect(chartX - 2, row.y - 2, chartWidth + 4, barHeight + 4, {
        fill: "none",
        stroke: C.navy,
        strokeWidth: 4,
        radius: 4,
      }));
    }
    boundaries.forEach((callout, index) => {
      const calloutY = row.y - 13 - index * 24;
      parts.push(`<line x1="${callout.x}" y1="${row.y}" x2="${callout.x}" y2="${calloutY + 5}" stroke="${callout.color}" stroke-width="2"/>`);
      parts.push(text(callout.x, calloutY, String(callout.count), { size: 18, weight: 700, fill: callout.color }));
    });
  }

  parts.push(rect(300, 875, 1400, 135, { fill: C.tealPale, stroke: C.teal, strokeWidth: 2.5, radius: 24, shadow: true }));
  parts.push(text(525, 934, "119 / 205", { size: 48, weight: 700, fill: C.teal }));
  parts.push(text(780, 933, "(58.05%)", { size: 34, weight: 700, fill: C.navy }));
  parts.push(text(1035, 929, "Strict-noncorrect paths retained", { size: 28, weight: 600, anchor: "start" }));
  parts.push(text(1035, 965, "unambiguously available support", { size: 28, weight: 600, anchor: "start" }));
  parts.push(text(W / 2, 997, "Verified store-specific decisive omissions: 0", { size: 21, weight: 700, fill: C.slate }));

  parts.push(text(W / 2, 1063, "Counts are answer paths, not independent questions or storage defects; “no official annotation” is not a verified omission.", { size: 19, fill: C.slate }));
  parts.push(text(W / 2, 1092, "Availability alone does not identify whether the later break occurred in retrieval, packaging, or Answerer utilisation.", { size: 19, fill: C.slate }));
  parts.push(`</svg>`);
  return parts.join("\n");
}

async function main() {
  const data = loadData();
  const svg = buildSvg(data);
  const svgPath = path.join(OUT, `${STEM}.svg`);
  const pngPath = path.join(OUT, `${STEM}.png`);
  fs.writeFileSync(svgPath, svg);
  await sharp(Buffer.from(svg)).png({ compressionLevel: 9 }).toFile(pngPath);

  const lineage = {
    figure_id: "Figure 5.6",
    title: "Stored Support in Selective-Path Errors",
    protocol_version: data.audit.protocol_version,
    audit_id: data.audit.audit_id,
    source: path.relative(ROOT, INPUT),
    source_sha256: sha256(INPUT),
    answer_path_denominator: data.rows.length,
    counts: data.counts,
    store_specific_decisive_losses: data.audit.store_specific_decisive_losses,
    output_sha256: {
      [`${STEM}.svg`]: sha256(svgPath),
      [`${STEM}.png`]: sha256(pngPath),
    },
    inserted_into_report: true,
  };
  fs.writeFileSync(path.join(OUT, LINEAGE), `${JSON.stringify(lineage, null, 2)}\n`);
  process.stdout.write(`${svgPath}\n${pngPath}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exitCode = 1;
});
