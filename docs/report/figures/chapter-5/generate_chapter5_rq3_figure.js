#!/usr/bin/env node

/*
 * Deterministic vector source for Figure 5.5.
 *
 * The program reads only the passed RQ3 outcome-flow input table, verifies the
 * audit and PASSED gates, and writes an editable SVG plus a PNG preview. It
 * performs no estimation, model calls, or network access.
 */

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const sharp = require("sharp");

const OUT = __dirname;
const ROOT = path.resolve(OUT, "../../../..");
const RQ3 = path.join(ROOT, "artifacts/chapter5-main60-analysis-v1/rq3-dual-source-fusion");
const INPUT = path.join(RQ3, "figure-5-6-inputs.csv");
const AUDIT = path.join(RQ3, "audit.json");
const PASSED = path.join(RQ3, "RQ3.PASSED");

const STEM = "figure-5-5-descriptive-fusion-outcome-flow";
const LINEAGE_NAME = "figure-5-5-data-lineage.json";
const W = 2000;
const H = 1125;
const FLOW_SCALE = 1.4; // SVG pixels per question; applied without a minimum width.

const C = {
  bg: "#FEFEFE",
  navy: "#0F2D4E",
  teal: "#0A8C86",
  tealPale: "#DDF3F1",
  violet: "#4D60D6",
  violetPale: "#E8EAFE",
  amber: "#C77D16",
  amberPale: "#FBEEDC",
  red: "#C94B49",
  redPale: "#F9E5E4",
  slate: "#60788E",
  slatePale: "#EEF2F5",
  border: "#A8BAC9",
  grid: "#DCE4EA",
  white: "#FFFFFF",
};

const PROFILES = [
  { id: "both_correct", label: "Both correct", detail: "E2 and E6" },
  { id: "e2_only_correct", label: "E2 only correct", detail: "E6 incorrect" },
  { id: "e6_only_correct", label: "E6 only correct", detail: "E2 incorrect" },
  { id: "neither_correct", label: "Neither correct", detail: "E2 and E6 incorrect" },
];

const OUTCOMES = {
  preserve: { label: "Preserve", fill: C.tealPale, stroke: C.teal, symbol: "circle" },
  harm: { label: "Harm", fill: C.redPale, stroke: C.red, symbol: "triangle" },
  repair: { label: "Repair", fill: C.violetPale, stroke: C.violet, symbol: "diamond" },
  unresolved: { label: "Unresolved", fill: C.slatePale, stroke: C.slate, symbol: "square" },
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

function assertClose(actual, expected, label, tolerance = 1e-12) {
  if (!Number.isFinite(actual) || Math.abs(actual - expected) > tolerance) {
    fail(`${label}: expected ${expected}, found ${actual}`);
  }
}

function loadData() {
  for (const required of [INPUT, AUDIT, PASSED]) {
    if (!fs.existsSync(required)) fail(`Required RQ3 gate is missing: ${path.relative(ROOT, required)}`);
  }

  const audit = JSON.parse(fs.readFileSync(AUDIT, "utf8"));
  const passed = JSON.parse(fs.readFileSync(PASSED, "utf8"));
  if (audit.status !== "passed" || passed.status !== "passed") fail("RQ3 audit and PASSED marker must both report passed");
  if (audit.protocol_version !== "chapter5-main60-rq3-v1" || passed.protocol_version !== audit.protocol_version) {
    fail("Unexpected or inconsistent RQ3 protocol version");
  }
  if (passed.audit_id !== audit.audit_id) fail("RQ3 PASSED marker does not identify the audited run");
  if (passed.audit_sha256 !== sha256(AUDIT)) fail("RQ3 PASSED marker audit hash does not match audit.json");
  if (audit.no_api_calls !== true || audit.no_network_calls !== true || audit.statistical_inference_computed !== false) {
    fail("Figure 5.5 requires the passed offline descriptive-only RQ3 scope");
  }
  if (!audit.output_sha256 || audit.output_sha256["figure-5-6-inputs.csv"] !== sha256(INPUT)) {
    fail("Figure 5.5 input hash does not match the passed RQ3 audit");
  }
  if (passed.question_denominator !== 60 || passed.paired_question_triples !== 120) {
    fail("Unexpected RQ3 denominator in PASSED marker");
  }

  const raw = parseCsv(fs.readFileSync(INPUT, "utf8"));
  if (raw.length !== 16) fail(`Figure 5.5 requires 16 rows; found ${raw.length}`);

  const expectedCounts = {
    qwen: {
      both_correct: { preserve: 37, harm: 0 },
      e2_only_correct: { preserve: 2, harm: 1 },
      e6_only_correct: { preserve: 4, harm: 3 },
      neither_correct: { repair: 1, unresolved: 12 },
    },
    deepseek: {
      both_correct: { preserve: 35, harm: 1 },
      e2_only_correct: { preserve: 4, harm: 2 },
      e6_only_correct: { preserve: 3, harm: 1 },
      neither_correct: { repair: 3, unresolved: 11 },
    },
  };
  const backboneOrder = { qwen: 1, deepseek: 2 };
  const grouped = { qwen: {}, deepseek: {} };

  for (const row of raw) {
    const backbone = row.backbone_id;
    const profile = row.parent_profile;
    if (!(backbone in grouped)) fail(`Unexpected backbone: ${backbone}`);
    const profileIndex = PROFILES.findIndex((item) => item.id === profile);
    if (profileIndex < 0) fail(`Unexpected parent profile: ${profile}`);
    if (Number(row.backbone_order) !== backboneOrder[backbone]) fail(`Wrong backbone order for ${backbone}`);
    if (Number(row.parent_profile_order) !== profileIndex + 1) fail(`Wrong profile order for ${backbone}/${profile}`);
    if (Number(row.denominator) !== 60) fail(`Wrong denominator for ${backbone}/${profile}`);

    const strict = row.e7_strict_correct;
    if (!new Set(["True", "False"]).has(strict)) fail(`Invalid E7 Strict flag for ${backbone}/${profile}`);
    const expectedOutcome = profile === "neither_correct"
      ? (strict === "True" ? "repair" : "unresolved")
      : (strict === "True" ? "preserve" : "harm");
    if (row.fusion_outcome !== expectedOutcome) fail(`Invalid outcome mapping for ${backbone}/${profile}/${strict}`);

    const count = Number(row.count);
    const proportion = Number(row.proportion);
    if (!Number.isInteger(count) || count < 0 || count > 60) fail(`Invalid count for ${backbone}/${profile}`);
    assertClose(proportion, count / 60, `${backbone}/${profile}/${expectedOutcome} proportion`);
    grouped[backbone][profile] ??= {};
    if (expectedOutcome in grouped[backbone][profile]) fail(`Duplicate outcome row for ${backbone}/${profile}/${expectedOutcome}`);
    grouped[backbone][profile][expectedOutcome] = count;
  }

  for (const backbone of ["qwen", "deepseek"]) {
    let panelTotal = 0;
    for (const profile of PROFILES) {
      const expected = expectedCounts[backbone][profile.id];
      const actual = grouped[backbone][profile.id];
      if (!actual || Object.keys(actual).length !== 2) fail(`Incomplete outcome pair for ${backbone}/${profile.id}`);
      for (const [outcome, count] of Object.entries(expected)) {
        if (actual[outcome] !== count) fail(`Count mismatch for ${backbone}/${profile.id}/${outcome}`);
        panelTotal += count;
      }
    }
    if (panelTotal !== 60) fail(`${backbone} profile partition sums to ${panelTotal}, not 60`);
  }

  return { audit, passed, grouped };
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
    opacity = 1,
  } = options;
  return `<text x="${x}" y="${y}" text-anchor="${anchor}" font-family="Arial, Helvetica, sans-serif" font-size="${size}" font-weight="${weight}" fill="${fill}" fill-opacity="${opacity}" text-rendering="geometricPrecision">${tspans(lines, x, lineHeight)}</text>`;
}

function rect(x, y, width, height, options = {}) {
  const {
    fill = C.white,
    stroke = C.border,
    strokeWidth = 2,
    radius = 16,
    shadow = false,
    dash = "",
    opacity = 1,
  } = options;
  return `<rect x="${x}" y="${y}" width="${width}" height="${height}" rx="${radius}" fill="${fill}" fill-opacity="${opacity}" stroke="${stroke}" stroke-width="${strokeWidth}"${dash ? ` stroke-dasharray="${dash}"` : ""}${shadow ? ' filter="url(#shadow)"' : ""}/>`;
}

function line(x1, y1, x2, y2, options = {}) {
  const { stroke = C.grid, width = 2, dash = "", opacity = 1 } = options;
  return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${width}" stroke-opacity="${opacity}"${dash ? ` stroke-dasharray="${dash}"` : ""} stroke-linecap="round"/>`;
}

function symbol(kind, cx, cy, color, size = 9) {
  if (kind === "circle") return `<circle cx="${cx}" cy="${cy}" r="${size}" fill="${color}"/>`;
  if (kind === "triangle") {
    return `<polygon points="${cx},${cy - size} ${cx - size},${cy + size} ${cx + size},${cy + size}" fill="${color}"/>`;
  }
  if (kind === "diamond") {
    return `<polygon points="${cx},${cy - size - 1} ${cx + size + 1},${cy} ${cx},${cy + size + 1} ${cx - size - 1},${cy}" fill="${color}"/>`;
  }
  return `<rect x="${cx - size}" y="${cy - size}" width="${size * 2}" height="${size * 2}" rx="2" fill="${color}"/>`;
}

function ribbon(x1, y1, x2, y2, count, color) {
  if (count === 0) return "";
  const c1 = x1 + (x2 - x1) * 0.46;
  const c2 = x1 + (x2 - x1) * 0.54;
  return `<path d="M ${x1} ${y1} C ${c1} ${y1}, ${c2} ${y2}, ${x2} ${y2}" fill="none" stroke="${color}" stroke-width="${count * FLOW_SCALE}" stroke-opacity="0.53" stroke-linecap="butt"/>`;
}

function outcomeCard(x, y, width, height, outcome, count) {
  const style = OUTCOMES[outcome];
  const zero = count === 0;
  let svg = rect(x, y, width, height, {
    fill: zero ? C.white : style.fill,
    stroke: zero ? C.border : style.stroke,
    strokeWidth: 2,
    radius: 13,
    dash: zero ? "7 5" : "",
    opacity: zero ? 0.72 : 1,
  });
  svg += symbol(style.symbol, x + 29, y + height / 2, zero ? C.border : style.stroke, 8);
  svg += text(x + 51, y + height / 2 + 7, `${style.label}  ${count}`, {
    size: 19,
    weight: 800,
    fill: zero ? C.slate : C.navy,
    anchor: "start",
  });
  return svg;
}

function totalsFor(data) {
  const totals = { preserve: 0, harm: 0, repair: 0, unresolved: 0 };
  for (const profile of PROFILES) {
    for (const [outcome, count] of Object.entries(data[profile.id])) totals[outcome] += count;
  }
  return totals;
}

function profileTotal(profileRows) {
  return Object.values(profileRows).reduce((sum, value) => sum + value, 0);
}

function panel(panelX, title, accent, data) {
  const panelY = 166;
  const panelW = 930;
  const panelH = 810;
  const rowCenters = [340, 485, 630, 775];
  const sourceX = panelX + 38;
  const sourceW = 295;
  const sourceH = 82;
  const targetX = panelX + 555;
  const targetW = 325;
  const targetH = 52;
  const targetGap = 12;
  const outcomesByProfile = {
    both_correct: ["preserve", "harm"],
    e2_only_correct: ["preserve", "harm"],
    e6_only_correct: ["preserve", "harm"],
    neither_correct: ["repair", "unresolved"],
  };

  let svg = rect(panelX, panelY, panelW, panelH, { fill: C.white, stroke: C.border, strokeWidth: 2, radius: 20, shadow: true });
  svg += `<path d="M ${panelX + 20} ${panelY} H ${panelX + panelW - 20} Q ${panelX + panelW} ${panelY} ${panelX + panelW} ${panelY + 20} V ${panelY + 66} H ${panelX} V ${panelY + 20} Q ${panelX} ${panelY} ${panelX + 20} ${panelY}" fill="${accent}"/>`;
  svg += text(panelX + panelW / 2, panelY + 43, title, { size: 29, weight: 800, fill: C.white });
  svg += text(sourceX + sourceW / 2, panelY + 101, "Parent correctness profile", { size: 20, weight: 800 });
  svg += text(targetX + targetW / 2, panelY + 101, "E7 Strict outcome", { size: 20, weight: 800 });
  svg += text(panelX + 433, panelY + 101, "count-proportional ribbon", { size: 15, weight: 650, fill: C.slate });

  for (let index = 0; index < PROFILES.length; index += 1) {
    const profile = PROFILES[index];
    const profileRows = data[profile.id];
    const total = profileTotal(profileRows);
    const centerY = rowCenters[index];
    const outcomes = outcomesByProfile[profile.id];
    const firstY = centerY - targetH - targetGap / 2;
    const secondY = centerY + targetGap / 2;
    const totalWidth = total * FLOW_SCALE;
    let cumulative = -totalWidth / 2;

    for (let outcomeIndex = 0; outcomeIndex < outcomes.length; outcomeIndex += 1) {
      const outcome = outcomes[outcomeIndex];
      const count = profileRows[outcome];
      const width = count * FLOW_SCALE;
      const sourceY = centerY + cumulative + width / 2;
      const targetCenterY = (outcomeIndex === 0 ? firstY : secondY) + targetH / 2;
      svg += ribbon(sourceX + sourceW, sourceY, targetX, targetCenterY, count, OUTCOMES[outcome].stroke);
      cumulative += width;
    }

    svg += rect(sourceX, centerY - sourceH / 2, sourceW, sourceH, {
      fill: "#F7F9FB",
      stroke: C.navy,
      strokeWidth: 2,
      radius: 15,
    });
    svg += text(sourceX + 22, centerY - 7, profile.label, { size: 21, weight: 800, anchor: "start" });
    svg += text(sourceX + 22, centerY + 22, `${profile.detail}  ·  n = ${total}`, { size: 16, weight: 600, fill: C.slate, anchor: "start" });
    svg += outcomeCard(targetX, firstY, targetW, targetH, outcomes[0], profileRows[outcomes[0]]);
    svg += outcomeCard(targetX, secondY, targetW, targetH, outcomes[1], profileRows[outcomes[1]]);

    if (index < PROFILES.length - 1) {
      svg += line(panelX + 25, centerY + 71, panelX + panelW - 25, centerY + 71, { stroke: C.grid, width: 1.2 });
    }
  }

  const totals = totalsFor(data);
  const summaryY = panelY + panelH - 72;
  svg += rect(panelX + 38, summaryY, panelW - 76, 48, { fill: C.slatePale, stroke: C.border, strokeWidth: 1.5, radius: 12 });
  svg += text(panelX + 58, summaryY + 31, "E7 totals", { size: 17, weight: 800, anchor: "start" });
  const summary = ["preserve", "harm", "repair", "unresolved"];
  const summaryXs = [panelX + 245, panelX + 410, panelX + 565, panelX + 735];
  for (let index = 0; index < summary.length; index += 1) {
    const outcome = summary[index];
    const style = OUTCOMES[outcome];
    svg += symbol(style.symbol, summaryXs[index], summaryY + 24, style.stroke, 7);
    svg += text(summaryXs[index] + 17, summaryY + 31, `${style.label} ${totals[outcome]}`, { size: 16, weight: 750, anchor: "start" });
  }
  return svg;
}

function figure57(grouped) {
  let svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-labelledby="figure-title figure-desc">
  <title id="figure-title">Descriptive Parent Profiles and E7 Outcomes</title>
  <desc id="figure-desc">Separate Qwen and DeepSeek panels partition sixty paired questions by E2 and E6 Strict correctness and show the corresponding E7 outcome. Ribbon widths and box labels represent exact question counts. The accounting is descriptive and does not imply causal transitions.</desc>
  <defs>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#0F2D4E" flood-opacity="0.10"/></filter>
  </defs>
  <rect width="${W}" height="${H}" fill="${C.bg}"/>
  ${text(W / 2, 68, "Descriptive Parent Profiles and E7 Outcomes", { size: 54, weight: 800 })}
  ${text(W / 2, 111, "Strict-correctness accounting for the same 60 questions under each backbone", { size: 23, weight: 500, fill: C.slate })}
  ${panel(45, "Qwen", C.teal, grouped.qwen)}
  ${panel(1025, "DeepSeek", C.violet, grouped.deepseek)}
  ${text(W / 2, 1023, "Ribbon width and labels encode question count  ·  1 question = 1.4 px  ·  N = 60 per panel", { size: 19, weight: 700, fill: C.slate })}
  ${text(W / 2, 1057, "Preserve/Harm: at least one parent was correct  ·  Repair/Unresolved: neither parent was correct", { size: 18, weight: 600, fill: C.slate })}
  ${text(W / 2, 1090, "Lines partition paired questions; they describe outcomes and do not imply causal transitions.", { size: 18, weight: 600, fill: C.slate })}
  </svg>`;
  return svg;
}

function checksumFile(names) {
  return `${names.map((name) => `${sha256(path.join(OUT, name))}  ${name}`).join("\n")}\n`;
}

async function main() {
  const { audit, passed, grouped } = loadData();
  const svgPath = path.join(OUT, `${STEM}.svg`);
  const pngPath = path.join(OUT, `${STEM}.png`);
  const svg = figure57(grouped);
  fs.writeFileSync(svgPath, svg, "utf8");
  await sharp(Buffer.from(svg))
    .resize(W, H, { fit: "fill" })
    .flatten({ background: C.bg })
    .png({ compressionLevel: 9, adaptiveFiltering: true })
    .toFile(pngPath);

  const lineage = {
    schema_version: 1,
    figure: "Figure 5.5",
    title: "Descriptive Parent Profiles and E7 Outcomes",
    deterministic: true,
    generator: path.relative(ROOT, __filename),
    generator_sha256: sha256(__filename),
    protocol_version: audit.protocol_version,
    rq3_audit_id: audit.audit_id,
    rq3_status: audit.status,
    passed_marker_status: passed.status,
    scope: "descriptive Strict-correctness partition of E2/E6 parent profiles and E7 outcomes",
    panel_denominators: { qwen: 60, deepseek: 60 },
    ribbon_scale_svg_pixels_per_question: FLOW_SCALE,
    causal_claim: false,
    source_files: [INPUT, AUDIT, PASSED].map((filePath) => ({
      path: path.relative(ROOT, filePath),
      sha256: sha256(filePath),
    })),
    output_files: [svgPath, pngPath].map((filePath) => ({
      path: path.relative(ROOT, filePath),
      sha256: sha256(filePath),
    })),
  };
  const lineagePath = path.join(OUT, LINEAGE_NAME);
  fs.writeFileSync(lineagePath, `${JSON.stringify(lineage, null, 2)}\n`, "utf8");

  const checksumNames = [
    "figure-5-1-storage-retrieval-interaction.svg",
    "figure-5-1-storage-retrieval-interaction.png",
    "figure-5-2-curated-memory-effect-profile.svg",
    "figure-5-2-curated-memory-effect-profile.png",
    "figure-5-3-cross-backbone-architecture-stability.svg",
    "figure-5-3-cross-backbone-architecture-stability.png",
    "figure-5-4-e7-composition.svg",
    "figure-5-4-e7-composition.png",
    `${STEM}.svg`,
    `${STEM}.png`,
    "data-lineage.json",
    "figure-5-3-data-lineage.json",
    LINEAGE_NAME,
    "generate_chapter5_rq1_figures.js",
    "generate_chapter5_rq2_figure.js",
    "generate_chapter5_e7_composition_figure.js",
    "generate_chapter5_rq3_figure.js",
  ];
  fs.writeFileSync(path.join(OUT, "SHA256SUMS"), checksumFile(checksumNames), "utf8");
}

main().catch((error) => {
  console.error(error.stack || error.message || error);
  process.exitCode = 1;
});
