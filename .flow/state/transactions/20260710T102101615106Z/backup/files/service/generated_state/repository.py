from __future__ import annotations

import subprocess
from pathlib import Path

from service.generated_state.common import GeneratedStateError, _validate_commit

def _resolve_revision(project_root: Path, ref: str, commit: str | None) -> str:
    if commit is not None:
        return _validate_commit(commit)
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"],
        cwd=project_root,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise GeneratedStateError(
            f"cannot resolve base ref {ref!r}; pass --base-commit explicitly"
        )
    return _validate_commit(completed.stdout)
