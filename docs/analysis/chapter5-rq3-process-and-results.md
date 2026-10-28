# Chapter 5 RQ3 Process and Results Record

## Status and purpose

RQ3 is complete and formally audited. It evaluates whether E7 benefits from
combining the E2 raw-dialogue EvidenceBundle with the E6 curated-memory
EvidenceBundle. It also identifies when fusion preserves, repairs, or harms a
Strict-correct parent result.

The machine-readable source of truth is
`artifacts/chapter5-main60-analysis-v1/rq3-dual-source-fusion/`. Its passed
marker is `RQ3.PASSED`. The final audit identity is:

`rq3-audit-e0ac8fc4a256b4fa5d016871163fc19243e99a9328985568b48b73ee35586378`

No API or network call was made. No formal answer, score, trace, EvidenceBundle,
or Stage A row was changed. The analysis computed no new bootstrap interval,
p-value, or causal error label.

## Frozen inputs and E7 contract

The program reads the audited Stage A E1--E7 table and filters exactly 360
rows: two backbones, three conditions, and 60 questions. These rows form 120
ordered `(E2, E6, E7)` triples. Pairing requires the same question ID,
question hash, global position, category, evidence-eligibility state, and gold
source IDs.

For every triple, the audit verifies that:

- E2 is S1+R2 and E6 is S3+R3;
- E7 is the fixed fusion of E2 and E6 rather than a third retriever;
- E7 records the ordered E2 and E6 parent EvidenceBundle IDs;
- each parent has a 16,000-character budget and E7 has a 32,000-character
  total budget;
- E7 performs zero new search actions;
- E7 source IDs equal the union of the two parent source-ID sets;
- E7 EvidenceBundle item and character counts equal the parent sums;
- E7 retrieval calls and tokens are the inherited parent-retrieval sums;
- E7 uses one new shared Answerer call after the inherited retrieval work.

The last two points are important. E7's recorded retrieval cost is not zero.
It carries the cost of obtaining both parent bundles. “No new retrieval” means
that fusion itself runs no additional search action.

## Calculation 1: E7 relative to each parent

Every effect is paired by question and defined as:

```text
E7 score - parent score
```

Answer-quality denominators are 60. Evidence Recall uses only the 58 questions
with annotated source IDs.

| Backbone | Parent | ΔPrecision | ΔRecall | ΔF1 | ΔStrict | ΔSoft | ΔEvidence Recall |
|---|---|---:|---:|---:|---:|---:|---:|
| Qwen | E2 | -0.0425 | +0.0194 | -0.0340 | +0.0667 | +0.0417 | +0.1178 |
| Qwen | E6 | -0.0028 | -0.0131 | -0.0122 | 0.0000 | 0.0000 | +0.0632 |
| DeepSeek | E2 | +0.0408 | +0.0341 | +0.0398 | +0.0500 | +0.0917 | +0.0977 |
| DeepSeek | E6 | +0.0498 | +0.1280 | +0.0614 | +0.0833 | +0.0917 | +0.1695 |

The overall fusion effect is backbone-dependent. Under DeepSeek, E7 improves
all five reported answer metrics, as well as Evidence Recall, relative to both
individual parents. Under Qwen, E7 improves Strict Accuracy and Soft Semantic
Score relative to E2, but reduces lexical F1; relative to E6, semantic
accuracy is unchanged and F1 is slightly lower. Both backbones obtain higher
annotated Evidence Recall from the fused source union.

## Calculation 2: semantic transitions

The program retains all incorrect, partial, and correct Judge transitions.
This prevents a Strict-only view from hiding partial-credit movement. The
complete 3-by-3 matrices are published in `judge-transitions.*`.

The main Strict transitions, shown as parent-correct/E7-correct,
parent-correct/E7-wrong, parent-wrong/E7-correct, and both wrong, are:

| Backbone | Parent | 1→1 | 1→0 | 0→1 | 0→0 |
|---|---|---:|---:|---:|---:|
| Qwen | E2 | 39 | 1 | 5 | 15 |
| Qwen | E6 | 41 | 3 | 3 | 13 |
| DeepSeek | E2 | 39 | 3 | 6 | 12 |
| DeepSeek | E6 | 38 | 2 | 7 | 13 |

These parent-specific transitions explain why E7 can improve over each single
parent while still failing to preserve every question that either parent
answered correctly.

## Calculation 3: Repair, Preserve, Harm, and Unresolved

The four mutually exclusive states use Strict Accuracy only:

- **Repair:** E2 and E6 are wrong, while E7 is correct;
- **Preserve:** at least one parent is correct, and E7 is correct;
- **Harm:** at least one parent is correct, while E7 is wrong;
- **Unresolved:** both parents and E7 are wrong.

| Backbone | Repair | Preserve | Harm | Unresolved |
|---|---:|---:|---:|---:|
| Qwen | 1 | 43 | 4 | 12 |
| DeepSeek | 3 | 42 | 4 | 11 |

The descriptive parent oracle—correct whenever E2 or E6 is correct—would
answer 47 Qwen questions and 46 DeepSeek questions correctly. E7 answers 44
and 45 correctly. Therefore, relative to this unattainable oracle, E7 has a
net balance of `Repair - Harm = -3` questions for Qwen and `-1` for DeepSeek.
This does not contradict the positive DeepSeek E7-minus-parent effects. It
shows that deterministic fusion captures much, but not all, of the parents'
complementary correctness.

Conditional on both parents being wrong, the Repair rate is 1/13 (7.69%) for
Qwen and 3/14 (21.43%) for DeepSeek. Conditional on at least one correct
parent, the Harm rate is 4/47 (8.51%) and 4/46 (8.70%), respectively.

## Calculation 4: parent correctness profiles and complementarity opportunity

| Backbone | Both correct | E2 only | E6 only | Neither correct |
|---|---:|---:|---:|---:|
| Qwen | 37 | 3 | 7 | 13 |
| DeepSeek | 36 | 6 | 4 | 14 |

The asymmetric parent cells demonstrate real complementarity: E2 and E6 do
not fail on exactly the same questions. However, complementarity defines
opportunity rather than guaranteed fusion gain. E7 must still select and use
the combined evidence correctly.

These profiles are defined by parent answer correctness, not by evidence-set
overlap. Evidence-source complementarity is analysed separately below.

## Calculation 5: source-ID overlap and annotated evidence coverage

The overlap unit is a retrieved dialogue source ID, not evidence text. The
mean E2/E6 source-ID Jaccard is 0.1956 under Qwen and 0.1587 under DeepSeek.
The two paths therefore retrieve largely different source sets.

For the one Qwen question where both parent source-ID sets are empty, the
program uses the standard identical-empty-set Jaccard convention of 1.0 and
retains the zero union count in the question-level diagnostic table. This
convention is fixed in the analysis code and included in the reported mean.

| Backbone | E2 Evidence Recall | E6 Evidence Recall | Union/E7 Evidence Recall | Mean source-ID Jaccard | Questions with either parent's unique gold coverage |
|---|---:|---:|---:|---:|---:|
| Qwen | 0.7816 | 0.8362 | 0.8994 | 0.1956 | 14/58 |
| DeepSeek | 0.7974 | 0.7256 | 0.8951 | 0.1587 | 19/58 |

For both backbones, the source union reaches complete annotated coverage on
49 of 58 eligible questions. Across 82 annotated source occurrences per
backbone, the Qwen partition is 53 shared, 7 E2-only, 11 E6-only, and 11
missing. The DeepSeek partition is 48 shared, 13 E2-only, 10 E6-only, and 11
missing.

Low source-ID overlap supports the existence of different access paths, but
it is not proof of semantic complementarity or conflict. Most eligible
questions contain no marginal annotated source from either parent: 44/58 for
Qwen and 39/58 for DeepSeek. Automatic results therefore identify candidate
mechanisms; RQ5 trace review must confirm them.

## Calculation 6: category analysis

Category results are descriptive. Answer denominators are 13 multi-hop, 13
temporal, 7 open-domain, and 27 single-hop. Evidence denominators are 13, 13,
5, and 27.

### Qwen

- Multi-hop shows the clearest semantic gain: E7 gains +0.1538 Strict versus
  E2 and +0.0769 versus E6. It produces one Repair and no Harm, although F1
  decreases relative to both parents.
- Temporal fusion raises Evidence Recall strongly versus E2 (+0.2308), but
  does not improve Strict or Soft versus E2. This is an access-to-utilisation
  mismatch candidate, not yet a causal diagnosis.
- Single-hop contains three of the four Qwen Harm cases and no Repair. Extra
  evidence is least useful in this group under the current fusion rule.
- Open-domain has only seven answers and five evidence-eligible questions, so
  its apparent improvements remain exploratory.

### DeepSeek

- Temporal is the clearest fusion-success category: two Repair cases, one
  Harm case, +0.1538 Strict versus E2, and +0.2308 versus E6.
- Multi-hop has one Repair and one Harm. F1 increases relative to both
  parents, while the semantic effect depends on the selected parent metric.
- Single-hop has no Repair and one Harm. E7 is better than E6 but essentially
  ties E2 on Strict Accuracy.
- Open-domain has one Harm and no Repair. F1 rises, but Strict falls relative
  to E2, illustrating lexical--semantic disagreement in a small subgroup.

## Answer to RQ3

Dual-source fusion is useful but conditional. It raises annotated Evidence
Recall under both backbones because E2 and E6 retrieve different source sets.
DeepSeek converts this extra access into consistent overall gains relative to
both individual parents. Qwen gains semantic quality only relative to E2,
ties E6 semantically, and loses lexical F1.

The question-level state analysis gives a stricter qualification. E7 repairs
some cases—especially DeepSeek temporal questions—but harms four cases under
each backbone and remains below the descriptive parent oracle. The current
deterministic fusion should therefore be described as a backbone- and
question-type-dependent method, not as a universally superior replacement
for both parents.

## Interpretation boundaries

- E7 is fixed fusion of reused E2/E6 evidence, not a third retrieval method.
- The parent oracle is descriptive and unattainable; it is not a baseline
  system score.
- Repair, Preserve, Harm, and Unresolved use Strict Accuracy only.
- Category findings are exploratory, especially open-domain results.
- Source-ID Jaccard is not evidence-text overlap or proof of conflict.
- Annotated source IDs are evidence locations, not complete reasoning chains.
- Harm identifies possible-interference candidates; RQ5 performs causal trace
  review.
- RQ3 does not rank cost. The full online cost of E7 belongs to RQ6.

## Published outputs

| Output | Rows | Purpose |
|---|---:|---|
| `parent-effects.*` | 4 | Overall E7-minus-E2/E6 effects |
| `category-effects.*` | 16 | Effects by backbone, category, and parent |
| `judge-transitions.*` | 36 | Complete 3-by-3 semantic transition matrices |
| `fusion-outcomes.*` | 8 | Overall Repair/Preserve/Harm/Unresolved counts |
| `fusion-outcome-summary.*` | 2 | Parent-oracle, conditional-rate, and net summaries |
| `fusion-outcomes-by-category.*` | 32 | Four outcomes within each category |
| `parent-complementarity.*` | 8 | E2/E6 Strict-correctness profiles |
| `evidence-source-overlap.*` | 2 | Source-ID and annotated-coverage summary |
| `question-diagnostics.*` | 120 | Publication-safe paired numeric records |
| `rq5-candidate-cases.*` | 12 | Repair/Harm identifiers deferred to RQ5 |
| `table-5-14-inputs.*` | 4 | Compact report-facing effect table |
| `figure-5-6-inputs.*` | 16 | Parent-profile-to-E7 flow inputs |

Every table is published as CSV and canonical JSONL. The directory also
contains `README.md`, `schema.json`, `source-manifest.json`, `audit.json`, and
`RQ3.PASSED`.

## Verification

The formal builder and independent audit both passed. Twelve RQ3 tests cover
the 360-row source scope, 120 paired triples, all numerical anchors, parent
bundle identities, no-new-search rule, inherited retrieval accounting,
budgets, category denominators, semantic transitions, outcome partitions,
source-ID overlap, RQ5 candidates, forbidden text fields, output hashes,
tamper rejection, extra-file rejection, and atomic destination handling.

The combined Stage A, Stage E-RQ1, RQ2, and RQ3 regression run passed all 31
tests.
