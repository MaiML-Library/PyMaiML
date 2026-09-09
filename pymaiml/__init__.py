"""
PyMaiML -- MaiML (JIS K 0200) Python SDK.

This package builds on top of maiml_domain (the MaiML-Domain foundational
domain model: https://github.com/MaiML-Library/MaiML-Domain), which is
declared as a normal pip dependency in pyproject.toml (pinned to a released
git tag, not to a floating branch -- see README.md for why).

maiml_domain intentionally contains zero business-rule validation and no
XML (de)serialization -- see its own README for the rationale. Those
concerns live here, in the SDK layer, split across four modules:

  pymaiml.serialization
      Convert maiml_domain object trees to/from real MaiML XML: dumps/dump
      to write, loads/load to read -- see that module.

  pymaiml.validation
      Validate a .maiml/.maiml.zip/.mai file against the official
      MaiML-Schema-1_0 XSD (bundled) plus the supplementary business rules
      from the MaiML AI Common Specification that XSD alone can't express.

  pymaiml.builders
      Ergonomic helpers that reduce the boilerplate/mistakes of building a
      maiml_domain object tree by hand: unique id/uuid generation
      (IdFactory), property/content class inference from a Python value's
      type (infer_property/infer_content), and the
      lifecycle:transition="complete" event that validation's EVT-02 rule
      requires whenever <data> records a measurement (new_complete_event).

  pymaiml.query
      Read-only "what's in this file" utilities, in two families. Four
      "list the X" functions return flat lists of strings: get_uuids(),
      get_keys(), get_namespaces(), get_insertion_uris(). Two
      object-returning functions take keyword-argument filters instead:
      get_templates(xml_text, *, kind=None) and get_instances(xml_text,
      *, kind=None, instruction_id=None), returning the actual
      maiml_domain template/instance objects (id-only access is just
      [obj.id for obj in ...] on the result, not a separate function).
      Every function except get_namespaces() reads its answer off the
      maiml_domain object tree serialization.loads() builds (so the file
      must be schema-valid); get_namespaces() is the one exception and
      parses the XML directly, since namespace declarations have no
      maiml_domain representation at all.

Typical usage:

    import maiml_domain as m
    from pymaiml import serialization, validation
    from pymaiml.builders import IdFactory, infer_property, new_complete_event

    root = m.MaimlRootType(...)                 # build with maiml_domain + builders
    serialization.dump(root, "out.maiml", extra_namespaces={...})
    result = validation.validate("out.maiml")
    assert result.ok, result
"""
from __future__ import annotations

import maiml_domain  # noqa: F401  -- proves the dependency wiring works

from . import builders, query, serialization, validation  # noqa: F401,E402

__version__ = "0.1.0"

__all__ = ["__version__", "serialization", "validation", "builders", "query"]
