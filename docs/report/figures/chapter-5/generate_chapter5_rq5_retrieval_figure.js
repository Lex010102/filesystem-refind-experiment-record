#!/usr/bin/env node

/*
 * Deterministic vector source for Figure 5.7.
 *
 * The program reads only the passed RQ5 retrieval-audit table, verifies the
 * audit and PASSED gates, and writes an editable SVG, a PNG preview, and a
 * data-lineage record. It performs no estimation, model call, or network call.
 */

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const sharp = require("sharp");

const OUT = __dirname;
const ROOT = path.resolve(OUT, "../../../..");
const AUDIT_DIR = path.join(ROOT, "artifacts/chapter5-main60-analysis-v1/rq5-retrieval-audit");
const INPUT = path.join(AUDIT_DIR, "strict-error-retrieval-linkage.csv");
const AUDIT = path.join(AUDIT_DIR, "audit.json");
const PASSED = path.join(AUDIT_DIR, "RQ5-RETRIEVAL-AUDIT.PASSED");

const STEM = "figure-5-7-retrieval-error-stage-distribution";
const LINEAGE = "figure-5-7-data-lineage.json";
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
  white: "#FFFFFF",
  pale: "#F5F8FA",
};

const STATES = [
  {
    key: "complete",
    label: "Complete annotated bundle",
    color: C.teal,
    text: C.white,
  },
  {
    key: "retrieval_attrition",
    label: "Retrieval-stage attrition",
    color: C.amber,
    text: C.navy,
  },
  {
    key: "bundle_loss",
    label: "Selected-to-bundle loss",
    color: C.violet,
    text: C.white,
  },
];

const RETRIEVER_LABELS = {
  R1: ["R1", "Agentic Filesystem Retrieval"],
  R2: ["R2", "ReFind-Style Raw-Chat Retrieval"],
  R3: ["R3", "Curated-Memory Retrieval"],
  ALL: ["Overall", "E1–E6 selective paths"],
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
    complete_annotated_bundle_strict_noncorrect: "complete",
    annotated_source_not_reached: "retrieval_attrition",
    source_reached_gold_not_observed: "retrieval_attrition",
    partial_annotated_acquisition: "retrieval_attrition",
    complete_observation_incomplete_selection: "retrieval_attrition",
    complete_selection_incomplete_bundle: "bundle_loss",
  };
  const key = mapping[row.diagnostic_retrieval_state];
  if (!key) fail(`Unexpected eligible diagnostic state: ${row.diagnostic_retrieval_state}`);
  return key;
}

function loadData() {
  for (const required of [INPUT, AUDIT, PASSED]) {
    if (!fs.existsSync(required)) fail(`Missing required input: ${path.relative(ROOT, required)}`);
  }
  const audit = JSON.parse(fs.readFileSync(AUDIT, "utf8"));
  const passed = JSON.parse(fs.readFileSync(PASSED, "utf8"));
  if (audit.status !== "passed" || passed.status !== "passed") fail("The retrieval audit must be passed");
  if (audit.protocol_version !== "chapter5-main60-rq5-retrieval-audit-v1") fail("Unexpected protocol version");
  if (passed.protocol_version !== audit.protocol_version || passed.audit_id !== audit.audit_id) {
    fail("PASSED marker does not identify the audited retrieval run");
  }
  if (passed.audit_sha256 !== sha256(AUDIT)) fail("PASSED marker audit hash does not match audit.json");
  if (audit.output_sha256?.["strict-error-retrieval-linkage.csv"] !== sha256(INPUT)) {
    fail("Input table hash does not match the passed audit");
  }

  const rows = parseCsv(fs.readFileSync(INPUT, "utf8"));
  if (rows.length !== audit.strict_error_paths) {
    fail(`Expected ${audit.strict_error_paths} Strict-error paths; found ${rows.length}`);
  }
  const eligibleRows = rows.filter((row) => row.evidence_eligible === "True");
  if (eligibleRows.length !== audit.eligible_strict_error_paths) {
    fail(`Expected ${audit.eligible_strict_error_paths} eligible Strict-error paths; found ${eligibleRows.length}`);
  }

  const counts = {};
  for (const retriever of ["R1", "R2", "R3", "ALL"]) {
    counts[retriever] = Object.fromEntries(STATES.map((state) => [state.key, 0]));
  }
  for (const row of eligibleRows) {
    if (row.protocol_version !== audit.protocol_version) fail("Row protocol version differs from the audit");
    if (!["R1", "R2", "R3"].includes(row.retriever_id)) fail(`Unexpected retriever: ${row.retriever_id}`);
    if (!["partial", "incorrect"].includes(row.judge_label)) fail("Input contains a Strict-correct path");
    const key = stateKey(row);
    counts[row.retriever_id][key] += 1;
    counts.ALL[key] += 1;
  }

  const expected = {
    R1: { complete: 68, retrieval_attrition: 17, bundle_loss: 0 },
    R2: { complete: 28, retrieval_attrition: 44, bundle_loss: 0 },
    R3: { complete: 15, retrieval_attrition: 12, bundle_loss: 7 },
    ALL: { complete: 111, retrieval_attrition: 73, bundle_loss: 7 },
  };
  for (const retriever of Object.keys(expected)) {
    for (const state of STATES) {
      if (counts[retriever][state.key] !== expected[retriever][state.key]) {
        fail(`Count mismatch for ${retriever}/${state.key}`);
      }
    }
  }
  return { audit, passed, rows, eligibleRows, counts };
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
  parts.push(`<title>Annotated-Evidence State of Evidence-Eligible Strict Errors</title>`);
  parts.push(`<desc>One hundred percent stacked bars compare complete annotated bundles, retrieval-stage attrition, and selected-to-bundle loss for R1, R2, R3, and the weighted overall aggregate.</desc>`);
  parts.push(`<defs><filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="6" stdDeviation="10" flood-color="#0F2D4E" flood-opacity="0.12"/></filter></defs>`);
  parts.push(rect(0, 0, W, H, { fill: C.background }));

  parts.push(text(W / 2, 82, "Annotated-Evidence State of Evidence-Eligible Strict Errors", { size: 54, weight: 700 }));
  parts.push(text(W / 2, 132, "E1–E6 selective-retrieval paths pooled across both backbone models (n = 191)", { size: 27, fill: C.slate }));

  const legendY = 205;
  const legend = [
    { x: 355, state: STATES[0] },
    { x: 850, state: STATES[1] },
    { x: 1325, state: STATES[2] },
  ];
  for (const item of legend) {
    parts.push(rect(item.x, legendY - 20, 30, 30, { fill: item.state.color, radius: 5 }));
    parts.push(text(item.x + 45, legendY + 4, item.state.label, { size: 22, anchor: "start", weight: 600 }));
  }

  const chartX = 520;
  const chartWidth = 1270;
  const barHeight = 76;
  const rows = [
    { retriever: "R1", y: 315 },
    { retriever: "R2", y: 452 },
    { retriever: "R3", y: 589 },
    { retriever: "ALL", y: 752 },
  ];

  parts.push(text(chartX, 270, "Within-retriever share of eligible Strict-error paths", { size: 21, fill: C.slate, anchor: "start", weight: 600 }));
  for (const tick of [0, 25, 50, 75, 100]) {
    const x = chartX + chartWidth * tick / 100;
    parts.push(`<line x1="${x}" y1="286" x2="${x}" y2="850" stroke="${tick === 50 ? C.slate : C.grid}" stroke-width="${tick === 50 ? 2.5 : 1.5}" ${tick === 50 ? 'stroke-dasharray="8 8"' : ""}/>`);
    parts.push(text(x, 290, `${tick}%`, { size: 18, fill: C.slate }));
  }

  for (const row of rows) {
    const counts = data.counts[row.retriever];
    const total = totalFor(counts);
    const [primary, secondary] = RETRIEVER_LABELS[row.retriever];
    const centerY = row.y + barHeight / 2;
    parts.push(text(475, centerY - 7, primary, { size: row.retriever === "ALL" ? 29 : 34, weight: 700, anchor: "end" }));
    parts.push(text(475, centerY + 26, `${secondary} · n=${total}`, { size: 18, fill: C.slate, anchor: "end", weight: 500 }));

    let currentX = chartX;
    const smallLabels = [];
    for (const state of STATES) {
      const count = counts[state.key];
      if (count === 0) continue;
      const segmentWidth = chartWidth * count / total;
      parts.push(rect(currentX, row.y, segmentWidth, barHeight, {
        fill: state.color,
        stroke: C.white,
        strokeWidth: 2,
      }));
      const pct = percentage(count, total);
      const label = `${count} · ${pct.toFixed(1)}%`;
      if (segmentWidth >= 160) {
        parts.push(text(currentX + segmentWidth / 2, centerY + 8, label, {
          size: 21,
          weight: 700,
          fill: state.text,
        }));
      } else if (segmentWidth >= 58) {
        parts.push(text(currentX + segmentWidth / 2, centerY + 8, String(count), {
          size: 20,
          weight: 700,
          fill: state.text,
        }));
        smallLabels.push({
          x: currentX + segmentWidth / 2,
          label,
          color: state.color,
          position: "below",
        });
      } else {
        smallLabels.push({
          x: currentX + segmentWidth / 2,
          label,
          color: state.color,
          position: "below",
        });
      }
      currentX += segmentWidth;
    }

    if (row.retriever === "ALL") {
      parts.push(rect(chartX - 2, row.y - 2, chartWidth + 4, barHeight + 4, {
        fill: "none",
        stroke: C.navy,
        strokeWidth: 4,
        radius: 4,
      }));
    }

    smallLabels.forEach((callout, index) => {
      const calloutY = row.y + barHeight + 35 + index * 25;
      parts.push(`<line x1="${callout.x}" y1="${row.y + barHeight}" x2="${callout.x}" y2="${calloutY - 21}" stroke="${callout.color}" stroke-width="2"/>`);
      parts.push(text(Math.min(callout.x + 32, chartX + chartWidth), calloutY, callout.label, {
        size: 18,
        weight: 700,
        fill: callout.color,
        anchor: "end",
      }));
    });
  }

  parts.push(text(chartX + chartWidth, 408, "Bundle loss: 0 (0.0%)", { size: 17, fill: C.violet, anchor: "end", weight: 600 }));
  parts.push(text(chartX + chartWidth, 545, "Bundle loss: 0 (0.0%)", { size: 17, fill: C.violet, anchor: "end", weight: 600 }));

  parts.push(rect(270, 902, 1460, 120, { fill: C.tealPale, stroke: C.teal, strokeWidth: 2.5, radius: 24, shadow: true }));
  parts.push(text(495, 961, "111 / 191", { size: 48, weight: 700, fill: C.teal }));
  parts.push(text(745, 960, "(58.1%)", { size: 34, weight: 700, fill: C.navy }));
  parts.push(text(970, 950, "eligible errors already contain all official", { size: 27, weight: 600, anchor: "start" }));
  parts.push(text(970, 986, "annotated locators in the final EvidenceBundle", { size: 27, weight: 600, anchor: "start" }));

  parts.push(text(W / 2, 1060, "Counts are error paths, not independent questions; official locators diagnose funnel position, not causal responsibility.", { size: 19, fill: C.slate }));
  parts.push(text(W / 2, 1090, "A complete annotated bundle does not prove semantic sufficiency or an Answerer utilisation failure; E7 and Full Context are excluded.", { size: 19, fill: C.slate }));
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
    figure_id: "Figure 5.7",
    title: "Annotated-Evidence State of Evidence-Eligible Strict Errors",
    protocol_version: data.audit.protocol_version,
    audit_id: data.audit.audit_id,
    source: path.relative(ROOT, INPUT),
    source_sha256: sha256(INPUT),
    strict_error_paths_in_source: data.rows.length,
    evidence_eligible_strict_error_paths: data.eligibleRows.length,
    counts: data.counts,
    retrieval_stage_attrition_definition: [
      "annotated_source_not_reached",
      "source_reached_gold_not_observed",
      "partial_annotated_acquisition",
      "complete_observation_incomplete_selection",
    ],
    selected_to_bundle_loss_definition: "complete_selection_incomplete_bundle",
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
