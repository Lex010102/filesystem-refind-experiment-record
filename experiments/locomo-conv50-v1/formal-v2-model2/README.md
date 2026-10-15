# formal-v2-model2

`manifest.json` is the machine-readable source of truth for the frozen Model 2
main-60 experiment. It binds `formal-v2-model2-main60-candidate-02` to
implementation commit `95986c3588f404526d7f0aa0235030643e430007`, requested
alias `x-test-2`, and required served model `deepseek-v4.1-flash`.

Freeze manifest ID:
`formal-v2-model2-freeze-05bd1fbe832c471f20c5c855823d46c88e66601788391730f52ac04697fd79e8`.

The dev-6 pilot passed with 36/36 retrieval outputs and 42/42 answers. The
formal suite contains 60 questions, seven conditions, 420 planned records, and
12 serial batches. Main-40 runs first in eight local batches; extension-20 runs
second in four local batches; the combined pre-gold verifier runs last.

During answer generation, semantic gold and Judge calls are forbidden. This
freeze contains no API credential, question text, evidence, answer, or gold.
Any substantive method correction requires a new formal version and complete
reruns of affected conditions; records from different versions must not be
mixed.

Human-readable provenance and operating constraints are recorded in
`docs/reproduction/formal-v2-model2-freeze.md`.
