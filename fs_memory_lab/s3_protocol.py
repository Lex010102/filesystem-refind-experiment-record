"""Project-defined operational wrapper for S3 management episodes.

The paper publishes the system prompt, but not the exact user message that
wraps each chunk.  Keep that local choice separate, explicit, and hashable.
"""

from __future__ import annotations

import hashlib


S3_USER_WRAPPER_VERSION = "project-defined-s3-user-wrapper-v1"
S3_USER_INSTRUCTION = "Integrate this conversation chunk into the existing memory filesystem."
S3_USER_TEMPLATE = S3_USER_INSTRUCTION + "\n\n{chunk_payload}"

FROZEN_S3_USER_INSTRUCTION_SHA256 = (
    "67745e7c580625d5d2d84427ef92bef8c69d876ddb101a1746e4d108bb2ec3a3"
)
FROZEN_S3_USER_TEMPLATE_SHA256 = (
    "5c9e2854a7fc320202679d6cc7f28ee16024744be8ebdf5dadd66cfe6ffe217d"
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_s3_user_wrapper() -> None:
    actual_instruction = _sha256(S3_USER_INSTRUCTION)
    actual_template = _sha256(S3_USER_TEMPLATE)
    if actual_instruction != FROZEN_S3_USER_INSTRUCTION_SHA256:
        raise RuntimeError("S3 user instruction drifted")
    if actual_template != FROZEN_S3_USER_TEMPLATE_SHA256:
        raise RuntimeError("S3 user template drifted")


def render_s3_user_message(chunk_payload: str) -> str:
    if not isinstance(chunk_payload, str) or not chunk_payload:
        raise ValueError("S3 chunk payload must be a non-empty string")
    return S3_USER_INSTRUCTION + "\n\n" + chunk_payload


verify_s3_user_wrapper()
