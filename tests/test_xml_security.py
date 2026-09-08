"""
Regression tests for the untrusted-XML parser hardening in
pymaiml._xml_security (resolve_entities=False, no_network=True), and for
the fact that pymaiml.validation._load_schema() -- which compiles the
bundled, trusted MaiML-Schema-1_0 *.xsd files and legitimately needs
<xs:import>/<xs:include> resolution between them -- deliberately keeps a
separate, unhardened parser path rather than sharing the hardened one.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from pymaiml import serialization, validation
from pymaiml._xml_security import make_untrusted_input_parser

SECRET = "xxe-canary-3f9a1c2b"


def _external_entity_payload(target_uri: str) -> bytes:
    """A document that -- if the parser substituted external entities --
    would inline `target_uri`'s content into the root element's text."""
    return f"""<?xml version="1.0"?>
<!DOCTYPE maiml [<!ENTITY xxe SYSTEM "{target_uri}">]>
<maiml xmlns="http://www.maiml.org/schemas"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:type="maimlRootType" version="1.0">&xxe;</maiml>
""".encode("utf-8")


def test_hardened_parser_does_not_substitute_external_file_entities(tmp_path: Path) -> None:
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text(SECRET, encoding="utf-8")

    payload = _external_entity_payload(secret_file.as_uri())
    doc = etree.fromstring(payload, parser=make_untrusted_input_parser())

    assert SECRET not in etree.tostring(doc, encoding="unicode")
    assert (doc.text or "") == ""


def test_hardened_parser_does_not_attempt_network_fetches() -> None:
    # 192.0.2.0/24 is the RFC 5737 TEST-NET-1 block, reserved for
    # documentation/examples and guaranteed non-routable -- if no_network
    # were NOT honoured, resolving this would hang or fail slowly instead
    # of simply leaving the entity unexpanded.
    payload = _external_entity_payload("http://192.0.2.1/should-never-be-fetched")
    doc = etree.fromstring(payload, parser=make_untrusted_input_parser())
    assert "should-never-be-fetched" not in etree.tostring(doc, encoding="unicode")


def test_validate_does_not_crash_or_leak_secret_on_external_entity_payload(tmp_path: Path) -> None:
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text(SECRET, encoding="utf-8")

    maiml_file = tmp_path / "malicious.maiml"
    maiml_file.write_bytes(_external_entity_payload(secret_file.as_uri()))

    # Not a structurally valid MaiML document (root has bare text content),
    # so findings are expected -- the point is that validate() never raises
    # and never echoes the secret file's content back in a finding.
    result = validation.validate(maiml_file)
    assert not result.ok
    assert SECRET not in result.to_json()
    assert SECRET not in str(result)


def test_loads_does_not_crash_or_leak_secret_on_external_entity_payload(tmp_path: Path) -> None:
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text(SECRET, encoding="utf-8")

    payload = _external_entity_payload(secret_file.as_uri())
    try:
        serialization.loads(payload)
    except Exception as exc:  # noqa: BLE001 -- any parse/structure error is fine here
        assert SECRET not in str(exc)
    else:
        pytest.fail("loads() accepted a non-MaiML payload; expected it to raise")


def test_valid_file_still_loads_and_validates_after_hardening(minimal_root, tmp_path: Path) -> None:
    """The hardening must not break ordinary, well-formed MaiML input."""
    from pymaiml.builders import LIFECYCLE_NS

    out = tmp_path / "sample.maiml"
    serialization.dump(minimal_root, out, extra_namespaces={"lifecycle": LIFECYCLE_NS})

    result = validation.validate(out)
    assert result.ok
    assert result.errors == []

    loaded = serialization.loads(out.read_bytes())
    assert loaded.root.document.id == minimal_root.document.id


def test_load_schema_still_compiles_bundled_schema_with_local_imports() -> None:
    """_load_schema() must keep resolving <xs:import>/<xs:include> between
    the bundled schema files -- i.e. it must NOT have been switched onto
    the hardened untrusted-input parser, which is a different concern."""
    schema = validation._load_schema(validation._BUNDLED_SCHEMA_DIR)
    assert isinstance(schema, etree.XMLSchema)
