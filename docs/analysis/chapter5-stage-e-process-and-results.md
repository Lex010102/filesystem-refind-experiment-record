# Chapter 5 RQ1 Stage E Process and Results Record

## Status and purpose

Stage E is complete and formally audited. It reconciles the frozen Stage B--D
outputs, freezes every number used in the RQ1 report, and provides the final
English prose for Section 5.2. It does not rerun an experiment, rescore an
answer, add a bootstrap comparison, or modify any formal source result.

The machine-readable source of truth is
`artifacts/chapter5-main60-analysis-v1/stage-e-rq1/`. Its passed marker is
`STAGE-E-RQ1.PASSED`. The final report section is
`docs/report/chapter-5-rq1-architecture-effects.md`.

No API was called. No answer, retrieval trace, score, LLM judge result, or
Stage A--D artifact was changed.

## Frozen RQ1 scope

Stage E retains six core effects and two descriptive complete-system anchors,
each evaluated separately within Qwen and DeepSeek. This gives 16 main-text
result units.

| Role | Contrast | Interpretation |
|---|---|---|
| Core | E3−E1 | S1-to-S2 storage organisation under R1 |
| Core | E4−E2 | S1-to-S2 storage organisation under R2 |
| Core | E2−E1 | Complete R2-versus-R1 system effect on S1 |
| Core | E4−E3 | Complete R2-versus-R1 system effect on S2 |
| Core | `(E4−E2)−(E3−E1)` | Storage--retrieval interaction |
| Core | E6−E5 | Complete R3-versus-R1 access-system effect on the same S3 store |
| Descriptive anchor | E5−E3 | S3+R1 versus S2+R1 complete-system comparison |
| Descriptive anchor | E6−E4 | S3+R3 versus S2+R2 complete-system comparison |

All simple effects are target minus baseline. Answer outcomes use `N=60`,
evidence outcomes use the fixed eligible `N=58`, and multi-source evidence
outcomes use `N=19`. Category answer denominators are 13/13/7/27 and category
evidence denominators are 13/13/5/27 for C1/C2/C3/C4. Main-60 is treated as
one unified test set.

Stage E excludes formal cross-backbone inference, E7, Full Context, a global
error-stage census, Pareto analysis, and final system recommendation. These
remain RQ2--RQ6 tasks.

## Lineage and publication gates

The builder verified the frozen passed markers, audit identities, file
hashes, schemas, and source manifests for Stage A, Stage B, Stage C, and the
final Stage D artifact. It also verified the frozen S3 construction manifest.
Any mismatch stops publication.

The final Stage E audit identity is:

`stage-e-rq1-audit-eb62d71e3b89fd63833853e6a21ad306bdb637f4b8140bc57dc1fdbf572ecb24`

The passed marker binds that audit with SHA-256:

`e0b6e0e6bd559b25e2e33283e3d0782ac45c5f745f1f24b6a99887252be6c7eb`

## Published outputs

| Machine-readable output | Rows |
|---|---:|
| Result-unit register | 16 |
| Main metric table | 96 |
| Complete condition summaries | 156 |
| Paired-effect summaries | 182 |
| Interaction-effect summaries | 26 |
| Architecture effects | 16 |
| Architecture evidence codes | 16 |
| Existing selected bootstrap intervals | 30 |
| Strict transitions | 56 |
| Three-by-three semantic transitions | 126 |
| Evidence-to-answer conversion matrices | 756 |
| Evidence-to-answer compact summaries | 84 |
| Category effects | 224 |
| Category interactions | 32 |
| Process condition summaries | 312 |
| Process paired summaries | 364 |
| Figure 5.3 inputs | 32 |
| Table 5.3 inputs | 24 |
| One-time S3 construction record | 1 |
| Bounded trace evidence | 24 |
| Display-number register | 1,470 |

Figure 5.3 and Table 5.3 inputs are copied from the validated source stages
without changing their numeric contents. The Stage B bootstrap set remains
exactly 30 rows; no interval is added for E6−E5, a descriptive anchor, a
category subset, or a reviewed trace.

## Final prose reconciliation

The Section 5.2 draft was treated as provisional until the Stage E passed
marker existed. It was then reconciled against the display-number register and
rewritten as the final audited RQ1 section. The final pass made the following
reporting controls explicit:

- paired medians for F1, Strict Accuracy, and Soft Semantic Score are zero for
  every main simple comparison and the interaction;
- Partial Rate is retained but treated as neutral, with the complete
  three-by-three semantic transitions reserved for Appendix I;
- the `N=19` multi-source evidence changes are reported separately from the
  `N=58` evidence metrics;
- the four compact evidence-to-answer cells are shown but are explicitly
  labelled non-exhaustive;
- query-time model calls and tokens are not mislabeled as retrieval-only cost;
- failure-attempt counts are reported, while native latency and separately
  attributable failed-attempt tokens remain unavailable;
- LLM judge and token-overlap disagreement is preserved rather than collapsed
  into one score;
- complete-system S3 anchors are not described as pure curation effects.

## Final bounded findings for RQ1

1. **Storage organisation does not provide a general gain.** The main positive
   point estimate is Qwen E3−E1, concentrated in temporal questions. All
   storage F1 and Strict bootstrap intervals include or touch zero.
2. **R2 is more compact in recorded query-time calls and tokens but less
   effective in this experiment.** Its four raw-store comparisons use larger
   EvidenceBundles, cover less annotated evidence, and reduce both Strict and
   Soft outcomes. The comparison identifies the complete R2-versus-R1 system,
   not BM25 alone.
3. **No reliable storage--retrieval interaction is established.** The F1,
   Strict, and Soft interaction intervals include zero under both backbones,
   and category effects are heterogeneous.
4. **R3 does not improve access to the frozen S3 store relative to R1.** E6−E5
   has lower observed F1, Strict, Soft, and Evidence Recall means within each
   backbone while returning larger bundles.
5. **S3+R1 shows descriptive potential as a complete system.** E5−E3 raises
   semantic correctness and annotated-evidence coverage while lowering token
   F1. This is a complete-system anchor, not a causal estimate of curation.
6. **Evidence access and answer correctness are related but not
   interchangeable.** Repairs can occur without higher official Evidence
   Recall, and higher Evidence Recall can fail to improve the answer. The 24
   reviewed cases explain selected mechanisms but do not estimate prevalence.

## Interpretation boundaries

- Bootstrap intervals describe resampling stability across the observed 60
  questions, not variation across conversations.
- Qwen and DeepSeek results are placed side by side, but Stage E does not test
  cross-backbone stability.
- Category values are descriptive; C3 is especially small.
- Official evidence annotations are valid source locations, not necessarily a
  minimal or exhaustive proof set.
- R1 rounds and filesystem calls are not commensurate with R2/R3 actions.
- S3 locator coverage is not a direct measure of factual fidelity.
- Construction and process costs may explain behaviour here, but their value,
  amortisation, and practical trade-off are reserved for RQ6.

## Verification

The formal `build` and independent `audit` commands both passed. The Stage E
test module passed all six tests, including tamper rejection. The combined
Stage B--E regression suite passed 42 tests, and the final Stage A--E suite
passed all 46 tests. An independent prose audit also passed after checking the
published numbers, denominators, terminology, and RQ1 boundaries against the
formal artifacts. `git diff --check` reported no whitespace errors at the
formal publication gate.
