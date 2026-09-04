from __future__ import annotations

from pymaiml import serialization, validation
from pymaiml.builders import LIFECYCLE_NS


def test_valid_file_has_no_errors(minimal_root, tmp_path):
    out = tmp_path / "sample.maiml"
    serialization.dump(minimal_root, out, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    result = validation.validate(out)
    assert result.ok
    assert result.errors == []


def test_evt02_fires_when_complete_event_is_missing(minimal_root, tmp_path):
    """Break the lifecycle:transition="complete" property key and confirm
    validation actually catches it (not just a trivially-always-passing
    stub)."""
    out = tmp_path / "broken.maiml"
    xml_text = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    xml_text = xml_text.replace("lifecycle:transition", "lifecycle:not-transition")
    out.write_text(xml_text, encoding="utf-8")

    result = validation.validate(out)
    assert not result.ok
    assert any(f.code == "EVT-02" for f in result.errors)


def test_result_to_dict_and_json_roundtrip(minimal_root, tmp_path):
    import json

    out = tmp_path / "sample.maiml"
    serialization.dump(minimal_root, out, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    result = validation.validate(out)
    parsed = json.loads(result.to_json())
    assert parsed["valid"] is True
    assert parsed["errors"] == []
