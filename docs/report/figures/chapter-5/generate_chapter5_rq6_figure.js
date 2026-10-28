#!/usr/bin/env node

/*
 * Deterministic vector source for Figure 5.10.
 *
 * The program reads only the audited RQ6 plotting table, validates the
 * publication gate and the Soft Semantic Score Pareto contract, and writes an
 * editable SVG plus a publication-ready PNG preview. It performs no new
 * statistical estimation.
 */

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const sharp = require("sharp");

const OUT = __dirname;
const ROOT = path.resolve(OUT, "../../../..");
const RQ6 = path.join(ROOT, "artifacts/chapter5-main60-analysis-v1/rq6-quality-cost");
const INPUT = path.join(RQ6, "figure-5-12-inputs.csv");
const AUDIT = path.join(RQ6, "audit.json");
const PASSED = path.join(RQ6, "RQ6.PASSED");
const STEM = "figure-5-10-quality-cost-pareto-frontiers";
const LINEAGE = "figure-5-10-data-lineage.json";

const W = 2000;
const H = 1125;

const C = {
  background: "#FEFEFE",
  panel: "#F5F8FA",
  navy: "#0F2D4E",
  teal: "#0A8C86",
  tealPale: "#DDF3F1",
  amber: "#E58A00",
  amberPale: "#FFF0D8",
  slate: "#60788E",
  dominated: "#C7D4DE",
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

function assertClose(actual, expected, label, tolerance = 1e-12) {
  if (!Number.isFinite(actual) || Math.abs(actual - expected) > tolerance) {
    fail(`${label}: expected ${expected}, found ${actual}`);
  }
}

function loadData() {
  if (!fs.existsSync(PASSED)) fail("RQ6 passed marker is missing");
  const audit = JSON.parse(fs.readFileSync(AUDIT, "utf8"));
  if (audit.status !== "passed") fail(`RQ6 audit status is ${audit.status}`);
  if (audit.protocol_version !== "chapter5-main60-rq6-v1") {
    fail(`Unexpected RQ6 protocol ${audit.protocol_version}`);
  }
  if (!audit.output_sha256 || audit.output_sha256["figure-5-12-inputs.csv"] !== sha256(INPUT)) {
    fail("Figure 5.10 input hash does not match the passed RQ6 audit");
  }

  const rawRows = parseCsv(fs.readFileSync(INPUT, "utf8"));
  const rows = rawRows
    .filter((row) => row.quality_metric === "soft_semantic_score")
    .map((row) => ({
      scope: row.comparison_scope,
      condition: row.condition_id === "B3-FullContext" ? "Full Context" : row.condition_id,
      tokens: Number(row.mean_query_total_tokens),
      quality: Number(row.quality_value),
      efficient: row.pareto_efficient === "True",
      diagnostic: row.condition_id === "B3-FullContext",
    }));

  const qwen = rows.filter((row) => row.scope === "qwen_selective_exact");
  const deepseek = rows.filter((row) => row.scope === "deepseek_family_diagnostic");
  if (qwen.length !== 7) fail(`Expected 7 Qwen rows, found ${qwen.length}`);
  if (deepseek.length !== 8) fail(`Expected 8 DeepSeek-family rows, found ${deepseek.length}`);

  const expectedQwen = new Set(["E2", "E4", "E6", "E3", "E5"]);
  const expectedDeepSeek = new Set(["E2", "Full Context"]);
  for (const row of qwen) {
    if (row.efficient !== expectedQwen.has(row.condition)) {
      fail(`Unexpected Qwen Pareto status for ${row.condition}`);
    }
  }
  for (const row of deepseek) {
    if (row.efficient !== expectedDeepSeek.has(row.condition)) {
      fail(`Unexpected DeepSeek-family Pareto status for ${row.condition}`);
    }
  }

  const qwenE3 = qwen.find((row) => row.condition === "E3");
  const deepseekE7 = deepseek.find((row) => row.condition === "E7");
  const fullContext = deepseek.find((row) => row.condition === "Full Context");
  assertClose(qwenE3.tokens, 140288.41666666666, "Qwen E3 tokens");
  assertClose(qwenE3.quality, 0.7916666666666666, "Qwen E3 Soft");
  assertClose(deepseekE7.quality, 0.8, "DeepSeek E7 Soft");
  assertClose(fullContext.tokens, 36646.166666666664, "Full Context tokens");
  assertClose(fullContext.quality, 0.825, "Full Context Soft");
  return { audit, qwen, deepseek };
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

function circle(cx, cy, radius, options = {}) {
  const { fill = C.teal, stroke = C.white, strokeWidth = 4 } = options;
  return `<circle cx="${cx}" cy="${cy}" r="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}"/>`;
}

function diamond(cx, cy, radius, options = {}) {
  const { fill = C.amber, stroke = C.white, strokeWidth = 4 } = options;
  const points = `${cx},${cy - radius} ${cx + radius},${cy} ${cx},${cy + radius} ${cx - radius},${cy}`;
  return `<polygon points="${points}" fill="${fill}" stroke="${stroke}" stroke-width="${strokeWidth}" stroke-linejoin="round"/>`;
}

const X_MIN = 15000;
const X_MAX = 450000;
const Y_MIN = 0.69;
const Y_MAX = 0.84;

function scaleLog(value, start, end) {
  const ratio = (Math.log10(value) - Math.log10(X_MIN)) / (Math.log10(X_MAX) - Math.log10(X_MIN));
  return start + ratio * (end - start);
}

function scaleY(value, top, bottom) {
  const ratio = (value - Y_MIN) / (Y_MAX - Y_MIN);
  return bottom - ratio * (bottom - top);
}

const LABEL_OFFSETS = {
  qwen_selective_exact: {
    E1: [18, 32],
    E2: [-18, 34],
    E3: [-18, -22],
    E4: [22, -20],
    E5: [-18, -22],
    E6: [-18, -22],
    E7: [18, 32],
  },
  deepseek_family_diagnostic: {
    E1: [18, -22],
    E2: [-24, -22],
    E3: [-26, 34],
    E4: [25, 34],
    E5: [-18, -22],
    E6: [-20, 34],
    E7: [18, -22],
    "Full Context": [22, -22],
  },
};

function renderPanel(parts, panel, rows, options) {
  const { title: panelTitle, subtitle, scope, diagnostic } = options;
  parts.push(rect(panel.x, panel.y, panel.width, panel.height, {
    fill: C.panel,
    stroke: C.border,
    strokeWidth: 2.4,
    radius: 26,
    shadow: true,
  }));
  parts.push(text(panel.x + panel.width / 2, panel.y + 55, panelTitle, { size: 31, weight: 700 }));
  parts.push(text(panel.x + panel.width / 2, panel.y + 91, subtitle, { size: 20, fill: C.slate }));

  const chart = {
    left: panel.x + 115,
    right: panel.x + panel.width - 46,
    top: panel.y + 140,
    bottom: panel.y + panel.height - 105,
  };
  const xTicks = [20000, 50000, 100000, 200000, 400000];
  const yTicks = [0.70, 0.725, 0.75, 0.775, 0.80, 0.825];

  for (const tick of yTicks) {
    const y = scaleY(tick, chart.top, chart.bottom);
    parts.push(line(chart.left, y, chart.right, y, { stroke: C.grid, width: 1.5 }));
    parts.push(text(chart.left - 16, y + 7, tick.toFixed(3), { size: 17, fill: C.slate, anchor: "end" }));
  }
  for (const tick of xTicks) {
    const x = scaleLog(tick, chart.left, chart.right);
    parts.push(line(x, chart.top, x, chart.bottom, { stroke: C.grid, width: 1.5 }));
    parts.push(text(x, chart.bottom + 31, `${Math.round(tick / 1000)}k`, { size: 17, fill: C.slate }));
  }
  parts.push(line(chart.left, chart.bottom, chart.right, chart.bottom, { stroke: C.navy, width: 2.2 }));
  parts.push(line(chart.left, chart.top, chart.left, chart.bottom, { stroke: C.navy, width: 2.2 }));
  parts.push(text((chart.left + chart.right) / 2, panel.y + panel.height - 43, "Mean query tokens (log scale)", { size: 20, weight: 600 }));
  parts.push(`<text x="${panel.x + 29}" y="${(chart.top + chart.bottom) / 2}" transform="rotate(-90 ${panel.x + 29} ${(chart.top + chart.bottom) / 2})" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="20" font-weight="600" fill="${C.navy}">Soft Semantic Score</text>`);

  const efficient = rows.filter((row) => row.efficient).sort((a, b) => a.tokens - b.tokens);
  const frontierPoints = efficient.map((row) => {
    const x = scaleLog(row.tokens, chart.left, chart.right);
    const y = scaleY(row.quality, chart.top, chart.bottom);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  if (frontierPoints) {
    parts.push(`<polyline points="${frontierPoints}" fill="none" stroke="${diagnostic ? C.amber : C.teal}" stroke-width="4"${diagnostic ? ' stroke-dasharray="10 8"' : ""} stroke-linecap="round" stroke-linejoin="round" opacity="0.92"/>`);
  }

  const orderedRows = [...rows].sort((a, b) => Number(a.efficient) - Number(b.efficient));
  for (const row of orderedRows) {
    const x = scaleLog(row.tokens, chart.left, chart.right);
    const y = scaleY(row.quality, chart.top, chart.bottom);
    const [dx, dy] = LABEL_OFFSETS[scope][row.condition];
    const labelX = x + dx;
    const labelY = y + dy;
    const labelAnchor = dx < 0 ? "end" : "start";
    const leaderEndX = labelX + (dx < 0 ? 8 : -8);
    const leaderEndY = labelY - (dy > 0 ? 14 : -5);
    parts.push(line(x, y, leaderEndX, leaderEndY, {
      stroke: row.diagnostic ? C.amber : (row.efficient ? C.teal : C.slate),
      width: 1.4,
      opacity: 0.72,
    }));
    if (row.diagnostic) {
      parts.push(diamond(x, y, 16, { fill: C.amber }));
    } else if (row.efficient) {
      parts.push(circle(x, y, 13, { fill: C.teal }));
    } else {
      parts.push(circle(x, y, 11, { fill: C.dominated, stroke: C.white, strokeWidth: 3 }));
    }
    parts.push(text(labelX, labelY, row.condition, {
      size: row.condition === "Full Context" ? 17 : 19,
      weight: row.efficient ? 700 : 600,
      fill: row.diagnostic ? C.amber : (row.efficient ? C.navy : C.slate),
      anchor: labelAnchor,
    }));
  }
}

function buildSvg(data) {
  const parts = [];
  parts.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`);
  parts.push("<title>Quality–Cost Pareto Frontiers</title>");
  parts.push("<desc>Two scatter plots show Soft Semantic Score against mean successful-query tokens. Solid points are Pareto-efficient, pale points are dominated, and Full Context is a diagnostic point.</desc>");
  parts.push(`<defs><filter id="shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="6" stdDeviation="10" flood-color="#0F2D4E" flood-opacity="0.10"/></filter></defs>`);
  parts.push(rect(0, 0, W, H, { fill: C.background, stroke: C.background, radius: 0 }));

  parts.push(text(W / 2, 73, "Quality–Cost Pareto Frontiers", { size: 56, weight: 700 }));
  parts.push(text(W / 2, 122, "Soft Semantic Score versus mean successful-query tokens", { size: 26, fill: C.slate }));

  const legendY = 169;
  parts.push(circle(660, legendY - 7, 11, { fill: C.teal, strokeWidth: 3 }));
  parts.push(text(680, legendY, "Pareto-efficient", { size: 19, weight: 600, anchor: "start" }));
  parts.push(circle(900, legendY - 7, 10, { fill: C.dominated, strokeWidth: 3 }));
  parts.push(text(920, legendY, "Dominated", { size: 19, weight: 600, anchor: "start", fill: C.slate }));
  parts.push(diamond(1090, legendY - 7, 12, { fill: C.amber, strokeWidth: 3 }));
  parts.push(text(1112, legendY, "Full Context diagnostic", { size: 19, weight: 600, anchor: "start" }));

  const left = { x: 55, y: 205, width: 925, height: 815 };
  const right = { x: 1020, y: 205, width: 925, height: 815 };
  renderPanel(parts, left, data.qwen, {
    title: "Panel A · Qwen",
    subtitle: "Exact selective-retrieval scope · E1–E7",
    scope: "qwen_selective_exact",
    diagnostic: false,
  });
  renderPanel(parts, right, data.deepseek, {
    title: "Panel B · DeepSeek + Full Context",
    subtitle: "Diagnostic mixed-served-model scope",
    scope: "deepseek_family_diagnostic",
    diagnostic: true,
  });

  parts.push(rect(300, 1040, 1400, 55, { fill: C.amberPale, stroke: C.amber, strokeWidth: 2, radius: 18 }));
  parts.push(text(W / 2, 1075, "Pareto status is computed within each panel; Panel B is diagnostic because Full Context used a different served-model identifier.", { size: 19, weight: 600 }));
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
    figure_id: "Figure 5.10",
    title: "Quality–Cost Pareto Frontiers",
    protocol_version: data.audit.protocol_version,
    audit_id: data.audit.audit_id,
    source: path.relative(ROOT, INPUT),
    source_sha256: sha256(INPUT),
    plotted_metric: "soft_semantic_score",
    cost_metric: "mean_query_total_tokens",
    x_axis_scale: "log10",
    panels: {
      qwen_selective_exact: {
        rows: data.qwen.length,
        pareto_efficient: data.qwen.filter((row) => row.efficient).map((row) => row.condition),
      },
      deepseek_family_diagnostic: {
        rows: data.deepseek.length,
        pareto_efficient: data.deepseek.filter((row) => row.efficient).map((row) => row.condition),
        mixed_served_model_scope: true,
      },
    },
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
