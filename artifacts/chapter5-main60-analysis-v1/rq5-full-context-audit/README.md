# Chapter 5 RQ5 Full Context audit

This offline stage reviews the 14 unique Main-60 Full Context Strict-noncorrect questions. It updates only Full Context final-input sufficiency, long-context utilisation, and Answerer-utilisation states.

The diagnostic matrix aggregates the frozen 420 paired RQ4 comparisons over 60 questions. Its any-selective view is oracle-style, descriptive, and not deployable. Complete source visibility is not Evidence Recall.

The unique-question table prevents the 420 pairings from inflating the 60-answer denominator. All 60 Full Context records are bound to Stage A by file hash, canonical-payload hash, record ID, question identity, and bundle identity. Evidence-position diagnostics cover only the 58 questions with gold source annotations and never report Full Context Evidence Recall. Position is the zero-based global-turn ordinal divided by 567, not a character or token offset; midrange is the midpoint of the earliest and latest gold-turn positions.

The review supports failure-mechanism analysis only; repair mechanisms for Full-Context-only successes were not computed. This stage performs no evaluation and no primary-cause attribution.

Final post-stage register: `artifacts/chapter5-main60-analysis-v1/rq5-full-context-audit/root-cause-state-register-after-full-context.jsonl`.
