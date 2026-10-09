# Vendored compatibility code

## ReFind tokenizer

`refind_tokenizer.py` is copied byte-for-byte from:

- Repository: <https://github.com/imlrz/ReFind>
- Commit: `a80175ca0eeb52a938d7cab7a602bc780de8a577`
- Upstream path: `app/tokenizer.py`
- SHA-256: `111744fff0a766bb8248319f9d38294c9954d9d47b12c7be4c1dd8592609b9b6`
- License: the upstream MIT license saved as `ReFind-LICENSE`

## LoCoMo-compatible Porter stemmer

`locomo_porter.py` is a compact, dependency-free compatibility adaptation of
NLTK 3.8.1 `nltk/stem/porter.py`, default `NLTK_EXTENSIONS` mode.

- Upstream project: https://github.com/nltk/nltk
- Upstream tag: `3.8.1`
- Source path: `nltk/stem/porter.py`
- Downloaded upstream source SHA-256: `40797f3ce2d69f3a8d816eaef26d0d9a0cb0b373b77230a7e2de39a6f1e25ea6`
- License: Apache License 2.0 (NLTK), saved as `NLTK-LICENSE`
- Purpose: reproduce the stemming used by the pinned official LoCoMo evaluator
  without adding a runtime dependency.

On 2026-10-09 the compatibility implementation was compared against the upstream
3.8.1 class for all 13,178 distinct English tokens occurring in the frozen LoCoMo
JSON plus canonical Porter examples; zero output differences were found.

The NLTK-derived compatibility code is governed by NLTK's Apache License 2.0;
`ReFind-LICENSE` applies only to the ReFind-derived tokenizer.
