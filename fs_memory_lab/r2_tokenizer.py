"""Frozen adapter for the tokenizer shipped by the official ReFind repository."""

from __future__ import annotations

from pathlib import Path

from .evidence import EvidenceValidationError, sha256_bytes
from .r2_protocol import R2_OFFICIAL_CODE_COMMIT
from .vendor.refind_tokenizer import STOPWORDS, PorterStemmer, Tokenizer


R2_TOKENIZER_ID = "refind-official-compact-porter"
R2_TOKENIZER_VERSION = R2_OFFICIAL_CODE_COMMIT
R2_TOKENIZER_SOURCE_SHA256 = (
    "111744fff0a766bb8248319f9d38294c9954d9d47b12c7be4c1dd8592609b9b6"
)


def tokenizer_source_path() -> Path:
    return Path(__file__).resolve().parent / "vendor/refind_tokenizer.py"


def tokenizer_source_sha256() -> str:
    return sha256_bytes(tokenizer_source_path().read_bytes())


def verify_r2_tokenizer() -> None:
    if tokenizer_source_sha256() != R2_TOKENIZER_SOURCE_SHA256:
        raise EvidenceValidationError(
            "Vendored ReFind tokenizer differs from the pinned official source"
        )
    if len(STOPWORDS) != 63:
        raise EvidenceValidationError("Vendored ReFind stopword set changed")


__all__ = [
    "STOPWORDS",
    "PorterStemmer",
    "R2_TOKENIZER_ID",
    "R2_TOKENIZER_SOURCE_SHA256",
    "R2_TOKENIZER_VERSION",
    "Tokenizer",
    "tokenizer_source_sha256",
    "verify_r2_tokenizer",
]
