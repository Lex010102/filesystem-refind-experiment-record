# Chapter 6 General Discussion: Towards Evidence-Controlled Memory Systems

The results in Chapter 5 converge on one general problem. Information may exist in memory, become visible to the system, and still fail to support a reliable answer. Improving storage or retrieval alone cannot close every failure in this chain.

> **Central argument.** Long-term memory systems should be organised around explicit evidence control, rather than around storage or retrieval alone.

The chapter follows one argument:

> **evidence-conversion gap → Evidence Controller → staged evidence-access policy**

The staged policy begins with selective retrieval, adds another source only when needed, uses Full Context as recovery, and abstains when the evidence remains unsafe. The controller is a design proposal derived from the experiments, not a component implemented or evaluated in this study.

## 6.1 The Evidence-Conversion Gap

The principal gap lies between **information access** and **evidence readiness**. A conventional memory pipeline is often written as:

> memory store → retrieval → answer

This pipeline treats retrieved text as if it were already usable evidence. A more accurate chain is:

> stored information → accessible information → answer-ready evidence → correctly used evidence

Storage must preserve the required fact and its qualifiers. Retrieval must reach the appropriate source. Evidence packaging must retain the relevant entities, relations, time anchors, and context. The Answerer must then resolve and combine them correctly. Failure at any transition can produce the same incorrect answer.

Chapter 5 shows that these states cannot be collapsed. Decisive storage omission was not the dominant observed failure. Many error paths reached all annotated source locations, but the final EvidenceBundle was not always semantically sufficient. Some EvidenceBundles were sufficient but still produced an incorrect or unsupported answer. Full Context removed explicit retrieval selection without removing localisation, temporal ordering, cross-event composition, or Answerer utilisation failures. Dual-source fusion exposed complementary evidence, but extra evidence could also introduce repetition, competing states, or weaker focus.

The **evidence-conversion gap** is therefore the gap between information that a system stores or exposes and evidence that is sufficiently focused, coherent, and usable for the current question. It is not one more error label. It is the central transformation problem connecting storage, retrieval, packaging, and answering.

This changes the design objective. A memory system should preserve answer-bearing relationships, not only maximise stored content or retrieved matches. A Temporal question may require an ordered update rather than two independently relevant passages. A Multi-hop question may require an explicit connection between evidence items. A factual question may require one unambiguous entity--attribute relation. The best access path therefore depends on the question and the current evidence state, not only on the underlying store.

The general lesson is direct: memory quality must be judged by the complete conversion from historical information to usable evidence. This extends the emphasis on store shape and tool harnesses in Filesystem-Based Memory [4], the iterative access process in ReFind [6], and the distinction between retrieval and downstream utilisation in recent diagnostic work [7].

## 6.2 The Missing Architectural Layer: An Evidence Controller

The missing architectural component is an **Evidence Controller** between evidence access and the Answerer. It would inspect the question, the current EvidenceBundle, its provenance, and the remaining resource budget before deciding whether the system is ready to answer. It would not replace the memory store, Retrieval Agent, or Answerer. Its purpose would be to decide whether the present evidence justifies answering or requires another access action.

The controller would perform four functions.

**Sufficiency checking.** The controller would test whether the evidence covers the entities, relations, time constraints, and intermediate facts required by the question. A relevant passage is not necessarily a complete answer path.

**Conflict checking.** It would detect incompatible claims and competing temporal states. Rather than remove them through blind deduplication, it would compare their source and recency or seek disambiguating evidence.

**Provenance checking.** It would verify that answer-critical claims remain traceable to source records. This allows the system to distinguish a source event from a curated interpretation and to investigate disagreement between them.

**Action and stopping control.** It would choose whether to answer, continue searching, switch or add a source, fuse evidence, escalate to Full Context, or abstain. Stopping would depend on evidence readiness rather than only on an action cap or the presence of several matches.

The controller could not use gold answers, gold source turns, Evidence Recall, or LLM judge labels at deployment time. It would require observable proxies such as question decomposition, entity and time-slot coverage, cross-source agreement, provenance completeness, evidence novelty, and calibrated uncertainty. Chapter 5 uses gold evidence to diagnose completed runs; an online controller would have to estimate readiness without those annotations.

The resulting system would replace a one-way pipeline with a closed control loop:

> access evidence → inspect evidence state → choose the next action → answer or access again

The distinction from a Retrieval Agent is important. A Retrieval Agent decides how to search one store. An Evidence Controller decides whether the system should remain on that path at all. It coordinates access modes and stops further search when the evidence is already adequate. This avoids adding retrieval complexity when the main remaining risk is downstream utilisation.

## 6.3 Adaptive Evidence Access as a Control Policy

The controller should implement one clear policy: **select the least expansive access mode that can produce an adequate evidence state**. This turns selective retrieval, fusion, Full Context, and abstention into stages of one control process.

**Level 1: selective retrieval by default.** The system should begin with focused, traceable evidence. The exact storage--retrieval pairing may vary by backbone model and question type. The controller should stop at this level when the EvidenceBundle is sufficient and coherent.

**Level 2: multi-source fusion when complementarity is plausible.** A second source should be added only when the first path is incomplete and another representation may supply the missing relation, event, or temporal cue. Fusion must preserve source identity, remove redundancy without erasing distinct states, check conflicts, and control the combined budget. E7 demonstrates the opportunity and the risk: complementary evidence can repair an answer, but more evidence can also weaken focus.

**Level 3: Full Context as recovery.** The system should escalate when selective omission remains plausible, the question requires broad cross-session inspection, or retrieved fragments cannot be resolved locally. Full Context restores source visibility but is not an oracle. Localisation, temporal reasoning, composition, and Answerer utilisation can still fail.

**Abstention when evidence remains unsafe.** If evidence remains incomplete or irreconcilable, the system should abstain, expose the uncertainty, or request clarification rather than produce a falsely confident answer.

The four principal evidence states and their corresponding actions are summarised below.

**Table 6.1. Conceptual adaptive evidence-access policy.** The policy is a design implication, not an online routing procedure evaluated in the present experiments.

| Current evidence state | Controller action | Intended benefit | Required safeguard |
|---|---|---|---|
| Focused, coherent, and sufficient | Send the EvidenceBundle to the Answerer | Avoid unnecessary search and context growth | Retain answer-critical provenance |
| Partial, with a plausible complementary source | Query the alternative source or apply controlled multi-source fusion | Recover a missing relation, event, or temporal cue | Deduplicate, preserve source identity, and check conflicts |
| Selective omission remains plausible or broad cross-session inspection is required | Escalate to Full Context recovery | Restore complete source visibility | Recheck localisation, temporal order, and cross-event composition |
| Conflicting or insufficient after escalation | Abstain, flag uncertainty, or request clarification | Avoid an unsupported or falsely confident answer | Report the unresolved claims and their provenance |

The policy should be cost-aware but not cost-driven. Budgets can limit escalation, but they do not establish evidence sufficiency. Because the backbone model affects both retrieval behaviour and evidence utilisation, controller thresholds should be calibrated for the complete backbone pipeline rather than transferred unchanged between models.

The resulting principle is concise: **retrieval should be a controlled evidence-acquisition process, not a one-time preprocessing step**. The Evidence Controller would assess whether evidence is sufficient, coherent, and traceable, then choose the least expansive safe action. This proposal does not establish that one controller implementation will improve performance. It identifies the architectural problem exposed by the experiments and the most direct design response. Chapter 7 examines the limitations and validity threats that bound this conclusion.
