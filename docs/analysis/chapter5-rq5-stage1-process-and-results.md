# Chapter 5 RQ5 Section 5.6.1 Process and Results Record

## Status and purpose

Section 5.6.1 is complete and formally audited. It freezes the population and
the state contract for the later RQ5 root-cause analysis. It does not yet
assign any storage, retrieval, packaging, fusion, Answerer, Full Context, or
evaluation cause.

The machine-readable source of truth is:

`artifacts/chapter5-main60-analysis-v1/rq5-root-cause-index/`

Its passed marker is `RQ5-STAGE-1.PASSED`. The final audit identity is:

`rq5-stage-1-audit-f1a9efe44c178464f8e04ae9eb224585df8f76a512d29dd48ab428579b61f7b6`

No API or network call was made. No formal answer, score, trace, EvidenceBundle,
or Stage A row was changed.

## Frozen input and population

The builder reads only the frozen Stage A master table and the source-record
files named by that table. It verifies the fixed Stage A audit and manifest
identities, their pinned hashes, all 900 unique analysis-row IDs, all 900
unique source-record paths, and every source-record file hash.

The complete population is:

- Qwen E1–E7: 420 records;
- DeepSeek E1–E7: 420 records;
- DeepSeek-family Full Context: 60 records;
- total: 900 records.

The analytical unit in `case-index` is one evaluated answer path. The program
also groups rows into 120 `backbone × question` packets: 60 Qwen packets with
E1–E7 and 60 DeepSeek packets with E1–E7 plus Full Context.

## Strict-error definition and census

A Strict-noncorrect case is defined only as `strict_score == 0`. This includes
both Partial and Incorrect LLM-judge labels. It is not restricted to the
Incorrect label.

| Error partition | Count |
|---|---:|
| Partial | 74 |
| Incorrect | 176 |
| **Strict non-correct total** | **250** |
| Evidence-eligible | 233 |
| Evidence-ineligible | 17 |
| E1–E6 selective retrieval | 205 |
| E7 dual-source fusion | 31 |
| Full Context | 14 |

The 250 errors cover 33 unique question IDs. Fifty-eight of the 120
backbone-question packets contain at least one error: 27 Qwen packets and 31
DeepSeek packets. Correct rows in those packets remain available as
same-question counterfactual paths.

### Errors by condition

| Condition | Qwen | DeepSeek | Total |
|---|---:|---:|---:|
| E1 | 17 | 15 | 32 |
| E2 | 20 | 18 | 38 |
| E3 | 15 | 18 | 33 |
| E4 | 18 | 20 | 38 |
| E5 | 13 | 15 | 28 |
| E6 | 16 | 20 | 36 |
| E7 | 16 | 15 | 31 |
| Full Context | not run | 14 | 14 |

### Errors by question category

| Category | Count |
|---|---:|
| Multi-hop | 58 |
| Temporal | 60 |
| Open-domain | 59 |
| Single-hop | 73 |

These are error counts, not category-normalised error rates. The complete
condition–category–eligibility denominators are preserved in
`error-census.*`.

## Condition-specific root-cause chains

The root-cause model does not force all paths into one invalid sequence.

### E1–E6

```text
store availability
  → retriever reach
  → model observation
  → evidence retention
  → final-input sufficiency
  → Answerer utilisation
  → evaluation agreement
```

### E7

```text
E2 parent bundle + E6 parent bundle
  → fusion operation
  → fused-evidence retention
  → final-input sufficiency
  → Answerer utilisation
  → evaluation agreement
```

E7 performs no new retrieval. Every E7 case is linked to the same-question E2
and E6 case IDs, analysis-row IDs, and EvidenceBundle IDs.

### Full Context

```text
complete-history final input
  → final-input sufficiency
  → long-context utilisation
  → Answerer utilisation
  → evaluation agreement
```

Full Context has no retriever or selective EvidenceBundle. Evidence Recall,
Any-hit, and All-hit therefore remain not applicable.

## State initialisation and attribution boundary

The 250-row `root-cause-state-register` contains only two initial values for
stage states:

- `pending` when the state applies to that condition;
- `not_applicable` when it does not.

All 250 rows have `attribution_status = pending`, `primary_cause = pending`,
an empty secondary-cause list, and `attribution_strength = pending`.
`state-model.json` separately declares the permitted terminal states for each
stage, the primary-cause vocabulary, the E1–E6/E7/Full Context applicability
rules, and the earliest-supported-break rule.

The 17 evidence-ineligible errors pass record and question-identity checks but
have `gold_annotation_state = not_available`. They remain in Answerer and
evaluation analysis and are excluded from annotated-evidence attribution.

Evidence Recall is an observable coverage signal, not an automatic causal
label. A low value is not converted into a retrieval failure in this stage.

## Published outputs

| Output | Rows | Purpose |
|---|---:|---|
| `case-index.*` | 900 | Unified identifier, provenance, metric, and process index |
| `strict-error-cases.*` | 250 | Exact Strict-noncorrect population |
| `root-cause-state-register.*` | 250 | Condition-aware state skeleton with no assigned cause |
| `question-packets.*` | 120 | Same-backbone, same-question counterfactual grouping |
| `error-census.*` | 75 | Complete condition–category–eligibility denominators |
| `state-model.json` | — | State vocabulary, chains, applicability, and attribution contract |
| `denominator-audit.json` | — | Fixed counts and partition identities |
| `source-manifest.json` | — | Frozen Stage A lineage |
| `schema.json` | — | Field-level table schemas |
| `audit.json` | — | Independent reconstruction and content hashes |
| `RQ5-STAGE-1.PASSED` | — | Completion marker bound to the final audit |

Each tabular output is available as JSONL and CSV. Published rows contain
identifiers, hashes, metrics, and process counts only. They contain no
question, answer, evidence, prompt, rationale, or secret text.

## Verification

The implementation is `fs_memory_lab/chapter5_rq5_stage1.py`; regression and
tamper tests are in `tests/test_chapter5_rq5_stage1.py`.

The verification sequence was:

```text
python3 -m unittest tests.test_chapter5_rq5_stage1
python3 -m fs_memory_lab.chapter5_rq5_stage1 audit \
  --stage-a-dir artifacts/chapter5-main60-analysis-v1/stage-a \
  --output-dir artifacts/chapter5-main60-analysis-v1/rq5-root-cause-index
```

All 13 tests passed. The tests cover exact population reconstruction,
condition and backbone counts, E7 parent lineage, Full Context
non-applicability, state-chain applicability, deterministic output under
reversed input order, source path and hash rejection, exact file sets, and
tampered/missing/extra/symlink output rejection.

## Next analytical gate

Section 5.6.2 may now analyse store-level availability, fidelity, temporal
state, granularity, and provenance for S1–S3. It must update a new downstream
artifact rather than modify this immutable Section 5.6.1 index.
