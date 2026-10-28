# Chapter 5 RQ5 Section 5.6.2 Storage Audit: Process and Results

## Status and analytical purpose

Section 5.6.2 is complete and formally audited. It asks what S1, S2, and S3
preserve, remove, reorganise, or make difficult to access **before** a
retrieval failure or an Answerer failure is assigned. The machine-readable
source of truth is:

`artifacts/chapter5-main60-analysis-v1/rq5-storage-audit/`

The passed marker is `RQ5-STORAGE-AUDIT.PASSED`. The final audit identity is:

`rq5-storage-audit-5ff8638baf55d3e678e266ade364aafd6076e0d89c1193aad05b59bda631f5eb`

No API or network call was made. No formal store, answer, retrieval trace,
EvidenceBundle, score, or Section 5.6.1 record was changed.

## Units, evidence order, and causal boundary

The primary unit is `question × store`: 60 questions for each of S1, S2, and
S3, giving 180 rows. Fifty-eight questions have official evidence locators,
giving 174 evidence-eligible question-store rows. Store diagnoses were frozen
before the 720 E1–E6 answer outcomes were joined.

The audit uses three evidence sources in this order:

1. deterministic structural checks of the canonical records and frozen stores;
2. outcome-blind semantic review of S2 routing and S3 fact preservation;
3. descriptive linkage to answer, evidence, and error outcomes after the
   storage labels were fixed.

This order prevents a wrong answer from being used as proof that the store was
wrong. It also separates two concepts that must not be conflated:

- **source-to-store fidelity:** whether the store faithfully represents the
  information available in its declared source;
- **reference-support sufficiency:** whether that source is itself sufficient
  and unambiguous for the benchmark reference answer.

Gold-locator presence is treated as provenance coverage, not as proof that the
required entity, relation, time, or granularity survived.

## S1: flat raw sessions

### Structural fidelity

S1 contains 30 session files, 568 turns, 125 BLIP captions, and 114,456 bytes.
All 568 rendered records preserve the declared speaker, text, BLIP caption,
locator, `dia_id`, session ordering, and chronology.

This is complete fidelity to the **frozen text-plus-caption renderer**, not to
every field in the canonical record. The renderer excludes `img_url`,
`query`, and `re-download`.

| Renderer-scope diagnostic | Count | Denominator | Rate |
|---|---:|---:|---:|
| Canonical turns with any excluded media field | 99 | 568 | 17.43% |
| Gold-locator associations touching an excluded field | 26 | 82 | 31.71% |
| Eligible questions touching an excluded field | 25 | 58 | 43.10% |
| Gold-locator associations with excluded `query` metadata | 21 | 82 | 25.61% |
| Eligible questions touching excluded `query` metadata | 20 | 58 | 34.48% |

All 99 image-bearing turns retain a BLIP caption. Therefore, field exclusion
is a risk indicator rather than an automatic semantic-loss label. Image URLs
and operational download metadata are not treated as answer facts by default.

One shared representation insufficiency was directly verified. For q002, the
reference requires a precise vehicle model that appears only in a canonical
`media.query` field outside the official gold locators. The frozen renderer
removes that field, and the retained text and caption contain only a generic
vehicle description. This limitation is inherited by S1, S2, S3, E7, and Full
Context. It is therefore a **shared renderer/source-scope limitation**, not an
S1-specific storage defect.

### Evidence dispersion

The main S1 burden is navigation across flat, chronologically separated raw
sessions.

| Dispersion diagnostic | Result |
|---|---:|
| Questions with more than one gold locator | 19/58 (32.76%) |
| Questions with cross-session gold evidence | 17/58 (29.31%) |
| Cross-session global-turn span | mean 116.65; median 103; range 8–256 |
| Cross-session date span | mean 50.53 days; median 41; range 3–113 |

The burden is category-dependent:

| Category | Evidence-eligible questions | Cross-session questions |
|---|---:|---:|
| Multi-hop | 13 | 12 (92.31%) |
| Temporal | 13 | 3 (23.08%) |
| Open-domain | 5 | 2 (40.00%) |
| Single-hop | 27 | 0 |

This supports a structural conclusion: S1 makes multi-session composition a
common burden for multi-hop questions. It does not prove that every intervening
turn is a distractor or that dispersion causes a specific answer error.

The outcome linkage is also non-monotonic. Cross-session evidence has lower
mean Evidence Recall under R2 for both backbones, but R1 Strict Accuracy is not
lower on the same group. The result suggests that dispersion affects access,
especially ranked raw-chat retrieval, while alternative support and Answerer
behaviour can break a simple Evidence-Recall-to-correctness relationship. The
retrieval trace needed to assign those cases is deferred to Section 5.6.3.

The audit does not publish a distractor-density or lexical-opacity number. Gold
locators are evidence anchors, not exhaustive relevance labels, and no frozen
question-turn relevance or synonym codebook exists. Calling every unlabelled
turn a distractor would be invalid.

## S2: foldered raw sessions

### Content equivalence and structural potential

All 30 S2 files are byte-identical to their S1 counterparts. S1 and S2 have the
same 568 turns, 125 captions, 114,456 bytes, and content identity:

`5a58a8cca8616b91f3c231671271f6dbbedc669330b91e410980223ad2488ad8`

Only the paths and directory layout differ. The four directories contain 14
music sessions, 11 car sessions, three travel sessions, and two photography
sessions.

Fifty of the 58 eligible questions have all gold-bearing sessions in one
folder. Eight require more than one folder. Among the 17 cross-session
questions, nine remain within one folder and eight cross folders.

If an oracle already knew every folder containing gold evidence, the candidate
load would be 12.793 of 30 sessions on average, with median 14 and range 2–25.
This is a theoretical mean reduction of 57.36%. It is reported as **oracle
folder concentration**, not actual retriever discoverability. Six cross-folder
questions require the two largest folders and therefore retain 25 of 30
sessions even under this oracle.

### Outcome-blind semantic routing audit

Because one complete session is assigned to only one dominant topic, content
equivalence does not guarantee that every local fact is well signposted. The
audit therefore reviewed all 79 `question × gold-bearing session` units without
using model outputs.

| Routing label | Units | Rate |
|---|---:|---:|
| Aligned | 55 | 69.62% |
| Partially aligned | 6 | 7.59% |
| Misleading | 18 | 22.78% |
| Ambiguous | 0 | 0.00% |

At the question level:

| Question routing class | Questions | Rate |
|---|---:|---:|
| All gold-bearing sessions aligned | 36 | 62.07% |
| Partial alignment but no misleading session | 5 | 8.62% |
| At least one misleading gold-bearing session | 17 | 29.31% |

| S2 folder | Aligned | Partial | Misleading | Total |
|---|---:|---:|---:|---:|
| cars-and-auto-work | 23 | 0 | 10 | 33 |
| music-and-performance | 25 | 4 | 7 | 36 |
| photography | 4 | 0 | 1 | 5 |
| travel-and-outdoors | 3 | 2 | 0 | 5 |

These 18 misleading units are not missing facts. They are local subtopics
inside sessions whose dominant theme points elsewhere. S2 is therefore
lossless at the file level but imperfect as a semantic routing index.

### Descriptive outcome linkage

E3−E1 is the direct S2-versus-S1 navigation contrast under R1. The fixed
routing labels do not show a monotonic relationship with the score change.

| Backbone | S2 question class | N | ΔStrict | Strict W/T/L | ΔSoft | ΔF1 |
|---|---|---:|---:|---:|---:|---:|
| Qwen | All aligned | 36 | +0.028 | 3/31/2 | +0.028 | +0.060 |
| Qwen | Partial, no misleading | 5 | 0.000 | 0/5/0 | 0.000 | +0.005 |
| Qwen | At least one misleading | 17 | +0.059 | 2/14/1 | +0.029 | +0.031 |
| DeepSeek | All aligned | 36 | −0.056 | 0/34/2 | −0.069 | −0.018 |
| DeepSeek | Partial, no misleading | 5 | 0.000 | 0/5/0 | 0.000 | +0.008 |
| DeepSeek | At least one misleading | 17 | −0.059 | 1/14/2 | −0.029 | +0.021 |

The direction changes by backbone and does not become consistently worse in
the misleading group. The semantic route audit therefore identifies a real
access risk, but it does not establish that the risk caused the observed answer
changes. Action-level folder use, inspected-file breadth, and first relevant
observation must be tested in Section 5.6.3.

E4−E2 is not interpreted as an S2 organisation effect because R2 consumes the
same raw exchange index and does not use the S2 path hierarchy.

## S3: Agent-Curated Memory

### Global structure and provenance

S3 contains two files, 35 H2 groups, 390 fact units, 472 lines, and 304,640
bytes. It is 2.662 times the size of S1. S3 is therefore a reorganised and
expanded representation, not a globally compressed store.

The S3 body contains 1,459 locator mentions and 555 of the 568 unique source
locators (97.71%). The 13 missing locators are not Main-60 gold locators. All
68 unique Main-60 gold locators are present, so all 58 eligible questions have
complete locator-level provenance.

However, provenance can be coarse. Among 164 gold-linked fact units, the
median number of locators is three, the 90th percentile is 13, and the maximum
is 43. Twenty-eight units contain more than eight locators.

The apparent 41/58 one-unit co-location rate is dominated by the 39 questions
that have only one gold locator. Among the 19 multi-locator questions:

| Multi-locator provenance diagnostic | Questions | Rate |
|---|---:|---:|
| All gold locators in one fact unit | 2/19 | 10.53% |
| All gold locators in one H2 group | 15/19 | 78.95% |
| All gold locators in one S3 file | 19/19 | 100.00% |

Thus S3 often brings related evidence into a shared topic section, but it does
not usually collapse a multi-evidence answer into one fact unit.

### Two-axis semantic audit

The S3 review used two outcome-blind passes. For each eligible question, it
compared canonical source records with every gold-linked fact unit and then
searched the whole S3 body for alternate support. The published table records
the path, line range, content hash, and source locators of the reviewed units.

**Axis 1: fidelity to the declared source**

| Source-to-store state | Questions | Rate |
|---|---:|---:|
| Faithful to source | 51 | 87.93% |
| Compressed but source-faithful | 5 | 8.62% |
| Source conflict faithfully preserved | 1 | 1.72% |
| Shared renderer detail loss | 1 | 1.72% |
| Curator-introduced decisive omission or distortion | 0 | 0.00% |

**Axis 2: support for the benchmark reference**

| Reference-support state | Questions | Rate |
|---|---:|---:|
| Sufficient | 50 | 86.21% |
| Partial | 4 | 6.90% |
| Available but conflicting | 1 | 1.72% |
| Source/reference entity mismatch | 3 | 5.17% |

The axes change the interpretation. Three of the four partial-support cases
faithfully preserve an under-specified source; the fourth inherits the shared
renderer loss. They are not evidence that S3 curation removed a valid fact.
The single conflict case preserves competing source accounts instead of
creating a new contradiction.

### Descriptive answer conversion

Reference support is strongly associated with answer success. Across E5 and
E6, both backbones are Strict-incorrect on all 16 answer paths belonging to the
four partial-support questions. This is not a curator effect: all four gaps
originate before or outside S3 curation.

| Backbone | Condition | Reference support | N | Strict | Soft | F1 | Evidence Recall |
|---|---|---|---:|---:|---:|---:|---:|
| Qwen | E5 | Sufficient | 50 | 0.860 | 0.880 | 0.424 | 0.913 |
| Qwen | E6 | Sufficient | 50 | 0.840 | 0.860 | 0.419 | 0.860 |
| DeepSeek | E5 | Sufficient | 50 | 0.820 | 0.860 | 0.272 | 0.957 |
| DeepSeek | E6 | Sufficient | 50 | 0.740 | 0.770 | 0.233 | 0.742 |
| Qwen | E5 | Partial | 4 | 0.000 | 0.250 | 0.082 | 1.000 |
| Qwen | E6 | Partial | 4 | 0.000 | 0.125 | 0.115 | 0.750 |
| DeepSeek | E5 | Partial | 4 | 0.000 | 0.250 | 0.081 | 1.000 |
| DeepSeek | E6 | Partial | 4 | 0.000 | 0.125 | 0.088 | 0.750 |

The contrast also demonstrates why locator coverage alone is insufficient.
The partial-support group can have high locator-based Evidence Recall while the
stored/source information still lacks the reference-level fact.

The conflict and entity-mismatch cells contain only one and three questions,
respectively. Their observed scores are retained in the artifact but are not
used for a general claim.

## Storage attribution across the 250-error register

The 205 E1–E6 Strict-noncorrect paths comprise 70 S1 paths, 71 S2 paths, and 64
S3 paths. Many occur when the relevant store state is unambiguously available:

| Store | Selective Strict-noncorrect paths | Unambiguously available | Partial support | Source/reference mismatch | Conflict | No gold evidence |
|---|---:|---:|---:|---:|---:|---:|
| S1 | 70 | 41 | 14 | 10 | 0 | 5 |
| S2 | 71 | 41 | 15 | 10 | 0 | 5 |
| S3 | 64 | 37 | 16 | 6 | 1 | 4 |

These are repeated answer-path counts, not independent storage defects. They
show that store availability alone cannot explain most errors; they do not yet
identify whether the remaining break occurs in retrieval, packaging, evidence
use, or evaluation.

The q002 shared renderer limitation appears in 12 E1–E6 error paths, equal to
6.28% of 191 evidence-eligible selective errors and 5.85% of all 205 selective
errors. Including E7 and Full Context, 14 of the 250 Strict-noncorrect paths
belong to this question. These are paths **exposed** to a verified upstream
insufficiency, not 12 or 14 independent defects. A DeepSeek E7 path still
answers the question correctly despite the missing precise fact, so the audit
records the upstream limitation as direct but leaves its path-level causal
sufficiency unestablished.

The defensible storage-level totals are therefore:

- one question with a verified shared renderer/source-scope insufficiency;
- zero verified S1-, S2-, or S3-specific decisive omissions;
- zero verified curator-introduced decisive omissions or distortions;
- substantial access-structure burdens that require retrieval-trace analysis
  before an answer error can be assigned to them.

## Main conclusions for Section 5.6.2

1. **S1 is faithful but structurally demanding.** It fully preserves the
   declared text-plus-caption representation, but nearly one third of eligible
   questions span sessions, especially multi-hop questions.
2. **S2 is content-lossless but not semantically lossless as an index.** Its
   files are identical to S1, yet 18 of 79 local answer-bearing session units
   sit under a misleading dominant-topic folder. The folders create potential
   concentration, not guaranteed retrieval benefit.
3. **S3 changes organisation more than global size.** It expands the store by
   2.662×, repeats provenance, and usually groups multi-evidence questions at
   the H2 level rather than the fact-unit level.
4. **S3 curation is highly source-faithful in this test set.** The audit finds
   no curator-introduced decisive loss. Apparent partial cases arise from the
   shared renderer or source/reference problems.
5. **Provenance coverage is necessary but not sufficient.** S3 includes all
   68 unique gold locators, yet four questions still have only partial
   reference support.
6. **Storage-specific omission is not the dominant observed bottleneck.** Most
   Strict-noncorrect paths occur with information available in the store. The
   next audit must locate the break between source reach, observation,
   retention, EvidenceBundle construction, and Answerer use.

## Interpretation limits

- The results cover one LoCoMo conversation and the unified Main-60 set.
- S2 routing labels measure topic cue quality, not actual R1 behaviour.
- Gold locators are sparse evidence anchors, not exhaustive relevance labels.
- No distractor-density or lexical-opacity statistic is reported without a
  frozen relevance and synonym codebook.
- Outcome linkages are descriptive associations after outcome-blind storage
  labels; they are not causal estimates.
- The audit command deterministically reconstructs and hash-checks the same
  declared computation. It is a tamper and reproducibility check, not a second
  independent algorithm.

## Published outputs and verification

| Output | Rows | Purpose |
|---|---:|---|
| `store-integrity.*` | 3 | Store-level size, structure, locator, and identity checks |
| `s1-s2-equivalence.*` | 30 | Byte and body identity for matched sessions |
| `s2-routing.*` | 60 | Question-level folder burden and oracle concentration |
| `s2-routing-session-review.*` | 79 | Outcome-blind semantic routing labels |
| `s3-fact-preservation.*` | 60 | Two-axis fidelity, provenance, and review references |
| `storage-fidelity.*` | 180 | Frozen `question × store` register |
| `storage-outcome-linkage.*` | 720 | Post-freeze descriptive E1–E6 outcome linkage |
| `case-storage-linkage.*` | 205 | Storage state linked to selective Strict errors |
| `root-cause-state-register-after-storage.*` | 250 | Section 5.6.1 register after storage-stage update |
| `storage-summary.*` | 379 | Explicit numerator, denominator, value, and unit rows |

JSONL and CSV versions are published for every table. Public rows contain no
question, answer, evidence, prompt, rationale, or secret text.

The implementation is `fs_memory_lab/chapter5_rq5_storage.py`; tests are in
`tests/test_chapter5_rq5_storage.py`. The final verification sequence was:

```text
python3 -m unittest tests.test_chapter5_rq5_storage tests.test_chapter5_rq5_stage1
python3 -m fs_memory_lab.chapter5_rq5_storage \
  --audit-only \
  --output-dir artifacts/chapter5-main60-analysis-v1/rq5-storage-audit
```

All 22 tests passed. The artifact then passed deterministic reconstruction,
CSV/JSONL parity, source-hash, denominator, review-census, store-equivalence,
forbidden-field, and completion-marker checks.
