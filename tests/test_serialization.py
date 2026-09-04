from __future__ import annotations

import pytest

from pymaiml import serialization
from pymaiml.builders import LIFECYCLE_NS


def test_dumps_roundtrips_through_lxml(minimal_root):
    """dumps() output must be well-formed and carry the right root xsi:type."""
    lxml_etree = pytest.importorskip("lxml.etree")
    xml_text = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    root = lxml_etree.fromstring(xml_text.encode("utf-8"))
    assert root.tag == "{http://www.maiml.org/schemas}maiml"
    assert root.get("{http://www.w3.org/2001/XMLSchema-instance}type") == "maimlRootType"
    assert root.get("version") == "1.0"


def test_dumps_passes_schema_and_business_rule_validation(minimal_root, tmp_path):
    from pymaiml.validation import validate

    out = tmp_path / "sample.maiml"
    serialization.dump(minimal_root, out, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    result = validate(out)
    assert result.ok, result


def test_dumps_rejects_non_root_object():
    with pytest.raises(TypeError):
        serialization.dumps(object())


def test_loads_is_not_implemented_yet():
    with pytest.raises(NotImplementedError):
        serialization.loads("<maiml/>")
