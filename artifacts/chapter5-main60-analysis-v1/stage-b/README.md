# Chapter 5 Stage B: E1--E4 raw 2x2 core

This directory contains the audited within-backbone paired analysis for the
E1--E4 raw-memory 2x2 experiment. It estimates four simple contrasts and the
storage--retrieval interaction separately for Qwen and DeepSeek.

Answer metrics use all 60 Main-60 questions. Evidence metrics use only the
fixed 58-question Evidence-eligible mask. `multi_gold_source_*` metrics are
explicitly restricted to the frozen 19-question subset with more than one
distinct annotated gold dialogue-turn ID; they are not a renamed All-hit
metric and are never mixed with the 58-question denominator.

The paired tables use fixed target-minus-baseline directions. Partial Rate and
EvidenceBundle length are neutral descriptive metrics, so they have raw
increase/same/decrease states but no quality-oriented win/tie/loss label.
Strict binary transitions use `not_correct` for all non-correct Judge labels;
the separate 3x3 semantic table preserves correct/partial/incorrect.

Bootstrap intervals use 10,000 complete-question-block resamples, seed
20261021, Type-7 percentile interpolation, and no missing-value imputation.
They describe resampling stability over the observed Main-60 questions only.

No API is called, no formal source result is modified, and no question,
reference answer, candidate answer, Evidence text, or Judge rationale is
stored. Stage C/D analyses and final RQ1 conclusions are outside this stage.
