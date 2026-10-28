# Chapter 5 Stage D Formal Protocol

## Status and purpose

Stage D is the mechanism-analysis phase of RQ1. It explains the already
audited Stage B and Stage C effects without changing any formal experiment,
answer, retrieval trace, score, or earlier analysis artifact.

The stage has two gates:

1. **Stage D automatic phase:** build the evidence-to-answer, category, and
   process tables and freeze deterministic trace-review candidates.
2. **Stage D bounded review phase:** inspect only the frozen candidates with a
   fixed review order and record bounded mechanism findings.

The automatic phase may publish `STAGE-D-AUTO.PASSED`. The final
`STAGE-D.PASSED` marker is reserved for the point at which the bounded trace
review and the final Stage D audit are both complete.

No API call is permitted. The stage is read-only with respect to the formal
Qwen, DeepSeek, Judge, Stage A, Stage B, and Stage C results.

## Frozen lineage

Stage D must verify the following lineage before calculation:

- Stage A audit ID:
  `stage-a-audit-5f55ec411f097df7206fdae5e71742641aa8868b4128ac32262f034877a1d7f3`;
- Stage B audit ID:
  `stage-b-audit-2c5061c3db5cba00f099648963eaa2175d1136954e4cf673720423e7ffed6932`;
- Stage C audit ID:
  `stage-c-audit-a199de52d8b0011d837334e6dbf37bbfac446653753b5b74a35732ae32da1a31`;
- Stage C audit SHA-256:
  `fef87f523a6850c0fd1a7940a1aceb526e2c94f6ff3722d9b400c49ea063ea5a`.

The 720-row Stage A RQ1 view is the source for category, process, condition,
and question-level values. The Stage B and Stage C question-level tables are
the authoritative source for their already audited paired effects. Joins use
exact deterministic identities, including backbone, condition or contrast,
and `question_id`; every joined row must retain or verify its Stage A
`analysis_row_id` lineage.

## Frozen comparison register

All simple differences use `target - baseline` and remain separated by
backbone model.

### Main simple comparisons

1. E3-E1: raw storage organisation under R1;
2. E4-E2: raw storage organisation under R2;
3. E2-E1: retrieval-system effect on S1;
4. E4-E3: retrieval-system effect on S2;
5. E6-E5: access-system effect on the same S3 store;
6. E5-E3: descriptive R1 complete-system anchor;
7. E6-E4: descriptive representation-adapted complete-system anchor.

E5-E3 and E6-E4 must always retain their complete-system labels. They are not
pure estimates of curation.

### Interaction

The storage-retrieval interaction is retained separately as:

```text
(E4 - E2) - (E3 - E1)
```

It is not treated as an eighth simple comparison. Both algebraically
equivalent difference-in-differences forms must continue to agree.

### Appendix sensitivity comparisons

- E5-E1;
- E6-E2.

These remain appendix-only sensitivity anchors and must not be mixed into the
main seven-comparison summaries.

## D0: input gate and denominator contract

Stage D must stop before publication unless all Stage A-C markers, audit IDs,
hashes, schemas, and source identities pass. It must preserve these fixed
denominators:

- answer outcomes: 60 questions per condition and comparison;
- Evidence outcomes: the shared 58-question eligible mask;
- multi-source Evidence outcomes: the shared 19-question subset;
- categories for answer outcomes: C1=13, C2=13, C3=7, C4=27;
- categories for Evidence outcomes: C1=13, C2=13, C3=5, C4=27.

Main-60 is one unified test set. Stage D must not partition it by construction
history or use an old/new split.

## D1: comparison and data-contract materialisation

The automatic artifact must publish a machine-readable register that records:

- comparison ID, target, baseline, backbone, and publication role;
- causal or descriptive interpretation status;
- eligible metrics and denominator;
- the source Stage B or Stage C paired table and exact source identity;
- whether a row is main, interaction, or appendix sensitivity output.

No question text, reference answer, candidate answer, Evidence text, Judge
rationale, or secret may appear in the automatic machine-readable tables.

## D2: Evidence-to-answer conversion

For each main simple comparison and backbone, Stage D must cross the change in
Evidence access with the change in answer quality.

### Primary matrix

The primary matrix is:

```text
Evidence Recall: decrease / same / increase
by
Strict outcome: decline / same / improve
```

It uses only the 58 Evidence-eligible questions. The nine cells must sum to
58 for every backbone-comparison unit. From the full matrix, derive at least:

- Evidence improves and Strict improves;
- Evidence improves but Strict does not improve;
- Evidence is unchanged while Strict improves;
- Evidence declines without corresponding Strict harm.

### Supporting matrices

- Evidence Recall change by token F1 change;
- Evidence Recall change by Soft Semantic Score change;
- All-hit state or transition by Strict transition;
- Any-hit state or transition by Strict transition as a supplemental view;
- multi-source coverage transitions on the fixed 19-question subset.

The interaction, if shown in mechanism tables, must use a separate
difference-in-differences sign matrix. It must not be forced into the simple
comparison transition interpretation.

These tables describe association. They do not prove that an Evidence change
caused an answer change.

## D3: category mechanism matrices

For each backbone and C1-C4 category, Stage D must report the six core RQ1
effects and keep the two complete-system anchors visibly separate. The main
category metrics are:

- token F1;
- Strict Accuracy;
- Soft Semantic Score as supporting semantic evidence;
- Evidence Recall on the eligible category denominator.

The storage-retrieval interaction receives its own category table. E5-E1 and
E6-E2 receive a separate appendix sensitivity table.

Category tables are descriptive. No new category-level bootstrap or category
significance claim is permitted. C3 must be interpreted especially cautiously
because it contains seven answer questions and five Evidence-eligible
questions.

## D4: process summaries

For E1-E6 and for each permitted comparison, report process quantities that
help explain the architectural effects:

- query, retrieval, and answer model calls;
- prompt, completion, and total tokens by stage;
- provider request attempts and failed-attempt counts;
- failed-attempt tokens as a separate quantity;
- EvidenceBundle characters and item count;
- answer characters and normalised answer tokens;
- search depth using the native unit of each retriever.

R1 provider rounds and filesystem tool calls must remain distinct from R2/R3
controller actions. They are not a common unit and must not be directly
subtracted as if equivalent.

Native per-answer latency for E1-E7 is unavailable and must remain explicitly
`N/A`. Stage D must not infer latency from event timestamps. Successful query
totals must not silently absorb failed-attempt tokens. Stage D does not rank
cost efficiency or construct a Pareto frontier; those tasks belong to RQ6.

## D5: deterministic bounded trace-review candidates

Candidate selection occurs before any candidate content is inspected. It must
be deterministic, reproducible, and stable under rerun, with ties resolved by
the frozen global question position and then `question_id`.

The candidate register must cover all four RQ1 analysis modules:

1. storage organisation;
2. retrieval-system effects;
3. storage-retrieval interaction and category heterogeneity;
4. Agent-Curated Memory complete-system effects.

Each module must include at least one repair case, one harm case, and one
counterexample or metric-disagreement case. The resulting register therefore
contains at least 12 module-by-role slots. Coverage across both backbones,
condition families, and C1-C4 should be maximised without changing the frozen
selection rules after viewing content.

The automatic candidate file contains identifiers, selection role, metric
pattern, source paths, hashes, and review status only. It does not copy source
text into the public table.

## D6: bounded trace review

Each frozen candidate must be reviewed in this order:

1. question and reference answer;
2. annotated gold source turns;
3. declared memory-store content;
4. retrieval trace and native search actions;
5. evidence selection, fusion, and budget handling;
6. final EvidenceBundle and candidate answer;
7. token metrics and LLM-judge label;
8. bounded mechanism finding and uncertainty note.

The review records whether the case is most consistent with storage fidelity,
navigation or ranking, query choice, local expansion, packaging or budget,
evidence utilisation, alternative valid evidence, metric disagreement, or an
indeterminate mechanism. These are case explanations, not prevalence
estimates. The global error-stage census belongs to RQ5.

## D7: audit and publication

The automatic audit must independently recompute every table and verify:

- all comparison roles and fixed directions;
- every 60/58/19 denominator;
- every category subtotal and full-table total;
- agreement with all relevant Stage B and Stage C paired effects, transitions,
  and interaction values;
- complete separation of main, interaction, and appendix sensitivity outputs;
- explicit native-unit labels and missing-latency status;
- absence of prohibited text-bearing or secret fields;
- deterministic candidate selection and byte-identical reconstruction.

After these checks it may write `STAGE-D-AUTO.PASSED`, with the review status
still recorded as `pending`.

The final Stage D audit additionally verifies that every frozen candidate was
reviewed, no unregistered case was substituted, review sources match their
hashes, and conclusions remain within the Stage D scope. Only then may it
write `STAGE-D.PASSED`.

## Explicit exclusions

Stage D must not compute or claim:

- formal cross-backbone stability or model-dependence conclusions (RQ2);
- E7 fusion effects (RQ3);
- Full Context comparisons (RQ4);
- a complete failure-stage distribution or error census (RQ5);
- Pareto ranking, amortised deployment cost, or final recommendation (RQ6);
- a final RQ1 narrative before the later Stage E reconciliation;
- a new bootstrap analysis;
- any result split between the original 40 and added 20 questions.

## Expected automatic outputs

The exact filenames are fixed by the implementation schema, but the automatic
artifact must contain, at minimum:

- comparison register;
- Evidence-to-answer question table and aggregate matrices;
- hit-state and multi-source conversion tables;
- category simple-effect tables;
- category interaction tables;
- appendix sensitivity category tables;
- process condition and paired summaries;
- deterministic trace-review candidate register;
- schema, source manifest, audit, README, and `STAGE-D-AUTO.PASSED`.

The final bounded-review artifact adds the completed review register,
casebook, final audit, and `STAGE-D.PASSED` without overwriting Stage A-C.
