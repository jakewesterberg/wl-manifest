"""The wl.yaml contract: schema, host selectors, and a single-package check."""

from __future__ import annotations

from wl_manifest.check import CheckFinding, check_file, check_mapping, has_errors
from wl_manifest.hosts import HOST_CLASSES, HostSelector
from wl_manifest.models import (
    STABILITIES,
    STAGES_WITH_REPO,
    Artifact,
    Consumption,
    Lifecycle,
    PackageClass,
    PackageManifest,
    Requirement,
    Status,
    ThirdPartyDep,
    Visibility,
    _Tolerant,
)

__all__ = [
    "CheckFinding", "check_file", "check_mapping", "has_errors",
    "HOST_CLASSES", "HostSelector", "STABILITIES", "STAGES_WITH_REPO",
    "Artifact", "Consumption", "Lifecycle",
    "PackageClass", "PackageManifest", "Requirement", "Status", "ThirdPartyDep",
    "Visibility",
    "_Tolerant",
]
