"""Tests for pymaiml.query -- the "list the X used in this file" utilities
(get_uuids/get_keys/get_namespaces/get_insertion_uris).

get_uuids()/get_keys()/get_insertion_uris() now go through
pymaiml.serialization.loads() and read their answer off the resulting
maiml_domain object tree (see query.py's module docstring for why), so
most of their tests here build on the shared `minimal_root` fixture
(tests/conftest.py) -- a real, schema-valid maiml_domain tree -- and
mutate a small piece of it per test, rather than hand-writing XML
snippets the way the old raw-XML implementation's tests could.
get_namespaces() is the one function that still parses raw XML directly
(namespaces have no maiml_domain representation at all), so its tests
keep using small hand-built XML snippets as before.
"""
from __future__ import annotations

import maiml_domain as m
import pytest

from pymaiml import query, serialization
from pymaiml.builders import LIFECYCLE_NS

SECRET = "xxe-canary-query-9f2c"


def _external_entity_payload(target_uri: str) -> bytes:
    return f"""<?xml version="1.0"?>
<!DOCTYPE maiml [<!ENTITY xxe SYSTEM "{target_uri}">]>
<maiml xmlns="http://www.maiml.org/schemas"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:type="maimlRootType" version="1.0">&xxe;</maiml>
""".encode("utf-8")


# ---------------------------------------------------------------------------
# get_uuids() / get_keys() / get_insertion_uris(): now read off the
# maiml_domain object tree loads() builds, not off raw XML.
# ---------------------------------------------------------------------------

def test_get_uuids_finds_every_uuid_in_a_real_dumps_output(minimal_root):
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    uuids = query.get_uuids(xml)
    assert str(minimal_root.document.content.uuid) in uuids
    # minimal_root's uuids all come from IdFactory.new_uuid(), which never
    # repeats -- so with nothing added, there is nothing to deduplicate yet.
    assert len(uuids) == len(set(uuids))


def test_get_uuids_keeps_duplicates_instead_of_deduplicating(minimal_root):
    """Give <document> a <chain> whose uuid intentionally repeats the
    document's own content uuid -- get_uuids() must report it twice, not
    collapse it to one (see get_uuids()'s own docstring for why: a
    repeated uuid is itself a fact worth being able to see)."""
    repeated_uuid = minimal_root.document.content.uuid
    before = query.get_uuids(
        serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    )

    minimal_root.document.chains = [
        m.ChainType(uuid=repeated_uuid, hash=m.HashType(value=b"x", method="SHA-256")),
    ]
    after = query.get_uuids(
        serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    )

    assert after.count(str(repeated_uuid)) == 2
    assert len(after) == len(before) + 1


def test_get_uuids_requires_schema_valid_maiml_like_loads_does():
    """get_uuids() no longer has its own, more permissive raw-XML parsing
    path -- it calls serialization.loads() and lets whatever that raises
    propagate, exactly like any other loads() caller. A snippet that is
    not a schema-valid <maiml> document is no longer accepted just because
    it happens to contain a <uuid> element."""
    with pytest.raises(Exception):
        query.get_uuids("<root><uuid>11111111-1111-3111-8111-111111111111</uuid></root>")


def test_get_uuids_inherits_loads_hardening_and_does_not_leak_secret(tmp_path):
    """get_uuids() does not parse xml_text itself at all anymore -- it
    delegates entirely to serialization.loads(), so its XXE/entity
    hardening is whatever loads() does (see tests/test_xml_security.py for
    the dedicated coverage of that). This is a light smoke test that the
    delegation is real: a malicious payload must not resolve the entity or
    leak the secret file's content into whatever exception loads() raises
    for this (structurally invalid) input."""
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text(SECRET, encoding="utf-8")

    payload = _external_entity_payload(secret_file.as_uri())
    try:
        query.get_uuids(payload)
    except Exception as exc:  # noqa: BLE001 -- any parse/structure error is fine here
        assert SECRET not in str(exc)
    else:
        pytest.fail("get_uuids() accepted a non-MaiML payload; expected it to raise")


def test_get_keys_finds_the_lifecycle_complete_marker_in_a_real_dumps_output(minimal_root):
    """minimal_root's only property is the lifecycle:transition="complete"
    marker new_complete_event() attaches (EVT-02) -- get_keys() must find
    it via the same generic object-tree walk as every other test here, not
    a property/content-specific code path."""
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    assert query.get_keys(xml) == ["lifecycle:transition"]


def test_get_keys_dedupes_a_key_repeated_across_two_different_objects(minimal_root):
    """key= appears on property/content instances (here: two StringType
    properties on <document>'s own content) and on ChainType/ParentType.
    MaiML-Schema-1_0 does not require key= to be unique (see
    pymaiml/README.md), so get_keys() reports the distinct keys used, not
    one entry per occurrence -- even when the repeats come from two
    separate objects, not the same one twice."""
    minimal_root.document.content.properties = [
        m.StringType(key="ex:temperature", value="1"),
        m.StringType(key="ex:temperature", value="2"),
    ]
    minimal_root.document.parents = [
        m.ParentType(
            uuid=minimal_root.document.content.uuid,
            hash=m.HashType(value=b"x"),
            key="ex:parent",
        ),
    ]
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    keys = query.get_keys(xml)
    assert keys.count("ex:temperature") == 1
    assert "ex:parent" in keys
    assert "lifecycle:transition" in keys


def test_get_insertion_uris_returns_empty_list_when_none_present(minimal_root):
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    assert query.get_insertion_uris(xml) == []


def test_get_insertion_uris_dedupes_and_preserves_order(minimal_root):
    minimal_root.document.content.insertions = [
        m.InsertionType(uri="file:///a.csv", hash=m.HashType(value=b"h1")),
        m.InsertionType(uri="file:///b.csv", hash=m.HashType(value=b"h2")),
        m.InsertionType(uri="file:///a.csv", hash=m.HashType(value=b"h3")),
    ]
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    assert query.get_insertion_uris(xml) == ["file:///a.csv", "file:///b.csv"]


def test_insertion_type_always_requires_a_uri():
    """Documents a direct consequence of building get_insertion_uris() on
    maiml_domain rather than raw XML: an <insertion> with no uri -- which
    the old implementation had to explicitly skip -- can no longer be
    constructed at all, so it can never reach get_insertion_uris() in the
    first place."""
    with pytest.raises(ValueError):
        m.InsertionType(uri="", hash=m.HashType(value=b"x"))


# ---------------------------------------------------------------------------
# get_namespaces(): the one function that still parses xml_text directly
# (no maiml_domain equivalent exists for namespace declarations).
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


def test_get_namespaces_result_is_reusable_as_dumps_extra_namespaces(minimal_root):
    """The result should be a drop-in for dumps(..., extra_namespaces=...),
    matching LoadedMaiml.namespaces's documented usage pattern."""
    xml1 = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    namespaces = query.get_namespaces(xml1)
    assert namespaces == {"lifecycle": LIFECYCLE_NS}
    xml2 = serialization.dumps(minimal_root, extra_namespaces=namespaces)
    assert xml1 == xml2


def test_get_namespaces_does_not_resolve_external_file_entities(tmp_path):
    """get_namespaces() is the one function in this module that still
    parses xml_text itself (see the module docstring) -- it must still go
    through pymaiml._xml_security.make_untrusted_input_parser(), same as
    before this module's other three functions started delegating to
    loads() instead."""
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text(SECRET, encoding="utf-8")

    payload = (
        '<?xml version="1.0"?>'
        f'<!DOCTYPE root [<!ENTITY xxe SYSTEM "{secret_file.as_uri()}">]>'
        '<root xmlns:ex="http://example.org/ex"><note>&xxe;</note></root>'
    )
    # The declared namespace is still found; the entity is left unresolved
    # (no crash, no secret content anywhere in the result).
    assert query.get_namespaces(payload) == {"ex": "http://example.org/ex"}


# ---------------------------------------------------------------------------
# get_templates() / get_instances(): object-returning, keyword-filterable.
# Like get_uuids()/get_keys()/get_insertion_uris(), both go through
# serialization.loads() and therefore require schema-valid input; unlike
# those three, they return the actual maiml_domain objects, not strings.
# ---------------------------------------------------------------------------

def test_get_templates_returns_all_kinds_by_default(minimal_root):
    """minimal_root defines exactly one template, a materialTemplate (the
    protocol's material_templates=[mt] -- see conftest.py). kind=None
    should find it without the caller having to know its kind up front."""
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    templates = query.get_templates(xml)
    assert [type(t).__name__ for t in templates] == ["MaterialTemplateType"]
    assert templates[0].id == minimal_root.protocol.material_templates[0].id


def test_get_templates_filters_by_kind(minimal_root):
    """Add a conditionTemplate alongside minimal_root's existing
    materialTemplate, at the same protocol level -- kind="material" must
    return only the former, kind="condition" only the latter."""
    ct = m.ConditionTemplateType(
        id="ct1",
        place_refs=[m.PlaceRefType(id="ctref1", ref=minimal_root.protocol.methods[0].pnmls[0].places[0].id)],
        content=m.GlobalObjectContent(uuid=m.Uuid("11111111-1111-3111-8111-111111111111")),
    )
    minimal_root.protocol.condition_templates = [ct]
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})

    material_only = query.get_templates(xml, kind="material")
    assert [type(t).__name__ for t in material_only] == ["MaterialTemplateType"]

    condition_only = query.get_templates(xml, kind="condition")
    assert [type(t).__name__ for t in condition_only] == ["ConditionTemplateType"]

    both = query.get_templates(xml)
    assert sorted(type(t).__name__ for t in both) == ["ConditionTemplateType", "MaterialTemplateType"]


def test_get_templates_raises_on_unknown_kind(minimal_root):
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    with pytest.raises(ValueError, match="unknown kind"):
        query.get_templates(xml, kind="bogus")


def test_get_templates_requires_schema_valid_maiml_like_loads_does():
    with pytest.raises(Exception):
        query.get_templates("<root/>")


def test_get_templates_ids_are_available_on_the_returned_objects(minimal_root):
    """There is no separate 'ids only' function -- the object returned by
    get_templates() already carries .id, so the caller extracts it."""
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    ids = [t.id for t in query.get_templates(xml)]
    assert ids == [minimal_root.protocol.material_templates[0].id]


def test_get_instances_returns_all_kinds_by_default(minimal_root):
    """minimal_root's <data> holds exactly one materialType instance (see
    conftest.py: results.materials=[material])."""
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    instances = query.get_instances(xml)
    assert [type(i).__name__ for i in instances] == ["MaterialType"]
    assert instances[0].id == minimal_root.data.results_list[0].materials[0].id


def test_get_instances_filters_by_kind(minimal_root):
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    assert [type(i).__name__ for i in query.get_instances(xml, kind="material")] == ["MaterialType"]
    assert query.get_instances(xml, kind="condition") == []
    assert query.get_instances(xml, kind="result") == []


def test_get_instances_raises_on_unknown_kind(minimal_root):
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    with pytest.raises(ValueError, match="unknown kind"):
        query.get_instances(xml, kind="bogus")


def test_get_instances_requires_schema_valid_maiml_like_loads_does():
    with pytest.raises(Exception):
        query.get_instances("<root/>")


def test_get_instances_with_instruction_id_follows_event_results_refs_chain(minimal_root):
    """minimal_root's own new_complete_event() does not set results_refs
    (see conftest.py/builders.py) -- add one linking the instruction's
    event to the file's one <results>, and instruction_id= must then find
    the instance that <results> holds, via
    instruction -> event -> results_refs -> results -> materials."""
    instr_id = minimal_root.protocol.methods[0].programs[0].instructions[0].id
    results_id = minimal_root.data.results_list[0].id
    event = minimal_root.event_log.logs[0].traces[0].events[0]
    event.results_refs = [m.ResultsRefType(id="rref1", ref=results_id)]

    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    linked = query.get_instances(xml, instruction_id=instr_id)
    assert [type(i).__name__ for i in linked] == ["MaterialType"]
    assert linked[0].id == minimal_root.data.results_list[0].materials[0].id


def test_get_instances_valid_instruction_id_with_nothing_linked_returns_empty_list(minimal_root):
    """minimal_root's event has no results_refs by default (see
    conftest.py's new_complete_event() call) -- a real, existing
    instruction with nothing linked to it yet is not an error, unlike an
    instruction_id that does not exist at all (see the next test)."""
    instr_id = minimal_root.protocol.methods[0].programs[0].instructions[0].id
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    assert query.get_instances(xml, instruction_id=instr_id) == []


def test_get_instances_unknown_instruction_id_raises(minimal_root):
    xml = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    with pytest.raises(ValueError, match="no <instruction id="):
        query.get_instances(xml, instruction_id="no-such-instruction")


def test_get_templates_works_on_protocol_only_root(protocol_only_root):
    """A protocolFileRootType still has templates -- get_templates() does
    not need <data>/<eventLog> to exist at all."""
    xml = serialization.dumps(protocol_only_root)
    templates = query.get_templates(xml)
    assert [type(t).__name__ for t in templates] == ["MaterialTemplateType"]


def test_get_instances_on_protocol_only_root_is_always_empty(protocol_only_root):
    """A protocolFileRootType has no <data>/<eventLog> at all (see
    maiml_domain.root.ProtocolFileRootType), so there is nothing
    get_instances() could ever find -- with or without instruction_id=. A
    *valid* instruction_id there still resolves without raising (the
    <instruction> element itself is present); only an unknown one raises,
    exactly as for a full maimlRootType file."""
    instr_id = protocol_only_root.protocol.methods[0].programs[0].instructions[0].id
    xml = serialization.dumps(protocol_only_root)
    assert query.get_instances(xml) == []
    assert query.get_instances(xml, instruction_id=instr_id) == []
    with pytest.raises(ValueError, match="no <instruction id="):
        query.get_instances(xml, instruction_id="no-such-instruction")
