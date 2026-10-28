# Chapter 5 Stage D bounded trace-review casebook

This casebook records the 24 candidates frozen before source content was inspected. Findings are concise paraphrases. They explain selected cases and do not estimate global error prevalence or replace the later Stage E reconciliation.

## Review coverage

| Module | Backbone | Intended role | Question | Category | Primary mechanism | Confidence |
|---|---|---|---|---:|---|---|
| 5.2.1 | qwen | repair | `conv-50-q051` | C2 | metric_disagreement | medium |
| 5.2.1 | qwen | harm | `conv-50-q014` | C3 | local_expansion | high |
| 5.2.1 | qwen | counterexample | `conv-50-q023` | C1 | alternative_valid_evidence | high |
| 5.2.1 | deepseek | repair | `conv-50-q114` | C4 | evidence_utilisation | medium |
| 5.2.1 | deepseek | harm | `conv-50-q051` | C2 | metric_disagreement | medium |
| 5.2.1 | deepseek | counterexample | `conv-50-q052` | C2 | alternative_valid_evidence | high |
| 5.2.2 | qwen | repair | `conv-50-q051` | C2 | metric_disagreement | medium |
| 5.2.2 | qwen | harm | `conv-50-q014` | C3 | local_expansion | high |
| 5.2.2 | qwen | counterexample | `conv-50-q023` | C1 | alternative_valid_evidence | high |
| 5.2.2 | deepseek | repair | `conv-50-q114` | C4 | evidence_utilisation | medium |
| 5.2.2 | deepseek | harm | `conv-50-q069` | C2 | local_expansion | high |
| 5.2.2 | deepseek | counterexample | `conv-50-q024` | C1 | alternative_valid_evidence | high |
| 5.2.3 | qwen | repair | `conv-50-q022` | C3 | query_choice | high |
| 5.2.3 | qwen | harm | `conv-50-q051` | C2 | metric_disagreement | medium |
| 5.2.3 | qwen | counterexample | `conv-50-q024` | C1 | alternative_valid_evidence | high |
| 5.2.3 | deepseek | repair | `conv-50-q111` | C4 | metric_disagreement | medium |
| 5.2.3 | deepseek | harm | `conv-50-q051` | C2 | metric_disagreement | medium |
| 5.2.3 | deepseek | counterexample | `conv-50-q002` | C1 | metric_disagreement | high |
| 5.2.4 | qwen | repair | `conv-50-q069` | C2 | local_expansion | high |
| 5.2.4 | qwen | harm | `conv-50-q088` | C4 | evidence_utilisation | high |
| 5.2.4 | qwen | counterexample | `conv-50-q022` | C3 | alternative_valid_evidence | high |
| 5.2.4 | deepseek | repair | `conv-50-q046` | C1 | metric_disagreement | medium |
| 5.2.4 | deepseek | harm | `conv-50-q022` | C3 | evidence_utilisation | high |
| 5.2.4 | deepseek | counterexample | `conv-50-q054` | C1 | alternative_valid_evidence | high |

## Bounded findings

### 5.2.1|qwen|repair — `conv-50-q051`

- Observed case: metric_disagreement.
- Primary mechanism: metric_disagreement; secondary: indeterminate.
- Finding: No storage or retrieval gain explains this strict repair; the label flip is most consistent with semantic-judge sensitivity to the added early-October wording.
- Uncertainty: The source gives a relative week, while the reference uses a calendar-week phrase, so the exact boundary is intrinsically ambiguous.

### 5.2.1|qwen|harm — `conv-50-q014`

- Observed case: harm.
- Primary mechanism: local_expansion; secondary: query_choice.
- Finding: The harm arose after the relevant session had been reached: the E4 controller continued searching until the action cap and never converted the useful result into evidence.
- Uncertainty: One bounded trace cannot estimate how often this controller-action pattern occurs.

### 5.2.1|qwen|counterexample — `conv-50-q023`

- Observed case: counterexample.
- Primary mechanism: alternative_valid_evidence; secondary: indeterminate.
- Finding: Folder organisation increased annotated-source coverage, but the baseline already contained direct sufficient evidence, leaving no room for an answer-quality gain.
- Uncertainty: The gold set identifies source locations, not a minimal proof set, so full annotated recall is not required for this yes-or-no answer.

### 5.2.1|deepseek|repair — `conv-50-q114`

- Observed case: repair.
- Primary mechanism: evidence_utilisation; secondary: indeterminate.
- Finding: Both paths retained the annotated source, but only the foldered-path answer preserved the reference-level detail; the observed repair occurs after evidence access rather than through a storage-fidelity gain.
- Uncertainty: The baseline answer conveyed the central sensation in less specific wording, so the strict transition is partly sensitive to how narrowly the reference detail is enforced.

### 5.2.1|deepseek|harm — `conv-50-q051`

- Observed case: metric_disagreement.
- Primary mechanism: metric_disagreement; secondary: indeterminate.
- Finding: E2 and E4 both retained the same dated source and produced materially equivalent relative-date inferences, so the apparent storage harm is driven by inconsistent strict treatment of near-identical timing language.
- Uncertainty: The source states a relative week while the reference uses a calendar-week label; this boundary makes strict distinctions among the candidate phrasings fragile.

### 5.2.1|deepseek|counterexample — `conv-50-q052`

- Observed case: counterexample.
- Primary mechanism: alternative_valid_evidence; secondary: indeterminate.
- Finding: Folder organisation raised annotated recall from partial to complete, but the flat-store bundle already contained the dated source that was sufficient for the same correct answer.
- Uncertainty: The annotated set supplies corroborating locations rather than a proven minimal evidence set, so complete annotated recall was not necessary in this case.

### 5.2.2|qwen|repair — `conv-50-q051`

- Observed case: metric_disagreement.
- Primary mechanism: metric_disagreement; secondary: indeterminate.
- Finding: The apparent R2 repair is not supported by a retrieval-content difference; it is chiefly an evaluation-sensitive wording change in the final answer.
- Uncertainty: The reference calendar-week wording is not an exact restatement of the relative date in the source.

### 5.2.2|qwen|harm — `conv-50-q014`

- Observed case: harm.
- Primary mechanism: local_expansion; secondary: query_choice.
- Finding: With storage held fixed, the observed harm is a retrieval-controller failure to retain an already surfaced relevant result, not a storage omission.
- Uncertainty: The review establishes this case mechanism only; it is not a prevalence estimate for R2.

### 5.2.2|qwen|counterexample — `conv-50-q023`

- Observed case: counterexample.
- Primary mechanism: alternative_valid_evidence; secondary: indeterminate.
- Finding: R2 improved annotated coverage but not answer quality because R1's partial-gold bundle already directly answered the question.
- Uncertainty: Evidence Recall counts annotated locations rather than the minimum evidence needed for this answer.

### 5.2.2|deepseek|repair — `conv-50-q114`

- Observed case: repair.
- Primary mechanism: evidence_utilisation; secondary: indeterminate.
- Finding: R1 and R2 both supplied the exact annotated statement; the strict repair came from the R2-conditioned answer retaining a finer reference detail that the R1-conditioned answer paraphrased away.
- Uncertainty: Because the baseline still conveyed the main experience, this is an answer-specific utilisation change with a reference-specific strict boundary, not evidence that R2 uniquely found the fact.

### 5.2.2|deepseek|harm — `conv-50-q069`

- Observed case: harm.
- Primary mechanism: local_expansion; secondary: navigation_or_ranking.
- Finding: R2 reached the relevant late session but selected nearby car and blog exchanges without the adjacent acquisition-time turn; R1 included that turn, so the harm is a retrieval-selection near miss rather than a storage omission.
- Uncertainty: This trace identifies one local-expansion failure but cannot estimate its prevalence or isolate BM25 ranking from controller note selection.

### 5.2.2|deepseek|counterexample — `conv-50-q024`

- Observed case: counterexample.
- Primary mechanism: alternative_valid_evidence; secondary: metric_disagreement.
- Finding: R2 increased annotated coverage, but R1 had already retrieved a direct statement sufficient to identify the same passion; Strict stayed correct while token F1 moved in the opposite direction because the R2 answer was more expansive.
- Uncertainty: Annotated recall measures coverage of listed source turns rather than the minimum proof needed for this short-answer question.

### 5.2.3|qwen|repair — `conv-50-q022`

- Observed case: repair.
- Primary mechanism: query_choice; secondary: navigation_or_ranking.
- Finding: The positive difference-in-differences is driven by R2's different second query and selected results, not by a missing fact in S1; E4 reached a direct goal statement that E2 missed.
- Uncertainty: Because controller queries differ across single traces, this case cannot isolate folder organisation as the sole cause of the interaction.

### 5.2.3|qwen|harm — `conv-50-q051`

- Observed case: metric_disagreement.
- Primary mechanism: metric_disagreement; secondary: indeterminate.
- Finding: The negative interaction is an evaluation-sensitive answer-wording pattern rather than evidence loss or a storage-retrieval failure.
- Uncertainty: The temporal reference itself is not a clean calendar-equivalent of the relative statement, so strict distinctions among these answers are fragile.

### 5.2.3|qwen|counterexample — `conv-50-q024`

- Observed case: counterexample.
- Primary mechanism: alternative_valid_evidence; secondary: metric_disagreement.
- Finding: The positive Evidence DID does not convert to Strict because the lower-recall bundles already contain unannotated direct evidence sufficient for the same answer.
- Uncertainty: Gold locations are evidence anchors rather than an exhaustive set of all valid supporting turns.

### 5.2.3|deepseek|repair — `conv-50-q111`

- Observed case: metric_disagreement.
- Primary mechanism: metric_disagreement; secondary: evidence_utilisation.
- Finding: All four paths retained the annotated plan, and each answer conveyed the garage visit while omitting the same secondary project-idea detail; only E3 was labelled partial, so the positive interaction is not a clean retrieval or storage repair.
- Uncertainty: The answers differ in breadth, but the judge applied the missing-detail criterion inconsistently, making the single-case difference-in-differences label unstable.

### 5.2.3|deepseek|harm — `conv-50-q051`

- Observed case: metric_disagreement.
- Primary mechanism: metric_disagreement; secondary: indeterminate.
- Finding: The four bundles all retained the same temporal source and the answers made closely equivalent week-before inferences; the negative interaction is therefore a judge-sensitive wording pattern rather than an evidence-access interaction.
- Uncertainty: The source-relative date and reference calendar-week wording are not exact equivalents, so the strict labels do not support a stable mechanistic contrast.

### 5.2.3|deepseek|counterexample — `conv-50-q002`

- Observed case: counterexample.
- Primary mechanism: metric_disagreement; secondary: navigation_or_ranking.
- Finding: E1 and E3 achieved complete annotated-turn recall, yet their bundles exposed only coarse purchase descriptions and omitted attributes required by the reference; official Evidence Recall therefore overstated answer sufficiency.
- Uncertainty: The omitted attributes appear outside the reviewed annotated-turn text, so this case cannot separate annotation incompleteness from retrieval of an insufficient but officially complete evidence set.

### 5.2.4|qwen|repair — `conv-50-q069`

- Observed case: repair.
- Primary mechanism: local_expansion; secondary: navigation_or_ranking.
- Finding: The curated path repaired a raw-chat near miss by co-locating the blog context with the adjacent acquisition-time fact; the relevant fact survived the near-limit E6 package.
- Uncertainty: This complete-system comparison cannot separate curation from its adapted retriever as independent causes.

### 5.2.4|qwen|harm — `conv-50-q088`

- Observed case: harm.
- Primary mechanism: evidence_utilisation; secondary: packaging_or_budget.
- Finding: The failure occurs after successful storage, retrieval, and packaging: broader E6 context distracts the Answerer from the relevant car-related statement.
- Uncertainty: The bundle is below budget, so the secondary packaging label denotes distractor composition rather than truncation or budget loss.

### 5.2.4|qwen|counterexample — `conv-50-q022`

- Observed case: counterexample.
- Primary mechanism: alternative_valid_evidence; secondary: indeterminate.
- Finding: Curated memory improves annotated coverage and coherence in this case, but the raw foldered baseline already contains enough evidence for a correct answer.
- Uncertainty: The case shows answer-quality saturation, not that the additional curated evidence is generally valueless.

### 5.2.4|deepseek|repair — `conv-50-q046`

- Observed case: metric_disagreement.
- Primary mechanism: metric_disagreement; secondary: alternative_valid_evidence.
- Finding: Both curated paths retrieved the annotated shared activity and both answers stated it; the apparent repair comes from penalising E5 for several additional evidence-backed shared interests while accepting a smaller extra interest in E6.
- Uncertainty: The reference is non-exhaustive for a plural question, and the judge's treatment of supported extra activities is inconsistent, so this is not a clean access-system repair.

### 5.2.4|deepseek|harm — `conv-50-q022`

- Observed case: harm.
- Primary mechanism: evidence_utilisation; secondary: packaging_or_budget.
- Finding: Neither path hit the official source IDs, but both bundles contained an alternative direct statement of the goal; E4 used it correctly, whereas E6 overlooked it inside a near-limit, distractor-heavy package.
- Uncertainty: The secondary mechanism concerns evidence composition, not truncation: the alternative support survived the E6 budget even though other items were skipped.

### 5.2.4|deepseek|counterexample — `conv-50-q054`

- Observed case: counterexample.
- Primary mechanism: alternative_valid_evidence; secondary: indeterminate.
- Finding: Curated memory increased annotated recall from one of two source turns to both, but the foldered R1 bundle already contained the explicit support-system statement needed for the same correct answer.
- Uncertainty: This shows saturation for one item, not that the additional curated source is generally unnecessary.

## Sample composition (not prevalence)

The following counts describe only the preselected review sample:

- `alternative_valid_evidence`: 7 cases
- `evidence_utilisation`: 4 cases
- `local_expansion`: 4 cases
- `metric_disagreement`: 8 cases
- `query_choice`: 1 cases

No cross-backbone stability claim, E7 analysis, Full Context comparison, global failure census, Pareto ranking, system recommendation, or final RQ1 conclusion is made by this bounded casebook.
