"""Tests for pymaiml.query -- the independent, read-only "list the X used
in this file" utilities (get_uuids/get_keys/get_namespaces/
get_insertion_uris). These operate directly on XML text, not via
serialization.loads(), so most tests here use small hand-built XML
snippets rather than a full maiml_domain object tree -- only enough
structure to exercise each function's own parsing logic."""
from __future__ import annotations

import os
import tempfile

import pytest

from pymaiml import query, serialization
from pymaiml.builders import LIFECYCLE_NS


# ---------------------------------------------------------------------------
# get_uuids()
# ---------------------------------------------------------------------------

def test_get_uuids_preserves_document_order_and_keeps_duplicates():
    """Unlike get_keys()/get_insertion_uris(), get_uuids() does NOT
    deduplicate: a repeated uuid is itself a fact worth surfacing (two
    objects sharing an identity that is supposed to be unique), so every
    occurrence is reported, in document order, duplicates included."""
    xml = """<root>
  <a><uuid>11111111-1111-1111-1111-111111111111</uuid></a>
  <b><uuid>22222222-2222-2222-2222-222222222222</uuid></b>
  <c><uuid>11111111-1111-1111-1111-111111111111</uuid></c>
</root>
"""
    assert query.get_uuids(xml) == [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "11111111-1111-1111-1111-111111111111",
    ]


def test_get_uuids_ignores_empty_or_whitespace_only_uuid_elements():
    xml = "<root><uuid>   </uuid><uuid></uuid><uuid>abc</uuid></root>"
    assert query.get_uuids(xml) == ["abc"]


def test_get_uuids_finds_uuids_in_a_real_dumps_output(minimal_root):
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    uuids = query.get_uuids(xml)
    assert str(minimal_root.document.content.uuid) in uuids


# ---------------------------------------------------------------------------
# get_keys()
# ---------------------------------------------------------------------------

def test_get_keys_collects_key_from_every_element_kind_and_dedupes():
    """key= appears on <property>/<content>/<chain>/<parent> -- see
    pymaiml.serialization._write_property_or_content/_write_chain_or_parent."""
    xml = """<root>
  <property key="ex:temperature">1</property>
  <content key="ex:series"/>
  <chain key="ex:c1"/>
  <parent key="ex:p1"/>
  <property key="ex:temperature">2</property>
</root>
"""
    assert query.get_keys(xml) == ["ex:temperature", "ex:series", "ex:c1", "ex:p1"]


def test_get_keys_finds_the_lifecycle_complete_marker_in_a_real_dumps_output(minimal_root):
    """minimal_root's only property is the lifecycle:transition="complete"
    marker new_complete_event() attaches (EVT-02) -- get_keys() must find
    it via the same generic key= attribute scan as the hand-built cases
    above, not a property/content-specific code path."""
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    assert query.get_keys(xml) == ["lifecycle:transition"]


# ---------------------------------------------------------------------------
# get_namespaces()
# ---------------------------------------------------------------------------

def test_get_namespaces_excludes_default_namespace_and_xsi():
    xml = (
        '<maiml xmlns="http://www.maiml.org/schemas" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:KYL="http://example.org/kyl" '
        'xmlns:lifecycle="http://www.xes-standard.org/lifecycle.xesext">'
        "</maiml>"
    )
    assert query.get_namespaces(xml) == {
        "KYL": "http://example.org/kyl",
        "lifecycle": "http://www.xes-standard.org/lifecycle.xesext",
    }


def test_get_namespaces_scans_the_whole_tree_not_only_the_root():
    """Unlike LoadedMaiml.namespaces (root <maiml> element only -- fine for
    pymaiml's own dumps() output, since ElementTree's serializer hoists
    every namespace URI used anywhere in the tree to a root declaration),
    get_namespaces() must also pick up a namespace declared deep in the
    tree: exactly what an externally-signed file's
    <ds:Signature xmlns:ds="..."> looks like before any pymaiml dumps()
    round trip has a chance to hoist it (dumps() itself never emits a
    <Signature> at all -- see dumps()'s docstring -- so a file with one is
    necessarily from outside pymaiml)."""
    xml = (
        '<maiml xmlns="http://www.maiml.org/schemas">'
        '<document id="d1">'
        '<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#">'
        "<ds:SignedInfo/></ds:Signature>"
        "</document>"
        "</maiml>"
    )
    assert query.get_namespaces(xml) == {"ds": "http://www.w3.org/2000/09/xmldsig#"}


def test_get_namespaces_raises_on_conflicting_prefix_bindings():
    xml = (
        "<root>"
        '<a xmlns:ex="http://example.org/a"/>'
        '<b xmlns:ex="http://example.org/b"/>'
        "</root>"
    )
    with pytest.raises(ValueError, match="conflicting declarations for xmlns:ex"):
        query.get_namespaces(xml)


def test_get_namespaces_result_is_reusable_as_dumps_extra_namespaces(minimal_root, tmp_path):
    """The result should be a drop-in for dumps(..., extra_namespaces=...),
    matching LoadedMaiml.namespaces's documented usage pattern."""
    xml1 = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    namespaces = query.get_namespaces(xml1)
    assert namespaces == {"lifecycle": LIFECYCLE_NS}
    xml2 = serialization.dumps(minimal_root, extra_namespaces=namespaces)
    assert xml1 == xml2


# ---------------------------------------------------------------------------
# get_insertion_uris()
# ---------------------------------------------------------------------------

def test_get_insertion_uris_dedupes_and_preserves_order():
    xml = """<root>
  <insertion><uri>file:///a.csv</uri></insertion>
  <insertion><uri>file:///b.csv</uri></insertion>
  <insertion><uri>file:///a.csv</uri></insertion>
</root>
"""
    assert query.get_insertion_uris(xml) == ["file:///a.csv", "file:///b.csv"]


def test_get_insertion_uris_skips_an_insertion_with_no_uri_child():
    xml = "<root><insertion><format>text/csv</format></insertion></root>"
    assert query.get_insertion_uris(xml) == []


def test_get_insertion_uris_returns_empty_list_when_none_present(minimal_root):
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    assert query.get_insertion_uris(xml) == []


# ---------------------------------------------------------------------------
# Shared: all four functions must use the hardened untrusted-input parser.
# ---------------------------------------------------------------------------

def test_get_uuids_does_not_resolve_external_file_entities(tmp_path):
    """query.py is exactly the kind of "just list what's in this file"
    utility that gets pointed at untrusted/uploaded input -- it must go
    through the same pymaiml._xml_security hardening as
    serialization.loads(), not a bare/default-config lxml parser."""
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("xxe-canary-query-9f2c", encoding="utf-8")

    payload = (
        '<?xml version="1.0"?>'
        f'<!DOCTYPE root [<!ENTITY xxe SYSTEM "{secret_file.as_uri()}">]>'
        "<root><uuid>&xxe;</uuid></root>"
    )
    # The entity is left unresolved (not substituted into the <uuid> text),
    # so there is no non-empty <uuid> text to report -- and, crucially, no
    # exception and no secret content anywhere in the result.
    assert query.get_uuids(payload) == []
