from __future__ import annotations

"""Compatibility facade for the data-package validation subsystem.

Validation responsibilities live under :mod:`service.data_package.validation`.
This module keeps the historical import path stable for consumers and tests.
"""

from service.data_package.validation import (
    QualityGateError,
    inspect_package,
    validate_against_baseline,
    validate_package,
    write_snapshot,
)
from service.data_package.validation.cli import main
from service.data_package.validation.constants import DEFAULT_CONFIG_PATH

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "QualityGateError",
    "inspect_package",
    "validate_against_baseline",
    "validate_package",
    "write_snapshot",
]

if __name__ == "__main__":
    main()
