from __future__ import annotations

"""Compatibility facade for generated-state export and verification.

The implementation is split into repository, exporter and verifier modules so
Git resolution, file-system export and integrity verification remain cohesive.
"""

from service.generated_state.common import GeneratedStateError
from service.generated_state.exporter import export_generated_state
from service.generated_state.verifier import (
    load_generated_state_manifest,
    verify_generated_state,
)

__all__ = [
    "GeneratedStateError",
    "export_generated_state",
    "load_generated_state_manifest",
    "verify_generated_state",
]
