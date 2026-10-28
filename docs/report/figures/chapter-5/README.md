# Chapter 5 figure assets

This directory contains the editable vector sources and PNG previews for the
figures used in Sections 5.2–5.7.

| Figure | Asset stem | Role | Planned placement |
|---|---|---|---|
| 5.1 | `figure-5-1-storage-retrieval-interaction` | E1–E4 storage–retrieval interaction across Qwen and DeepSeek | Section 5.2.3, after the Table 5.7 condition means and before Table 5.8 DID estimates |
| 5.2 | `figure-5-2-curated-memory-effect-profile` | S3 lexical, semantic, and evidence trade-offs | Section 5.2.4, after Tables 5.9–5.10 |
| 5.3 | `figure-5-3-cross-backbone-architecture-stability` | Directional stability of the six RQ1 architecture effects across Qwen and DeepSeek | Section 5.3.2, after Table 5.13 Panel B |
| 5.4 | `figure-5-4-e7-composition` | Explanatory composition of E7 from the E2 and E6 evidence paths | Section 5.4 opening, after the E7 definition |
| 5.5 | `figure-5-5-descriptive-fusion-outcome-flow` | Descriptive partition from E2/E6 parent-correctness profiles to E7 Strict outcomes | Section 5.4.3, after Table 5.14, Panel D |
| 5.6 | `figure-5-6-selective-error-storage-state` | Storage-state distribution of the 205 E1–E6 Strict-noncorrect answer paths | Section 5.6.2.4, after Table 5.20 |
| 5.7 | `figure-5-7-retrieval-error-stage-distribution` | Annotated-evidence state of the 191 evidence-eligible E1–E6 Strict-error paths | Section 5.6.3.1, after Table 5.21 |
| 5.8 | `figure-5-8-token-f1-llm-judge-alignment` | Token F1 distribution within each frozen LLM judge label | Section 5.6.5.1, after Table 5.29 |
| 5.9 | `figure-5-9-integrated-bottleneck-decomposition` | Primary attribution of all 250 non-Correct paths and the 123 confirmed system-internal failures | Section 5.6.6.1, after Table 5.31, Panel A |
| 5.10 | `figure-5-10-quality-cost-pareto-frontiers` | Soft Semantic Score versus successful-query token cost for Qwen and the DeepSeek-family diagnostic scope | Section 5.7.2, after Table 5.34 |

The SVG files are the canonical editable assets. The PNG files are previews
for Markdown and report review. Figures 5.1–5.2 use the audited Stage-E RQ1
artifact; Figure 5.3 uses the audited RQ2 artifact. The generators perform no
new statistical estimation. Figure 5.4 is an explanatory system diagram and
contains no measured result. Figure 5.5 uses the audited RQ3 artifact; its
ribbon widths are proportional to exact paired-question counts, and the
figure explicitly avoids a causal interpretation.

## Data lineage

- Figure 5.1 reads the frozen `stage-e-rq1/figure-5-3-inputs.csv` artifact
  (32 condition-mean rows). The frozen input filename retains its original
  pre-renumbering identifier.
- Figure 5.2 reads the six registered S3 rows from
  `stage-e-rq1/architecture-effects.csv`.
- Figure 5.3 reads the six audited rows in
  `rq2-backbone-robustness/table-5-13-inputs.csv`.
- Figure 5.4 has no empirical input. It records the frozen E2, E6, and E7
  composition described in Chapter 3.
- Figure 5.5 reads the 16 audited rows in the frozen
  `rq3-dual-source-fusion/figure-5-6-inputs.csv` artifact.
- Figure 5.6 reads the 205 audited rows in
  `rq5-storage-audit/case-storage-linkage.csv`. The plot normalises each store
  separately and includes the weighted all-path aggregate.
- Figure 5.7 reads the 205 audited Strict-error rows in
  `rq5-retrieval-audit/strict-error-retrieval-linkage.csv`, restricts the plot
  to the 191 evidence-eligible paths, normalises each retriever separately,
  and includes the weighted all-path aggregate.
- Figure 5.8 reads the 15-cell audited cross-tabulation in
  `rq5-evaluation-audit/judge-f1-crosstab.csv`. The teal intensity uses
  the within-label share, so each Correct, Partial, and Incorrect row sums to
  100% before rounding. Every cell also prints the exact answer count.
- Figure 5.9 reads the seven overall rows in
  `rq5-integrated-bottleneck/primary-root-cause-summary.csv`. Its left panel
  uses all 250 non-Correct answer paths. Its right panel excludes
  evaluation-sensitive and mixed-or-indeterminate paths and therefore uses
  the 123 confirmed system-internal paths.
- Figure 5.10 reads the audited Soft Semantic Score rows in the frozen
  `rq6-quality-cost/figure-5-12-inputs.csv` artifact. Panel A uses the exact Qwen
  E1–E7 scope. Panel B includes the Full Context diagnostic point and is
  explicitly marked as a mixed-served-model comparison. The horizontal axis
  uses a logarithmic scale because observed query cost spans more than one
  order of magnitude.
- The generator requires the Stage-E audit status to be `passed` and the
  `STAGE-E-RQ1.PASSED` marker to be present.
- The Figure 5.3 generator separately requires the RQ2 audit status to be
  `passed` and the `RQ2.PASSED` marker to be present.
- The Figure 5.5 generator separately verifies the RQ3 audit status, the
  `RQ3.PASSED` marker and its audit hash, and the audited input-table hash.
- The Figure 5.6 generator separately verifies the RQ5 storage-audit status,
  the `RQ5-STORAGE-AUDIT.PASSED` marker and its audit hash, and the audited
  input-table hash.
- The Figure 5.7 generator separately verifies the RQ5 retrieval-audit status,
  the `RQ5-RETRIEVAL-AUDIT.PASSED` marker and its audit hash, and the audited
  input-table hash.
- The Figure 5.8 generator separately verifies the RQ5 evaluation-audit
  status, the `RQ5-EVALUATION.PASSED` marker and its audit hash, and the
  audited input-table hash.
- The Figure 5.9 generator separately verifies the RQ5 integrated-audit
  status, the `RQ5-INTEGRATED.PASSED` marker and its audit hash, and the
  audited primary-root-cause table hash.
- The Figure 5.10 generator separately verifies the RQ6 audit status, the
  `RQ6.PASSED` marker, the audited plotting-table hash, and every Soft-score
  Pareto-membership label shown in the two panels.
- `data-lineage.json`, `figure-5-3-data-lineage.json`,
  `figure-5-5-data-lineage.json`, `figure-5-6-data-lineage.json`,
  `figure-5-7-data-lineage.json`, `figure-5-8-data-lineage.json`,
  `figure-5-9-data-lineage.json`, and `figure-5-10-data-lineage.json` record
  the exact input and output hashes used by the current renders.

## Reproduction

Run the deterministic generator with the bundled Node.js dependencies:

```bash
NODE_PATH="$BUNDLED_NODE_MODULES" "$BUNDLED_NODE" generate_chapter5_rq1_figures.js
NODE_PATH="$BUNDLED_NODE_MODULES" "$BUNDLED_NODE" generate_chapter5_rq2_figure.js
NODE_PATH="$BUNDLED_NODE_MODULES" "$BUNDLED_NODE" generate_chapter5_e7_composition_figure.js
NODE_PATH="$BUNDLED_NODE_MODULES" "$BUNDLED_NODE" generate_chapter5_rq3_figure.js
NODE_PATH="$BUNDLED_NODE_MODULES" "$BUNDLED_NODE" generate_chapter5_rq5_storage_figure.js
NODE_PATH="$BUNDLED_NODE_MODULES" "$BUNDLED_NODE" generate_chapter5_rq5_retrieval_figure.js
NODE_PATH="$BUNDLED_NODE_MODULES" "$BUNDLED_NODE" generate_chapter5_rq5_evaluation_figure.js
NODE_PATH="$BUNDLED_NODE_MODULES" "$BUNDLED_NODE" generate_chapter5_rq5_integrated_figure.js
NODE_PATH="$BUNDLED_NODE_MODULES" "$BUNDLED_NODE" generate_chapter5_rq6_figure.js
```

The figure palette and typography follow the Chapter 1–4 report assets. The
charts use high-contrast fills, borders, marker shapes, or line styles as
appropriate so that the plotted groups remain distinguishable in print.
