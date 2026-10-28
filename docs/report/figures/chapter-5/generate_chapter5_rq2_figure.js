#!/usr/bin/env node

/*
 * Deterministic vector source for Figure 5.3.
 *
 * The program reads only the audited RQ2 backbone-robustness artifact,
 * validates its publication gate and six-effect contract, and writes an
 * editable SVG plus a publication-ready PNG preview. It performs no new
 * statistical estimation.
 */

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const sharp = require("sharp");

const OUT = __dirname;
const ROOT = path.resolve(OUT, "../../../..");
const RQ2 = path.join(ROOT, "artifacts/chapter5-main60-analysis-v1/rq2-backbone-robustness");
const INPUT = path.join(RQ2, "table-5-13-inputs.csv");
const AUDIT = path.join(RQ2, "audit.json");
const PASSED = path.join(RQ2, "RQ2.PASSED");

const W = 2000;
const H = 1125;

const C = {
  bg: "#FEFEFE",
  navy: "#0F2D4E",
  teal: "#0A8C86",
  tealPale: "#DDF3F1",
  violet: "#4D60D6",
  violetPale: "#E8EAFE",
  amber: "#C77D16",
  red: "#C94B49",
  slate: "#60788E",
  border: "#A8BAC9",
  grid: "#DCE4EA",
  white: "#FFFFFF",
};

function fail(message) {
  throw new Error(message);
}

function sha256(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

function esc(value) {
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
    const char = content[index];
    if (quoted) {
      if (char === '"' && content[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') {
        quoted = false;
      } else {
        field += char;
      }
    } else if (char === '"') {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }
  if (field.length || row.length) {
    row.push(field.replace(/\r$/, ""));
    rows.push(row);
  }
  if (!rows.length) return [];
  const header = rows[0];
  return rows.slice(1)
    .filter((values) => values.some((value) => value !== ""))
    .map((values, rowIndex) => {
      if (values.length !== header.length) {
        fail(`CSV row ${rowIndex + 2} has ${values.length} fields; expected ${header.length}`);
      }
      return Object.fromEntries(header.map((name, fieldIndex) => [name, values[fieldIndex]]));
    });
}

function readCsv(filePath) {
  return parseCsv(fs.readFileSync(filePath, "utf8"));
}

function assertClose(actual, expected, label, tolerance = 1e-12) {
  if (!Number.isFinite(actual) || Math.abs(actual - expected) > tolerance) {
    fail(`${label}: expected ${expected}, found ${actual}`);
  }
}

function loadData() {
  if (!fs.existsSync(PASSED)) fail("RQ2 passed marker is missing");
  const audit = JSON.parse(fs.readFileSync(AUDIT, "utf8"));
  if (audit.status !== "passed") fail(`RQ2 audit status is ${audit.status}`);
  if (audit.protocol_version !== "chapter5-main60-rq2-v1") fail(`Unexpected RQ2 protocol ${audit.protocol_version}`);
  if (audit.cross_backbone_statistical_inference_computed !== false) {
    fail("Figure 5.3 requires the frozen descriptive-only RQ2 scope");
  }
  if (!audit.output_sha256 || audit.output_sha256["table-5-13-inputs.csv"] !== sha256(INPUT)) {
    fail("Figure 5.3 input hash does not match the passed RQ2 audit");
  }

  const expected = [
    ["storage_r1_e3_minus_e1", "E3 − E1", "Foldering under R1", "Backbone-dependent", "backbone_dependent"],
    ["storage_r2_e4_minus_e2", "E4 − E2", "Foldering under R2", "Supplementary path-cue", "partly_stable"],
    ["retrieval_s1_e2_minus_e1", "E2 − E1", "R2 vs R1 on S1", "Partly stable", "partly_stable"],
    ["retrieval_s2_e4_minus_e3", "E4 − E3", "R2 vs R1 on S2", "Stable · negative", "stable"],
    ["curated_access_e6_minus_e5", "E6 − E5", "R3 vs R1 on S3", "Stable · negative", "stable"],
    ["curated_vs_foldered_r1_e5_minus_e3", "E5 − E3", "S3+R1 vs S2+R1", "Stable · metric trade-off", "stable"],
  ];
  const rows = readCsv(INPUT);
  if (rows.length !== expected.length) fail(`Figure 5.3 requires 6 rows; found ${rows.length}`);

  const data = rows.map((row, index) => {
    const [comparisonId, code, description, classification, canonicalClass] = expected[index];
    if (row.comparison_order !== String(index + 1)) fail(`Unexpected comparison order at row ${index + 1}`);
    if (row.comparison_id !== comparisonId) fail(`Unexpected comparison at row ${index + 1}`);
    if (row.descriptive_only !== "True") fail(`Comparison ${comparisonId} is not marked descriptive-only`);
    if (row.stability_classification !== canonicalClass) fail(`Unexpected stability class for ${comparisonId}`);

    const values = {
      token_f1: {
        qwen: Number(row.qwen_token_f1_effect),
        deepseek: Number(row.deepseek_token_f1_effect),
      },
      strict_accuracy: {
        qwen: Number(row.qwen_strict_accuracy_effect),
        deepseek: Number(row.deepseek_strict_accuracy_effect),
      },
      soft_semantic_score: {
        qwen: Number(row.qwen_soft_semantic_score_effect),
        deepseek: Number(row.deepseek_soft_semantic_score_effect),
      },
    };
    for (const [metric, pair] of Object.entries(values)) {
      for (const [backbone, value] of Object.entries(pair)) {
        if (!Number.isFinite(value) || value < -1 || value > 1) {
          fail(`Invalid ${metric}/${backbone} value for ${comparisonId}`);
        }
      }
    }
    return { comparisonId, code, description, classification, values };
  });

  assertClose(data[0].values.token_f1.qwen, 0.04621963205152648, "Qwen E3-E1 F1");
  assertClose(data[3].values.strict_accuracy.deepseek, -0.03333333333333333, "DeepSeek E4-E3 Strict");
  assertClose(data[5].values.soft_semantic_score.deepseek, 0.041666666666666664, "DeepSeek E5-E3 Soft");
  return { audit, data };
}

function tspans(lines, x, lineHeight = 1.16) {
  const values = Array.isArray(lines) ? lines : [lines];
  return values.map((value, index) => {
    const dy = index === 0 ? 0 : `${lineHeight}em`;
    return `<tspan x="${x}" dy="${dy}">${esc(value)}</tspan>`;
  }).join("");
}

function text(x, y, lines, options = {}) {
  const {
    size = 22,
    weight = 500,
    fill = C.navy,
    anchor = "middle",
    lineHeight = 1.16,
  } = options;
  return `<text x="${x}" y="${y}" text-anchor="${anchor}" font-family="Arial, Helvetica, sans-serif" font-size="${size}" font-weight="${weight}" fill="${fill}" text-rendering="geometricPrecision">${tspans(lines, x, lineHeight)}</text>`;
}

function rect(x, y, width, height, options = {}) {
  const {
    fill = C.white,
    stroke = C.border,
    strokeWidth = 2,
    radius = 16,
    shadow = false,
  } = options;
  return `<rect x="${x}" y="${y}" width="${width}" height="${height}" rx="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"${shadow ? ' filter="url(#shadow)"' : ""}/>`;
}

function line(x1, y1, x2, y2, options = {}) {
  const { stroke = C.grid, width = 2, dash = "", opacity = 1 } = options;
  return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${width}" stroke-opacity="${opacity}"${dash ? ` stroke-dasharray="${dash}"` : ""} stroke-linecap="round"/>`;
}

function circle(cx, cy, radius, fill, stroke = C.white, strokeWidth = 3) {
  return `<circle cx="${cx}" cy="${cy}" r="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
}

function triangle(cx, cy, size, fill, stroke = C.white, strokeWidth = 3) {
  const height = size * 0.92;
  const points = `${cx},${cy - height / 2} ${cx - size / 2},${cy + height / 2} ${cx + size / 2},${cy + height / 2}`;
  return `<polygon points="${points}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}" stroke-linejoin="round"/>`;
}

function effectLabel(value) {
  const points = value * 100;
  if (Math.abs(points) < 0.05) return "0.0";
  return `${points > 0 ? "+" : "−"}${Math.abs(points).toFixed(1)}`;
}

function figure55(dataset) {
  const metrics = [
    { id: "token_f1", title: "Token F1" },
    { id: "strict_accuracy", title: "Strict Accuracy" },
    { id: "soft_semantic_score", title: "Soft Semantic Score" },
  ];
  const panels = [
    { x: 410, y: 220, width: 490, height: 740 },
    { x: 940, y: 220, width: 490, height: 740 },
    { x: 1470, y: 220, width: 490, height: 740 },
  ];
  const domainMin = -11;
  const domainMax = 6;
  const ticks = [-10, -5, 0, 5];
  const rowYs = [330, 438, 546, 654, 762, 870];

  let svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-labelledby="figure-title figure-desc">
  <title id="figure-title">Cross-Backbone Stability of Architecture Effects</title>
  <desc id="figure-desc">Three aligned panels compare Qwen and DeepSeek target-minus-baseline effects for Token F1, Strict Accuracy, and Soft Semantic Score across six architecture contrasts. A dashed vertical line marks zero effect.</desc>
  <defs>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#0F2D4E" flood-opacity="0.10"/></filter>
  </defs>
  <rect width="${W}" height="${H}" fill="${C.bg}"/>
  ${text(W / 2, 72, "Cross-Backbone Stability of Architecture Effects", { size: 56, weight: 800 })}
  ${text(W / 2, 116, "Mean target-minus-baseline effects in percentage points; paired markers show directional reproduction", { size: 23, weight: 500, fill: C.slate })}
  `;

  svg += circle(675, 166, 9, C.teal);
  svg += text(696, 173, "Qwen", { size: 19, weight: 700, anchor: "start" });
  svg += triangle(865, 166, 22, C.violet);
  svg += text(890, 173, "DeepSeek", { size: 19, weight: 700, anchor: "start" });
  svg += line(1100, 166, 1165, 166, { stroke: C.border, width: 4 });
  svg += text(1185, 173, "paired backbone effects", { size: 19, weight: 600, anchor: "start", fill: C.slate });
  svg += line(1460, 147, 1460, 184, { stroke: C.navy, width: 2.5, dash: "8 6" });
  svg += text(1481, 173, "zero effect", { size: 19, weight: 600, anchor: "start", fill: C.slate });

  svg += text(58, 254, "Architecture contrast", { size: 22, weight: 800, anchor: "start" });
  svg += text(58, 281, "Directional classification", { size: 16, weight: 550, fill: C.slate, anchor: "start" });

  for (let metricIndex = 0; metricIndex < metrics.length; metricIndex += 1) {
    const metric = metrics[metricIndex];
    const panel = panels[metricIndex];
    svg += rect(panel.x, panel.y, panel.width, panel.height, { fill: C.white, stroke: C.border, strokeWidth: 2, radius: 18, shadow: true });
    svg += text(panel.x + panel.width / 2, panel.y + 43, metric.title, { size: 25, weight: 800 });

    const px0 = panel.x + 48;
    const px1 = panel.x + panel.width - 32;
    const py0 = panel.y + 78;
    const py1 = panel.y + panel.height - 66;
    const xScale = (value) => px0 + ((value - domainMin) / (domainMax - domainMin)) * (px1 - px0);

    for (const tick of ticks) {
      const tx = xScale(tick);
      svg += line(tx, py0, tx, py1, {
        stroke: tick === 0 ? C.navy : C.grid,
        width: tick === 0 ? 2.7 : 1.3,
        dash: tick === 0 ? "8 6" : "",
      });
      svg += text(tx, py1 + 31, tick > 0 ? `+${tick}` : `${tick}`, {
        size: 17,
        weight: tick === 0 ? 800 : 500,
        fill: tick === 0 ? C.navy : C.slate,
      });
    }
    svg += text((px0 + px1) / 2, panel.y + panel.height - 18, "Effect (percentage points)", { size: 17, weight: 650, fill: C.slate });

    for (let rowIndex = 0; rowIndex < dataset.length; rowIndex += 1) {
      const item = dataset[rowIndex];
      const rowY = rowYs[rowIndex];
      const qwen = item.values[metric.id].qwen;
      const deepseek = item.values[metric.id].deepseek;
      const qx = xScale(qwen * 100);
      const dx = xScale(deepseek * 100);
      const qy = rowY - 7;
      const dy = rowY + 7;

      svg += line(px0, rowY, px1, rowY, { stroke: C.grid, width: 1.2, opacity: 0.82 });
      svg += line(qx, qy, dx, dy, { stroke: C.slate, width: 4, opacity: 0.58 });
      svg += circle(qx, qy, 9, C.teal);
      svg += triangle(dx, dy, 22, C.violet);

      const qAnchor = qx > px1 - 35 ? "end" : "start";
      const dAnchor = dx > px1 - 35 ? "end" : "start";
      svg += text(qx + (qAnchor === "end" ? -13 : 13), qy - 12, effectLabel(qwen), { size: 16, weight: 800, fill: C.teal, anchor: qAnchor });
      svg += text(dx + (dAnchor === "end" ? -13 : 13), dy + 25, effectLabel(deepseek), { size: 16, weight: 800, fill: C.violet, anchor: dAnchor });
    }
  }

  for (let rowIndex = 0; rowIndex < dataset.length; rowIndex += 1) {
    const item = dataset[rowIndex];
    const rowY = rowYs[rowIndex];
    svg += text(58, rowY - 12, item.code, { size: 21, weight: 800, anchor: "start" });
    svg += text(58, rowY + 13, item.description, { size: 17, weight: 600, fill: C.slate, anchor: "start" });
    svg += text(58, rowY + 38, item.classification, { size: 16, weight: 750, fill: C.slate, anchor: "start" });
  }

  svg += text(W / 2, 1030, "Strict and Soft guide the primary quality interpretation; Token F1 is a lexical diagnostic. Each effect uses N=60.", { size: 19, weight: 650, fill: C.slate });
  svg += text(W / 2, 1061, "Connectors join two within-backbone point estimates; they are not uncertainty intervals or significance tests.", { size: 18, weight: 550, fill: C.slate });
  svg += text(W / 2, 1091, "Directional stability is descriptive across the two tested pipelines and does not imply universal invariance.", { size: 17, weight: 550, fill: C.slate });
  return `${svg}</svg>`;
}

async function main() {
  const { audit, data } = loadData();
  const stem = "figure-5-3-cross-backbone-architecture-stability";
  const svgPath = path.join(OUT, `${stem}.svg`);
  const pngPath = path.join(OUT, `${stem}.png`);
  const svg = figure55(data);
  fs.writeFileSync(svgPath, svg, "utf8");
  await sharp(Buffer.from(svg))
    .resize(W, H, { fit: "fill" })
    .flatten({ background: C.bg })
    .png({ compressionLevel: 9, adaptiveFiltering: true })
    .toFile(pngPath);

  const lineage = {
    generated_at: new Date().toISOString(),
    generator: path.relative(ROOT, __filename),
    rq2_audit_id: audit.audit_id,
    rq2_status: audit.status,
    scope: "descriptive cross-backbone architecture-effect stability",
    source_files: [INPUT, AUDIT, PASSED].map((filePath) => ({
      path: path.relative(ROOT, filePath),
      sha256: sha256(filePath),
    })),
    output_files: [svgPath, pngPath].map((filePath) => ({
      path: path.relative(ROOT, filePath),
      sha256: sha256(filePath),
    })),
  };
  const lineagePath = path.join(OUT, "figure-5-3-data-lineage.json");
  fs.writeFileSync(lineagePath, `${JSON.stringify(lineage, null, 2)}\n`, "utf8");

  const checksumNames = [
    "figure-5-1-storage-retrieval-interaction.svg",
    "figure-5-1-storage-retrieval-interaction.png",
    "figure-5-2-curated-memory-effect-profile.svg",
    "figure-5-2-curated-memory-effect-profile.png",
    "figure-5-3-cross-backbone-architecture-stability.svg",
    "figure-5-3-cross-backbone-architecture-stability.png",
    "data-lineage.json",
    "figure-5-3-data-lineage.json",
    "generate_chapter5_rq1_figures.js",
    "generate_chapter5_rq2_figure.js",
  ];
  const checksums = checksumNames.map((name) => `${sha256(path.join(OUT, name))}  ${name}`).join("\n");
  fs.writeFileSync(path.join(OUT, "SHA256SUMS"), `${checksums}\n`, "utf8");
}

main().catch((error) => {
  console.error(error.stack || error.message || error);
  process.exitCode = 1;
});
