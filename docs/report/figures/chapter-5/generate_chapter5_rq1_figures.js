#!/usr/bin/env node

/*
 * Deterministic vector source for the Chapter 5 RQ1 figures.
 *
 * The program reads only the audited Stage-E RQ1 artifacts, validates their
 * expected shape and denominators, and writes editable SVG plus publication-
 * ready PNG previews. It deliberately performs no new statistical analysis.
 */

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const sharp = require("sharp");

const OUT = __dirname;
const ROOT = path.resolve(OUT, "../../../..");
const STAGE_E = path.join(ROOT, "artifacts/chapter5-main60-analysis-v1/stage-e-rq1");
const FIG53_INPUT = path.join(STAGE_E, "figure-5-3-inputs.csv");
const FIG54_INPUT = path.join(STAGE_E, "architecture-effects.csv");
const AUDIT = path.join(STAGE_E, "audit.json");
const PASSED = path.join(STAGE_E, "STAGE-E-RQ1.PASSED");

const W = 2000;
const H = 1125;

const C = {
  bg: "#FEFEFE",
  navy: "#0F2D4E",
  navy2: "#173E67",
  teal: "#0A8C86",
  teal2: "#2D9D96",
  tealPale: "#DDF3F1",
  violet: "#4D60D6",
  violetPale: "#E8EAFE",
  amber: "#DA902D",
  red: "#D84A49",
  redPale: "#FBE3E3",
  slate: "#60788E",
  border: "#A8BAC9",
  grid: "#DCE4EA",
  card: "#F7F9FB",
  card2: "#E9F0F5",
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

  for (let i = 0; i < content.length; i += 1) {
    const char = content[i];
    if (quoted) {
      if (char === '"' && content[i + 1] === '"') {
        field += '"';
        i += 1;
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
  return rows.slice(1).filter((values) => values.some((value) => value !== "")).map((values, rowIndex) => {
    if (values.length !== header.length) fail(`CSV row ${rowIndex + 2} has ${values.length} fields; expected ${header.length}`);
    return Object.fromEntries(header.map((name, index) => [name, values[index]]));
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

function validateGate() {
  if (!fs.existsSync(PASSED)) fail("Stage-E passed marker is missing");
  const audit = JSON.parse(fs.readFileSync(AUDIT, "utf8"));
  if (audit.status !== "passed") fail(`Stage-E audit status is ${audit.status}`);
  return audit;
}

function loadFigure53() {
  const rows = readCsv(FIG53_INPUT);
  const backbones = ["qwen", "deepseek"];
  const conditions = ["E1", "E2", "E3", "E4"];
  const metrics = ["token_f1", "strict_accuracy", "soft_semantic_score", "evidence_recall"];
  if (rows.length !== 32) fail(`Figure 5.1 requires 32 rows; found ${rows.length}`);

  const expectedMap = {
    E1: ["S1", "R1"],
    E2: ["S1", "R2"],
    E3: ["S2", "R1"],
    E4: ["S2", "R2"],
  };
  const index = new Map();
  for (const row of rows) {
    const key = `${row.backbone_id}|${row.condition_id}|${row.metric_id}`;
    if (index.has(key)) fail(`Duplicate Figure 5.1 key ${key}`);
    if (!backbones.includes(row.backbone_id)) fail(`Unexpected backbone ${row.backbone_id}`);
    if (!conditions.includes(row.condition_id)) fail(`Unexpected condition ${row.condition_id}`);
    if (!metrics.includes(row.metric_id)) fail(`Unexpected metric ${row.metric_id}`);
    const [storage, retrieval] = expectedMap[row.condition_id];
    if (row.storage_representation !== storage || row.retrieval_system !== retrieval) {
      fail(`Invalid E1–E4 mapping for ${row.condition_id}`);
    }
    const denominator = Number(row.denominator);
    const expectedDenominator = row.metric_id === "evidence_recall" ? 58 : 60;
    if (denominator !== expectedDenominator) fail(`Invalid denominator for ${key}`);
    const mean = Number(row.mean);
    if (!(mean >= 0 && mean <= 1)) fail(`Out-of-range mean for ${key}`);
    index.set(key, mean);
  }
  for (const backbone of backbones) {
    for (const condition of conditions) {
      for (const metric of metrics) {
        if (!index.has(`${backbone}|${condition}|${metric}`)) fail(`Missing ${backbone}/${condition}/${metric}`);
      }
    }
  }
  return { rows, index };
}

function loadFigure54() {
  const rows = readCsv(FIG54_INPUT);
  const selected = rows.filter((row) => [
    "curated_vs_foldered_r1_e5_minus_e3",
    "curated_access_e6_minus_e5",
    "curated_adapted_vs_foldered_raw_e6_minus_e4",
  ].includes(row.comparison_id));
  if (selected.length !== 6) fail(`Figure 5.2 requires 6 architecture-effect rows; found ${selected.length}`);
  const expected = new Set([
    "qwen|curated_vs_foldered_r1_e5_minus_e3",
    "deepseek|curated_vs_foldered_r1_e5_minus_e3",
    "qwen|curated_access_e6_minus_e5",
    "deepseek|curated_access_e6_minus_e5",
    "qwen|curated_adapted_vs_foldered_raw_e6_minus_e4",
    "deepseek|curated_adapted_vs_foldered_raw_e6_minus_e4",
  ]);
  const index = new Map();
  for (const row of selected) {
    const key = `${row.backbone_id}|${row.comparison_id}`;
    if (!expected.has(key)) fail(`Unexpected Figure 5.2 key ${key}`);
    if (index.has(key)) fail(`Duplicate Figure 5.2 key ${key}`);
    if (row.answer_denominator !== "60" || row.evidence_denominator !== "58") fail(`Invalid denominator for ${key}`);
    if (row.bootstrap_available !== "False" || row.bootstrap_status !== "not_predeclared_for_this_effect") {
      fail(`Unexpected bootstrap status for ${key}`);
    }
    const values = {
      token_f1: Number(row.delta_token_f1),
      strict_accuracy: Number(row.delta_strict_accuracy),
      soft_semantic_score: Number(row.delta_soft_semantic_score),
      evidence_recall: Number(row.delta_evidence_recall),
    };
    for (const [metric, value] of Object.entries(values)) {
      if (!Number.isFinite(value) || value < -1 || value > 1) fail(`Invalid ${metric} for ${key}`);
    }
    index.set(key, values);
  }
  for (const key of expected) if (!index.has(key)) fail(`Missing Figure 5.2 key ${key}`);

  // Frozen anchors protect the figure against silent direction or field drift.
  assertClose(index.get("qwen|curated_vs_foldered_r1_e5_minus_e3").token_f1, -0.046328504120277225, "Qwen E5-E3 F1");
  assertClose(index.get("deepseek|curated_access_e6_minus_e5").evidence_recall, -0.23706896551724138, "DeepSeek E6-E5 ER");
  assertClose(index.get("qwen|curated_adapted_vs_foldered_raw_e6_minus_e4").soft_semantic_score, 0.03333333333333333, "Qwen E6-E4 Soft");
  return { rows: selected, index };
}

function tspans(lines, x, lineHeight = 1.16) {
  const values = Array.isArray(lines) ? lines : [lines];
  return values.map((line, index) => {
    const dy = index === 0 ? 0 : `${lineHeight}em`;
    return `<tspan x="${x}" dy="${dy}">${esc(line)}</tspan>`;
  }).join("");
}

function text(x, y, lines, options = {}) {
  const {
    size = 22,
    weight = 500,
    fill = C.navy,
    anchor = "middle",
    lineHeight = 1.16,
    rotate = 0,
    italic = false,
  } = options;
  const transform = rotate ? ` transform="rotate(${rotate} ${x} ${y})"` : "";
  return `<text x="${x}" y="${y}" text-anchor="${anchor}" font-family="Arial, Helvetica, sans-serif" font-size="${size}" font-weight="${weight}" fill="${fill}" font-style="${italic ? "italic" : "normal"}" text-rendering="geometricPrecision"${transform}>${tspans(lines, x, lineHeight)}</text>`;
}

function rect(x, y, w, h, options = {}) {
  const {
    fill = C.white,
    stroke = C.border,
    strokeWidth = 2,
    radius = 16,
    opacity = 1,
    shadow = false,
  } = options;
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${radius}" fill="${fill}" fill-opacity="${opacity}" stroke="${stroke}" stroke-width="${strokeWidth}"${shadow ? ' filter="url(#shadow)"' : ""}/>`;
}

function line(x1, y1, x2, y2, options = {}) {
  const {
    stroke = C.grid,
    width = 2,
    dash = "",
    opacity = 1,
  } = options;
  return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${width}" stroke-opacity="${opacity}"${dash ? ` stroke-dasharray="${dash}"` : ""} stroke-linecap="round"/>`;
}

function circle(cx, cy, r, fill, stroke = C.white, strokeWidth = 3) {
  return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
}

function square(cx, cy, size, fill, stroke = C.white, strokeWidth = 3) {
  return `<rect x="${cx - size / 2}" y="${cy - size / 2}" width="${size}" height="${size}" rx="3" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
}

function triangle(cx, cy, size, fill, stroke = C.white, strokeWidth = 3) {
  const h = size * 0.92;
  const points = `${cx},${cy - h / 2} ${cx - size / 2},${cy + h / 2} ${cx + size / 2},${cy + h / 2}`;
  return `<polygon points="${points}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}" stroke-linejoin="round"/>`;
}

function base(title, subtitle) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
  <defs>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#0F2D4E" flood-opacity="0.10"/></filter>
  </defs>
  <rect width="${W}" height="${H}" fill="${C.bg}"/>
  ${text(W / 2, 72, title, { size: 56, weight: 800 })}
  ${text(W / 2, 116, subtitle, { size: 23, weight: 500, fill: C.slate })}
`;
}

function valueLabel(value) {
  return Number(value).toFixed(3).replace(/^0/, "");
}

function niceTicks(min, max, count) {
  return Array.from({ length: count }, (_, index) => min + ((max - min) * index) / (count - 1));
}

function figure53(data) {
  const metricSpecs = [
    { id: "token_f1", title: "Token F1", min: 0.20, max: 0.46, n: 60 },
    { id: "strict_accuracy", title: "Strict Accuracy", min: 0.64, max: 0.77, n: 60 },
    { id: "soft_semantic_score", title: "Soft Semantic Score", min: 0.68, max: 0.82, n: 60 },
    { id: "evidence_recall", title: "Evidence Recall", min: 0.74, max: 0.90, n: 58 },
  ];
  const backbones = [
    { id: "qwen", label: "Qwen" },
    { id: "deepseek", label: "DeepSeek" },
  ];
  const colX = [125, 590, 1055, 1520];
  const rowY = [220, 615];
  const panelW = 420;
  const panelH = 330;

  let svg = base(
    "Storage–Retrieval Interaction across Backbones",
    "Condition means for E1–E4; simple effects: Tables 5.3–5.6; DID: Table 5.8",
  );

  // One global legend; line style and marker shape duplicate the colour encoding.
  svg += line(710, 166, 790, 166, { stroke: C.teal, width: 5 });
  svg += circle(750, 166, 9, C.teal);
  svg += text(812, 173, "R1 · Agentic Filesystem Retrieval", { size: 19, weight: 700, anchor: "start" });
  svg += line(1165, 166, 1245, 166, { stroke: C.violet, width: 5, dash: "12 8" });
  svg += square(1205, 166, 18, C.violet);
  svg += text(1267, 173, "R2 · ReFind-Style Retrieval", { size: 19, weight: 700, anchor: "start" });

  for (let rowIndex = 0; rowIndex < backbones.length; rowIndex += 1) {
    const backbone = backbones[rowIndex];
    const y = rowY[rowIndex];
    svg += rect(12, y + 122, 105, 64, { fill: rowIndex === 0 ? C.tealPale : C.violetPale, stroke: rowIndex === 0 ? C.teal : C.violet, strokeWidth: 2, radius: 18 });
    svg += text(64.5, y + 162, backbone.label, { size: 18, weight: 800 });

    for (let colIndex = 0; colIndex < metricSpecs.length; colIndex += 1) {
      const metric = metricSpecs[colIndex];
      const x = colX[colIndex];
      svg += rect(x, y, panelW, panelH, { fill: C.white, stroke: C.border, strokeWidth: 2, radius: 18, shadow: true });
      svg += text(x + panelW / 2, y + 38, metric.title, { size: 25, weight: 800 });
      svg += text(x + panelW / 2, y + 63, `Condition mean · N=${metric.n}`, { size: 16, weight: 500, fill: C.slate });

      const px0 = x + 74;
      const px1 = x + panelW - 34;
      const py0 = y + 82;
      const py1 = y + panelH - 58;
      const xPositions = [px0 + 68, px1 - 68];
      const yScale = (value) => py1 - ((value - metric.min) / (metric.max - metric.min)) * (py1 - py0);
      const ticks = niceTicks(metric.min, metric.max, 4);

      for (const tick of ticks) {
        const ty = yScale(tick);
        svg += line(px0, ty, px1, ty, { stroke: C.grid, width: 1.5 });
        svg += text(px0 - 12, ty + 6, tick.toFixed(2), { size: 17, weight: 500, fill: C.slate, anchor: "end" });
      }
      svg += line(px0, py0, px0, py1, { stroke: C.navy, width: 2 });
      svg += line(px0, py1, px1, py1, { stroke: C.navy, width: 2 });
      svg += text(xPositions[0], py1 + 30, ["S1", "flat"], { size: 18, weight: 700, lineHeight: 1.02 });
      svg += text(xPositions[1], py1 + 30, ["S2", "foldered"], { size: 18, weight: 700, lineHeight: 1.02 });

      const r1Values = ["E1", "E3"].map((condition) => data.index.get(`${backbone.id}|${condition}|${metric.id}`));
      const r2Values = ["E2", "E4"].map((condition) => data.index.get(`${backbone.id}|${condition}|${metric.id}`));
      const r1Ys = r1Values.map(yScale);
      const r2Ys = r2Values.map(yScale);

      svg += line(xPositions[0], r1Ys[0], xPositions[1], r1Ys[1], { stroke: C.teal, width: 5 });
      svg += line(xPositions[0], r2Ys[0], xPositions[1], r2Ys[1], { stroke: C.violet, width: 5, dash: "12 8" });
      for (let index = 0; index < 2; index += 1) {
        svg += circle(xPositions[index], r1Ys[index], 9, C.teal);
        svg += square(xPositions[index], r2Ys[index], 18, C.violet);
        svg += text(xPositions[index], r1Ys[index] - 16, valueLabel(r1Values[index]), { size: 17, weight: 800, fill: C.teal });
        svg += text(xPositions[index], r2Ys[index] + 27, valueLabel(r2Values[index]), { size: 17, weight: 800, fill: C.violet });
      }
    }
  }

  svg += text(W / 2, 1048, "Answer metrics use N=60; Evidence Recall uses N=58. Lines connect condition means rather than inferential estimates.", { size: 18, weight: 600, fill: C.slate });
  svg += text(W / 2, 1077, "Y-axes are truncated and differ across metrics; each metric uses one shared range across both backbones.", { size: 17, weight: 550, fill: C.slate });
  svg += text(W / 2, 1104, "E1=S1+R1 · E2=S1+R2 · E3=S2+R1 · E4=S2+R2", { size: 17, weight: 650, fill: C.slate });
  return `${svg}</svg>`;
}

function effectLabel(value) {
  const points = value * 100;
  if (Math.abs(points) < 0.05) return "0.0";
  return `${points > 0 ? "+" : "−"}${Math.abs(points).toFixed(1)}`;
}

function figure54(data) {
  const metrics = [
    { id: "token_f1", title: "Token F1" },
    { id: "strict_accuracy", title: "Strict Accuracy" },
    { id: "soft_semantic_score", title: "Soft Semantic Score" },
    { id: "evidence_recall", title: "Evidence Recall" },
  ];
  const comparisons = [
    { id: "curated_vs_foldered_r1_e5_minus_e3", code: "E5 − E3", label: "S3+R1 vs S2+R1" },
    { id: "curated_access_e6_minus_e5", code: "E6 − E5", label: "R3 vs R1 on fixed S3" },
    { id: "curated_adapted_vs_foldered_raw_e6_minus_e4", code: "E6 − E4", label: "S3+R3 vs S2+R2" },
  ];
  const panels = [
    { x: 90, y: 220 },
    { x: 1025, y: 220 },
    { x: 90, y: 615 },
    { x: 1025, y: 615 },
  ];
  const panelW = 885;
  const panelH = 340;
  const min = -26;
  const max = 13;
  const ticks = [-25, -15, -5, 0, 5, 10];

  let svg = base(
    "Agent-Curated Memory: Architecture-Effect Profile",
    "Mean difference in percentage points (target − baseline); positive values favour the target condition",
  );

  svg += circle(760, 166, 9, C.teal);
  svg += text(782, 173, "Qwen", { size: 19, weight: 700, anchor: "start" });
  svg += triangle(1010, 166, 22, C.violet);
  svg += text(1034, 173, "DeepSeek", { size: 19, weight: 700, anchor: "start" });
  svg += line(1210, 166, 1260, 166, { stroke: C.navy, width: 3, dash: "8 6" });
  svg += text(1280, 173, "zero effect", { size: 19, weight: 600, anchor: "start", fill: C.slate });

  for (let metricIndex = 0; metricIndex < metrics.length; metricIndex += 1) {
    const metric = metrics[metricIndex];
    const { x, y } = panels[metricIndex];
    svg += rect(x, y, panelW, panelH, { fill: C.white, stroke: C.border, strokeWidth: 2, radius: 18, shadow: true });
    svg += text(x + panelW / 2, y + 39, metric.title, { size: 24, weight: 800 });

    const px0 = x + 255;
    const px1 = x + panelW - 42;
    const py0 = y + 70;
    const py1 = y + panelH - 60;
    const xScale = (value) => px0 + ((value - min) / (max - min)) * (px1 - px0);
    const zeroX = xScale(0);

    // Subtle directional fields make the zero-centred interpretation immediate.
    svg += `<rect x="${px0}" y="${py0}" width="${zeroX - px0}" height="${py1 - py0}" fill="${C.redPale}" fill-opacity="0.28"/>`;
    svg += `<rect x="${zeroX}" y="${py0}" width="${px1 - zeroX}" height="${py1 - py0}" fill="${C.tealPale}" fill-opacity="0.34"/>`;

    for (const tick of ticks) {
      const tx = xScale(tick);
      svg += line(tx, py0, tx, py1, { stroke: tick === 0 ? C.navy : C.grid, width: tick === 0 ? 2.6 : 1.3, dash: tick === 0 ? "8 6" : "" });
      svg += text(tx, py1 + 27, tick > 0 ? `+${tick}` : `${tick}`, { size: 16, weight: tick === 0 ? 800 : 500, fill: tick === 0 ? C.navy : C.slate });
    }

    for (let comparisonIndex = 0; comparisonIndex < comparisons.length; comparisonIndex += 1) {
      const comparison = comparisons[comparisonIndex];
      const rowY = py0 + 38 + comparisonIndex * 69;
      svg += line(px0, rowY, px1, rowY, { stroke: C.grid, width: 1.1, opacity: 0.75 });
      svg += text(x + 24, rowY - 4, comparison.code, { size: 20, weight: 800, anchor: "start" });
      svg += text(x + 24, rowY + 19, comparison.label, { size: 16, weight: 500, fill: C.slate, anchor: "start" });

      const qwen = data.index.get(`qwen|${comparison.id}`)[metric.id];
      const deepseek = data.index.get(`deepseek|${comparison.id}`)[metric.id];
      const qx = xScale(qwen * 100);
      const dx = xScale(deepseek * 100);
      const qy = rowY - 10;
      const dy = rowY + 10;
      svg += circle(qx, qy, 8, C.teal);
      svg += triangle(dx, dy, 20, C.violet);

      const qAnchor = qwen * 100 > 9 ? "end" : "start";
      const dAnchor = deepseek * 100 > 9 ? "end" : "start";
      svg += text(qx + (qAnchor === "end" ? -12 : 12), qy + 6, effectLabel(qwen), { size: 17, weight: 800, fill: C.teal, anchor: qAnchor });
      svg += text(dx + (dAnchor === "end" ? -12 : 12), dy + 6, effectLabel(deepseek), { size: 17, weight: 800, fill: C.violet, anchor: dAnchor });
    }
  }

  svg += text(W / 2, 1054, "E5−E3 and E6−E4 are descriptive complete-system anchors; E6−E5 compares R3 with R1 on the same frozen S3 store.", { size: 19, weight: 650, fill: C.slate });
  svg += text(W / 2, 1084, "No bootstrap interval was pre-declared for these S3 comparisons. Answer metrics use N=60; Evidence Recall uses N=58.", { size: 18, weight: 550, fill: C.slate });
  return `${svg}</svg>`;
}

async function writeFigure(stem, svg) {
  const svgPath = path.join(OUT, `${stem}.svg`);
  const pngPath = path.join(OUT, `${stem}.png`);
  fs.writeFileSync(svgPath, svg, "utf8");
  await sharp(Buffer.from(svg))
    .resize(W, H, { fit: "fill" })
    .flatten({ background: C.bg })
    .png({ compressionLevel: 9, adaptiveFiltering: true })
    .toFile(pngPath);
  return [svgPath, pngPath];
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const audit = validateGate();
  const fig53 = loadFigure53();
  const fig54 = loadFigure54();
  const outputs = [];
  outputs.push(...await writeFigure("figure-5-1-storage-retrieval-interaction", figure53(fig53)));
  outputs.push(...await writeFigure("figure-5-2-curated-memory-effect-profile", figure54(fig54)));

  const lineage = {
    generated_at: new Date().toISOString(),
    generator: path.relative(ROOT, __filename),
    stage_e_audit_id: audit.audit_id,
    stage_e_status: audit.status,
    source_files: [FIG53_INPUT, FIG54_INPUT, AUDIT, PASSED].map((filePath) => ({
      path: path.relative(ROOT, filePath),
      sha256: sha256(filePath),
    })),
    output_files: outputs.map((filePath) => ({
      path: path.relative(ROOT, filePath),
      sha256: sha256(filePath),
    })),
  };
  const lineagePath = path.join(OUT, "data-lineage.json");
  fs.writeFileSync(lineagePath, `${JSON.stringify(lineage, null, 2)}\n`, "utf8");

  const checksumFiles = [...outputs, lineagePath, __filename];
  const checksums = checksumFiles
    .map((filePath) => `${sha256(filePath)}  ${path.basename(filePath)}`)
    .join("\n");
  fs.writeFileSync(path.join(OUT, "SHA256SUMS"), `${checksums}\n`, "utf8");
}

main().catch((error) => {
  console.error(error.stack || error.message || error);
  process.exitCode = 1;
});
