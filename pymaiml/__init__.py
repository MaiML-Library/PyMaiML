"""
PyMaiML -- MaiML (JIS K 0200) Python SDK.

This package builds on top of maiml_domain (the MaiML-Domain foundational
domain model: https://github.com/MaiML-Library/MaiML-Domain), which is
declared as a normal pip dependency in pyproject.toml (pinned to a released
git tag, not to a floating branch -- see README.md for why).

maiml_domain intentionally contains zero business-rule validation and no
XML (de)serialization -- see its own README for the rationale. Those
concerns belong here, in the SDK layer:
  - constructing maiml_domain object trees from convenient, high-level APIs
  - serializing them to/from real .maiml XML
  - enforcing the business rules from the MaiML AI Common Specification that
    the domain model deliberately does not enforce (e.g. the EVT-01/02
    "complete" event requirement, reference-target type checking, etc.)
"""
from __future__ import annotations

import maiml_domain  # noqa: F401  -- proves the dependency wiring works

__version__ = "0.1.0"

__all__ = ["__version__"]
