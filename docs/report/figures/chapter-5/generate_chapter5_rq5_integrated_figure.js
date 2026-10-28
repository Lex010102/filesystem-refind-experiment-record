#!/usr/bin/env node

/*
 * Deterministic vector source for Figure 5.9.
 *
 * The generator reads the passed RQ5 integrated-attribution summary, verifies
 * the audit and PASSED marker, and writes an editable SVG, a PNG preview, and
 * a data-lineage record. It performs no estimation, model call, or network
 * call.
 */

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const sharp = require("sharp");

const OUT = __dirname;
const ROOT = path.resolve(OUT, "../../../..");
const AUDIT_DIR = path.join(ROOT, "artifacts/chapter5-main60-analysis-v1/rq5-integrated-bottleneck");
const INPUT = path.join(AUDIT_DIR, "primary-root-cause-summary.csv");
const AUDIT = path.join(AUDIT_DIR, "audit.json");
const PASSED = path.join(AUDIT_DIR, "RQ5-INTEGRATED.PASSED");

const STEM = "figure-5-9-integrated-bottleneck-decomposition";
const LINEAGE = "figure-5-9-data-lineage.json";
const W = 2000;
const H = 1125;

const C = {
  background: "#FEFEFE",
  navy: "#0F2D4E",
  slate: "#60788E",
  border: "#A8BAC9",
  grid: "#DCE4EA",
  pale: "#F5F8FA",
  white: "#FFFFFF",
  teal: "#0A8C86",
  amber: "#F2B44B",
  violet: "#4D60D6",
  red: "#D95A5A",
  blue: "#4C90B8",
  mixed: "#A8BAC9",
  storage: "#DCE4EA",
  tealPale: "#DDF3F1",
};

const STAGES = [
  { key: "mixed_or_indeterminate", label: "Mixed / indeterminate", color: C.mixed },
  { key: "answerer", label: "Answerer utilisation", color: C.teal },
  { key: "evaluation_sensitive", label: "Evaluation-sensitive", color: C.blue },
  { key: "retrieval", label: "Retrieval", color: C.amber },
  { key: "packaging", label: "Packaging / budget", color: C.violet },
  { key: "fusion_or_long_context", label: "Fusion / long context", color: C.red },
  { key: "storage", label: "Storage", color: C.storage },
];

const INTERNAL_STAGES = [
  { key: "answerer", label: "Answerer utilisation", color: C.teal },
  { key: "retrieval", label: "Retrieval", color: C.amber },
  { key: "packaging", label: "Packaging / budget", color: C.violet },
  { key: "fusion_or_long_context", label: "Long context", color: C.red },
  { key: "storage", label: "Storage", color: C.storage },
];

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
  if (audit.status !== "passed" || passed.status !== "passed") fail("The integrated RQ5 audit must be passed");
  if (audit.protocol_version !== "chapter5-main60-rq5-integrated-v1") fail("Unexpected protocol version");
  if (passed.protocol_version !== audit.protocol_version || passed.audit_id !== audit.audit_id) {
    fail("PASSED marker does not identify the audited integrated run");
  }
  if (passed.audit_sha256 !== sha256(AUDIT)) fail("PASSED marker audit hash does not match audit.json");
  if (audit.output_sha256?.["primary-root-cause-summary.csv"] !== sha256(INPUT)) {
    fail("Input table hash does not match the passed audit");
  }

  const rows = parseCsv(fs.readFileSync(INPUT, "utf8"));
  const overallRows = rows.filter((row) => row.scope_type === "overall" && row.scope_value === "ALL");
  if (overallRows.length !== 7) fail(`Expected seven overall primary stages; found ${overallRows.length}`);

  const counts = {};
  for (const row of overallRows) {
    if (row.protocol_version !== audit.protocol_version) fail("Row protocol version differs from the audit");
    if (Number(row.denominator) !== 250) fail("Unexpected overall denominator");
    counts[row.primary_stage] = Number(row.count);
  }
  for (const stage of STAGES) {
    if (!Number.isInteger(counts[stage.key])) fail(`Missing or invalid count for ${stage.key}`);
  }

  const expected = {
    storage: 0,
    retrieval: 42,
    packaging: 7,
    answerer: 68,
    fusion_or_long_context: 6,
    evaluation_sensitive: 53,
    mixed_or_indeterminate: 74,
  };
  for (const [key, value] of Object.entries(expected)) {
    if (counts[key] !== value) fail(`Count mismatch for ${key}: expected ${value}; found ${counts[key]}`);
  }
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
  if (total !== audit.diagnostics.population_rows || total !== 250) fail("Primary-stage counts do not sum to 250");

  const internalCounts = Object.fromEntries(INTERNAL_STAGES.map((stage) => [stage.key, counts[stage.key]]));
  const internalTotal = Object.values(internalCounts).reduce((sum, value) => sum + value, 0);
  if (internalTotal !== 123) fail(`Expected 123 confirmed system-internal paths; found ${internalTotal}`);
  return { audit, passed, rows, counts, total, internalCounts, internalTotal };
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

function polar(cx, cy, radius, angle) {
  return {
    x: cx + radius * Math.cos(angle),
    y: cy + radius * Math.sin(angle),
  };
}

function donutSegment(cx, cy, outerRadius, innerRadius, startAngle, endAngle, color) {
  const outerStart = polar(cx, cy, outerRadius, startAngle);
  const outerEnd = polar(cx, cy, outerRadius, endAngle);
  const innerEnd = polar(cx, cy, innerRadius, endAngle);
  const innerStart = polar(cx, cy, innerRadius, startAngle);
  const largeArc = endAngle - startAngle > Math.PI ? 1 : 0;
  return `<path d="M ${outerStart.x.toFixed(3)} ${outerStart.y.toFixed(3)} A ${outerRadius} ${outerRadius} 0 ${largeArc} 1 ${outerEnd.x.toFixed(3)} ${outerEnd.y.toFixed(3)} L ${innerEnd.x.toFixed(3)} ${innerEnd.y.toFixed(3)} A ${innerRadius} ${innerRadius} 0 ${largeArc} 0 ${innerStart.x.toFixed(3)} ${innerStart.y.toFixed(3)} Z" fill="${color}" stroke="${C.white}" stroke-width="5"/>`;
}

function percentage(count, total) {
  return 100 * count / total;
}

function buildSvg(data) {
  const parts = [];
  parts.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`);
  parts.push("<title>Integrated Bottleneck Decomposition</title>");
  parts.push("<desc>A donut chart shows mutually exclusive primary attribution for 250 non-Correct answer paths. A horizontal bar chart shows the 123 resolved system-internal failures.</desc>");
  parts.push(`<defs><filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="6" stdDeviation="10" flood-color="#0F2D4E" flood-opacity="0.12"/></filter></defs>`);
  parts.push(rect(0, 0, W, H, { fill: C.background }));

  parts.push(text(W / 2, 78, "Integrated Bottleneck Decomposition", { size: 58, weight: 700 }));
  parts.push(text(W / 2, 130, "Primary attribution of the 250 answer paths not labelled Correct", { size: 27, fill: C.slate }));

  const left = { x: 55, y: 180, width: 925, height: 815 };
  const right = { x: 1020, y: 180, width: 925, height: 815 };
  parts.push(rect(left.x, left.y, left.width, left.height, { fill: C.pale, stroke: C.border, strokeWidth: 2.5, radius: 28, shadow: true }));
  parts.push(rect(right.x, right.y, right.width, right.height, { fill: C.pale, stroke: C.border, strokeWidth: 2.5, radius: 28, shadow: true }));

  parts.push(text(left.x + left.width / 2, 235, "All non-Correct paths", { size: 34, weight: 700 }));
  parts.push(text(left.x + left.width / 2, 274, "Mutually exclusive primary attribution · n = 250", { size: 21, fill: C.slate }));

  const cx = 285;
  const cy = 595;
  const outerRadius = 225;
  const innerRadius = 126;
  let angle = -Math.PI / 2;
  for (const stage of STAGES) {
    const count = data.counts[stage.key];
    if (count === 0) continue;
    const nextAngle = angle + 2 * Math.PI * count / data.total;
    parts.push(donutSegment(cx, cy, outerRadius, innerRadius, angle, nextAngle, stage.color));
    angle = nextAngle;
  }
  parts.push(text(cx, cy - 5, "250", { size: 55, weight: 700 }));
  parts.push(text(cx, cy + 37, "non-Correct", { size: 22, weight: 600, fill: C.slate }));
  parts.push(text(cx, cy + 66, "answer paths", { size: 22, weight: 600, fill: C.slate }));

  const legendX = 565;
  const legendValueX = 950;
  const legendStartY = 382;
  const legendGap = 83;
  STAGES.forEach((stage, index) => {
    const y = legendStartY + index * legendGap;
    const count = data.counts[stage.key];
    parts.push(`<circle cx="${legendX}" cy="${y - 8}" r="13" fill="${stage.color}" stroke="${stage.key === "storage" ? C.border : C.white}" stroke-width="2"/>`);
    parts.push(text(legendX + 28, y, stage.label, { size: 20, weight: 600, anchor: "start" }));
    parts.push(text(legendValueX, y, `${count} (${percentage(count, data.total).toFixed(1)}%)`, { size: 20, weight: 700, anchor: "end", fill: stage.key === "storage" ? C.slate : C.navy }));
  });

  parts.push(text(right.x + right.width / 2, 235, "Confirmed system-internal failures", { size: 34, weight: 700 }));
  parts.push(text(right.x + right.width / 2, 274, "Evaluation-sensitive and Mixed/Indeterminate excluded · n = 123", { size: 21, fill: C.slate }));

  const chartX = 1320;
  const chartWidth = 500;
  const chartTop = 355;
  const chartBottom = 880;
  const axisMax = 60;
  for (const tick of [0, 20, 40, 60]) {
    const x = chartX + chartWidth * tick / axisMax;
    parts.push(`<line x1="${x}" y1="${chartTop - 25}" x2="${x}" y2="${chartBottom + 18}" stroke="${C.grid}" stroke-width="2"/>`);
    parts.push(text(x, chartBottom + 52, `${tick}%`, { size: 18, fill: C.slate }));
  }

  const rowYs = [375, 500, 625, 750, 875];
  INTERNAL_STAGES.forEach((stage, index) => {
    const count = data.internalCounts[stage.key];
    const share = percentage(count, data.internalTotal);
    const y = rowYs[index];
    const width = chartWidth * share / axisMax;
    parts.push(text(1080, y + 20, stage.label, { size: 22, weight: 650, anchor: "start" }));
    parts.push(rect(chartX, y - 12, chartWidth, 60, { fill: C.white, stroke: C.grid, strokeWidth: 1.5, radius: 10 }));
    if (width > 0) {
      parts.push(rect(chartX, y - 12, width, 60, { fill: stage.color, radius: 10 }));
    }
    const valueX = count === 0 ? chartX + 14 : Math.min(chartX + width + 16, right.x + right.width - 20);
    parts.push(text(valueX, y + 27, `${count} (${share.toFixed(1)}%)`, {
      size: 21,
      weight: 700,
      anchor: "start",
      fill: count === 0 ? C.slate : C.navy,
    }));
  });
  parts.push(text(chartX + chartWidth / 2, 958, "Share within the 123 confirmed system-internal failures", { size: 19, fill: C.slate }));

  parts.push(rect(300, 1023, 1400, 64, { fill: C.tealPale, stroke: C.teal, strokeWidth: 2.2, radius: 20 }));
  parts.push(text(W / 2, 1064, "Different denominators: the left panel includes Evaluation-sensitive and Mixed/Indeterminate paths; the right panel does not.", { size: 21, weight: 600 }));
  parts.push(text(W / 2, 1110, "Counts describe the composition of observed non-Correct paths, not condition-level error rates.", { size: 18, fill: C.slate }));
  parts.push("</svg>");
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
    figure_id: "Figure 5.9",
    title: "Integrated Bottleneck Decomposition",
    protocol_version: data.audit.protocol_version,
    audit_id: data.audit.audit_id,
    source: path.relative(ROOT, INPUT),
    source_sha256: sha256(INPUT),
    population: {
      all_non_correct_paths: data.total,
      confirmed_system_internal_paths: data.internalTotal,
    },
    primary_counts: data.counts,
    confirmed_system_internal_counts: data.internalCounts,
    denominator_note: "The two panels use different denominators. Evaluation-sensitive and mixed-or-indeterminate paths are excluded from the right panel.",
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
