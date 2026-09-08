from __future__ import annotations

import datetime as dt

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


def test_loads_roundtrips_dumps_output_byte_for_byte(minimal_root):
    """dumps() -> loads() -> dumps() must reproduce the exact same XML --
    the strongest available check that the reader is the true inverse of
    the writer, without needing a separate object-equality definition."""
    xml_text = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    loaded = serialization.loads(xml_text)
    assert isinstance(loaded.root, type(minimal_root))
    xml_text_2 = serialization.dumps(loaded.root, extra_namespaces=loaded.namespaces)
    assert xml_text_2 == xml_text


def test_loads_collects_every_id_and_declared_namespace(minimal_root):
    xml_text = serialization.dumps(minimal_root, extra_namespaces={"lifecycle": LIFECYCLE_NS})
    loaded = serialization.loads(xml_text)
    assert loaded.namespaces == {"lifecycle": LIFECYCLE_NS}
    assert loaded.ids  # non-empty
    assert len(loaded.ids) == len(set(loaded.ids))  # ids are unique, as MaiML requires


def test_load_reads_protocol_file_root_type_from_a_path(protocol_only_root, tmp_path):
    out = tmp_path / "protocol.maiml"
    serialization.dump(protocol_only_root, out, extra_namespaces={"lifecycle": LIFECYCLE_NS})

    loaded = serialization.load(out)
    assert isinstance(loaded.root, type(protocol_only_root))
    assert loaded.root.protocol is not None
    # ProtocolFileRootType has no data/eventLog slot at all -- unlike
    # MaimlRootType, where an absent <data>/<eventLog> would instead show up
    # as None on the loaded object.
    assert not hasattr(loaded.root, "data")
    assert not hasattr(loaded.root, "event_log")


def test_load_then_extend_with_new_data_and_event_log(protocol_only_root, tmp_path):
    """The exact use case this module was written for: load an
    already-authored protocol file, keep its document/protocol as-is, and
    build a brand new data/eventLog on top -- with no id collisions and the
    original namespace declarations (lifecycle: in particular) preserved --
    and the result must still pass full schema + business-rule validation."""
    import maiml_domain as m

    from pymaiml import validation
    from pymaiml.builders import IdFactory, new_complete_event

    protocol_path = tmp_path / "protocol.maiml"
    serialization.dump(protocol_only_root, protocol_path, extra_namespaces={"lifecycle": LIFECYCLE_NS})

    loaded = serialization.load(protocol_path)
    ids = IdFactory.from_existing_ids(loaded.ids)

    loaded_protocol = loaded.root.protocol
    loaded_mt = loaded_protocol.material_templates[0]
    loaded_method = loaded_protocol.methods[0]
    loaded_program = loaded_method.programs[0]
    loaded_instr = loaded_program.instructions[0]

    material = m.MaterialType(id=ids.new_id("material"), ref=loaded_mt.id, content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    results = m.ResultsType(id=ids.new_id("results"), materials=[material], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    data = m.DataType(id=ids.new_id("data"), results_list=[results], content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    event = new_complete_event(ids.new_id("event"), loaded_instr.id, id_factory=ids)
    trace = m.TraceType(id=ids.new_id("trace"), ref=loaded_program.id, events=[event], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    log = m.LogType(id=ids.new_id("log"), ref=loaded_method.id, traces=[trace], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    event_log = m.EventLogType(id=ids.new_id("eventlog"), logs=[log], content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    full_root = m.MaimlRootType(
        document=loaded.root.document, protocol=loaded_protocol, data=data, event_log=event_log,
    )

    out = tmp_path / "extended.maiml"
    serialization.dump(full_root, out, extra_namespaces=loaded.namespaces)

    result = validation.validate(out)
    assert result.ok, result.errors


def test_protocol_placeholder_and_measured_data_share_xsi_type_and_validate(tmp_path):
    """A protocol's material template usually declares a property with no
    value yet (xsi_type= given explicitly instead) -- and the matching
    <data> recording of the same key, built later from an actual measured
    Python value, must serialize with that same xsi:type. Here the measured
    value is an int (20) for a key the protocol declared as floatType, so
    this also exercises XsiTypeRegistry actually overriding what plain type
    inference would have picked (IntType)."""
    import maiml_domain as m

    from pymaiml import validation
    from pymaiml.builders import IdFactory, XsiTypeRegistry, infer_property, new_complete_event

    ids = IdFactory()
    registry = XsiTypeRegistry()

    place = m.PlaceType(id=ids.new_id("place"))
    trans = m.TransitionType(id=ids.new_id("trans"))
    arc = m.ArcType(id=ids.new_id("arc"), source=place.id, target=trans.id)
    pnml = m.PnmlType(id=ids.new_id("pnml"), places=[place], transitions=[trans], arcs=[arc],
                       content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    instr = m.InstructionType(
        id=ids.new_id("instr"),
        transition_refs=[m.TransitionRefType(id=ids.new_id("ref"), ref=trans.id)],
        content=m.GlobalObjectContent(uuid=ids.new_uuid()),
    )
    program = m.ProgramType(id=ids.new_id("program"), instructions=[instr], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    method = m.MethodType(id=ids.new_id("method"), pnmls=[pnml], programs=[program], content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    placeholder = infer_property("ex:temperature", xsi_type=m.FloatType, registry=registry, units="degC")
    mt = m.MaterialTemplateType(
        id=ids.new_id("mt"), place_refs=[m.PlaceRefType(id=ids.new_id("ref"), ref=place.id)],
        content=m.GlobalObjectContent(uuid=ids.new_uuid(), properties=[placeholder]),
    )
    protocol = m.ProtocolType(id=ids.new_id("protocol"), methods=[method], material_templates=[mt],
                               content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    vendor = m.VendorType(id=ids.new_id("vendor"), content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    owner = m.OwnerType(id=ids.new_id("owner"), content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    creator = m.CreatorType(id=ids.new_id("creator"),
                             vendor_refs=[m.VendorRefType(id=ids.new_id("ref"), ref=vendor.id)],
                             content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    document = m.DocumentType(id=ids.new_id("doc"), date=dt.datetime.now(dt.timezone.utc),
                               creators=[creator], vendors=[vendor], owners=[owner],
                               content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    measured = infer_property("ex:temperature", value=20, registry=registry, units="degC")
    assert type(measured) is m.FloatType  # not IntType, despite the Python int

    material = m.MaterialType(id=ids.new_id("material"), ref=mt.id,
                               content=m.GlobalObjectContent(uuid=ids.new_uuid(), properties=[measured]))
    results = m.ResultsType(id=ids.new_id("results"), materials=[material], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    data = m.DataType(id=ids.new_id("data"), results_list=[results], content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    event = new_complete_event(ids.new_id("event"), instr.id, id_factory=ids)
    trace = m.TraceType(id=ids.new_id("trace"), ref=program.id, events=[event], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    log = m.LogType(id=ids.new_id("log"), ref=method.id, traces=[trace], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    event_log = m.EventLogType(id=ids.new_id("eventlog"), logs=[log], content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    root = m.MaimlRootType(document=document, protocol=protocol, data=data, event_log=event_log)

    out = tmp_path / "sample.maiml"
    serialization.dump(root, out, extra_namespaces={"lifecycle": LIFECYCLE_NS, "ex": "http://example.org/ex"})
    xml_text = out.read_text(encoding="utf-8")

    # both the protocol's placeholder and data's measured property for
    # ex:temperature must serialize with the same xsi:type
    assert xml_text.count('xsi:type="floatType"') >= 2

    result = validation.validate(out)
    assert result.ok, result.errors


# ---------------------------------------------------------------------------
# <uncertainty> and scalar xsi:type parsing -- regression coverage for two
# bugs found while reconstructing real-world MaiML files with pymaiml:
#   1. <uncertainty> was silently dropped on both write and read.
#   2. _parse_scalar_text/_format_value matched xsi:type names with a
#      case-sensitive substring check (e.g. "Float" in xsi_type) that can
#      never match a bare type like "floatType", because
#      pymaiml._xsi_registry lowercases only the class name's *first*
#      letter -- so every bare scalar/list type (float, double, decimal,
#      int, long, short, byte, boolean, dateTime, uuid, hexBinary,
#      base64Binary) round-tripped as a raw string instead of its real
#      Python type. Content-prefixed types (ContentFloatListType ->
#      "contentFloatListType") and "unsigned*" types happened to still work
#      by accident, which is why this had gone unnoticed.
# ---------------------------------------------------------------------------

def test_uncertainty_round_trips_through_dumps_and_loads():
    import maiml_domain as m

    prop = m.FloatType(
        key="ex:scaleX", value=0.8840,
        uncertainties=[m.FloatType(key="ex:StandardError", value=0.0021, format_string="0.0000")],
    )
    root = _minimal_root_with_result_property(prop)

    xml_text = serialization.dumps(root, extra_namespaces={"lifecycle": LIFECYCLE_NS, "ex": "http://example.org/ex"})
    assert "<uncertainty " in xml_text

    loaded = serialization.loads(xml_text)
    loaded_prop = _find_property(loaded.root, "ex:scaleX")
    assert loaded_prop.value == 0.8840
    assert len(loaded_prop.uncertainties) == 1
    u = loaded_prop.uncertainties[0]
    assert isinstance(u, m.FloatType)
    assert u.key == "ex:StandardError"
    assert u.value == 0.0021
    assert u.format_string == "0.0000"


@pytest.mark.parametrize(
    "cls, value",
    [
        (__import__("maiml_domain").FloatType, 1.5),
        (__import__("maiml_domain").DoubleType, 2.5),
        (__import__("maiml_domain").DecimalType, __import__("decimal").Decimal("3.25")),
        (__import__("maiml_domain").IntType, 7),
        (__import__("maiml_domain").LongType, 123456789),
        (__import__("maiml_domain").BooleanType, True),
        (__import__("maiml_domain").UuidType, __import__("maiml_domain").Uuid("12345678-1234-3234-8234-123456789012")),
    ],
)
def test_bare_scalar_types_round_trip_with_correct_python_type(cls, value):
    """These are exactly the "keyword at position 0 of the class name"
    types that the case-sensitive substring bug used to silently mis-parse
    back as a plain string."""
    import maiml_domain as m

    prop = cls(key="ex:value", value=value)
    root = _minimal_root_with_result_property(prop)

    xml_text = serialization.dumps(root, extra_namespaces={"ex": "http://example.org/ex"})
    loaded = serialization.loads(xml_text)
    loaded_prop = _find_property(loaded.root, "ex:value")

    assert type(loaded_prop.value) is type(value) or (
        isinstance(value, m.Uuid) and isinstance(loaded_prop.value, m.Uuid)
    )
    assert loaded_prop.value == value


def _minimal_root_with_result_property(prop):
    """Build the smallest MaimlRootType whose single result carries `prop`
    -- shared scaffolding for the two regression tests above."""
    import maiml_domain as m

    from pymaiml.builders import IdFactory, new_complete_event

    ids = IdFactory()
    place = m.PlaceType(id=ids.new_id("place"))
    trans = m.TransitionType(id=ids.new_id("trans"))
    arc = m.ArcType(id=ids.new_id("arc"), source=place.id, target=trans.id)
    pnml = m.PnmlType(id=ids.new_id("pnml"), places=[place], transitions=[trans], arcs=[arc],
                       content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    instr = m.InstructionType(id=ids.new_id("instr"),
                               transition_refs=[m.TransitionRefType(id=ids.new_id("ref"), ref=trans.id)],
                               content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    program = m.ProgramType(id=ids.new_id("program"), instructions=[instr], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    method = m.MethodType(id=ids.new_id("method"), pnmls=[pnml], programs=[program], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    rt = m.ResultTemplateType(id=ids.new_id("rt"), place_refs=[m.PlaceRefType(id=ids.new_id("ref"), ref=place.id)],
                               content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    protocol = m.ProtocolType(id=ids.new_id("protocol"), methods=[method], result_templates=[rt],
                               content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    vendor = m.VendorType(id=ids.new_id("vendor"), content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    owner = m.OwnerType(id=ids.new_id("owner"), content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    creator = m.CreatorType(id=ids.new_id("creator"),
                             vendor_refs=[m.VendorRefType(id=ids.new_id("ref"), ref=vendor.id)],
                             content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    document = m.DocumentType(id=ids.new_id("doc"), date=dt.datetime.now(dt.timezone.utc),
                               creators=[creator], vendors=[vendor], owners=[owner],
                               content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    result = m.ResultType(id=ids.new_id("result"), ref=rt.id,
                           content=m.GlobalObjectContent(uuid=ids.new_uuid(), properties=[prop]))
    results = m.ResultsType(id=ids.new_id("results"), results=[result], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    data = m.DataType(id=ids.new_id("data"), results_list=[results], content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    event = new_complete_event(ids.new_id("event"), instr.id, id_factory=ids)
    trace = m.TraceType(id=ids.new_id("trace"), ref=program.id, events=[event], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    log = m.LogType(id=ids.new_id("log"), ref=method.id, traces=[trace], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    event_log = m.EventLogType(id=ids.new_id("eventlog"), logs=[log], content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    return m.MaimlRootType(document=document, protocol=protocol, data=data, event_log=event_log)


def _find_property(root_obj, key):
    result = root_obj.data.results_list[0].results[0]
    for prop in result.content.properties:
        if prop.key == key:
            return prop
    raise AssertionError(f"property {key!r} not found")



# ---------------------------------------------------------------------------
# Regression tests for the external review (PyMaiML review findings 01-03,
# 2026-09-07): signature round-trip crash, empty-string/absent confusion
# for <description>/<format>, and a conflicting-declaration safety net.
# ---------------------------------------------------------------------------

def _minimal_root_with_signature(signature_xml):
    """Build the smallest MaimlRootType whose document carries `signature`
    -- mirrors conftest.py's minimal_root fixture, but with a <Signature>
    attached, which that fixture deliberately omits."""
    import maiml_domain as m

    from pymaiml.builders import IdFactory, new_complete_event

    ids = IdFactory()
    vendor = m.VendorType(id=ids.new_id("vendor"), content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    owner = m.OwnerType(id=ids.new_id("owner"), content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    creator = m.CreatorType(id=ids.new_id("creator"),
                             vendor_refs=[m.VendorRefType(id=ids.new_id("ref"), ref=vendor.id)],
                             content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    document = m.DocumentType(id=ids.new_id("doc"), date=dt.datetime.now(dt.timezone.utc),
                               creators=[creator], vendors=[vendor], owners=[owner],
                               content=m.GlobalObjectContent(uuid=ids.new_uuid()),
                               signature=signature_xml)

    place = m.PlaceType(id=ids.new_id("place"))
    trans = m.TransitionType(id=ids.new_id("trans"))
    arc = m.ArcType(id=ids.new_id("arc"), source=place.id, target=trans.id)
    pnml = m.PnmlType(id=ids.new_id("pnml"), places=[place], transitions=[trans], arcs=[arc],
                       content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    instr = m.InstructionType(id=ids.new_id("instr"),
                               transition_refs=[m.TransitionRefType(id=ids.new_id("ref"), ref=trans.id)],
                               content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    program = m.ProgramType(id=ids.new_id("program"), instructions=[instr], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    method = m.MethodType(id=ids.new_id("method"), pnmls=[pnml], programs=[program], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    mt = m.MaterialTemplateType(id=ids.new_id("mt"), place_refs=[m.PlaceRefType(id=ids.new_id("ref"), ref=place.id)],
                                 content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    protocol = m.ProtocolType(id=ids.new_id("protocol"), methods=[method], material_templates=[mt],
                               content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    material = m.MaterialType(id=ids.new_id("material"), ref=mt.id, content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    results = m.ResultsType(id=ids.new_id("results"), materials=[material], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    data = m.DataType(id=ids.new_id("data"), results_list=[results], content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    event = new_complete_event(ids.new_id("event"), instr.id, id_factory=ids)
    trace = m.TraceType(id=ids.new_id("trace"), ref=program.id, events=[event], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    log = m.LogType(id=ids.new_id("log"), ref=method.id, traces=[trace], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    event_log = m.EventLogType(id=ids.new_id("eventlog"), logs=[log], content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    return m.MaimlRootType(document=document, protocol=protocol, data=data, event_log=event_log)


def test_signature_round_trips_without_duplicate_namespace_error():
    """A <Signature> read back via loads() is re-serialized by lxml with
    every namespace declaration in scope baked into the fragment text
    (including ones inherited from the root, unrelated to the signature
    itself). Re-appending that text on the next dumps() call makes
    xml.etree.ElementTree auto-declare its own ns0/ns1/... prefix for the
    namespace(s) actually used inside it -- and before the fix, that could
    collide with the very same prefix loads() had reported back via
    LoadedMaiml.namespaces (the documented load-modify-dump workflow),
    producing two xmlns:ns0="..." attributes on the root <maiml> element
    and: xml.parsers.expat.ExpatError: duplicate attribute."""
    root = _minimal_root_with_signature(
        '<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#">'
        "<ds:SignedInfo><ds:DigestValue>AAAA</ds:DigestValue></ds:SignedInfo>"
        "<ds:SignatureValue>BBBB</ds:SignatureValue></ds:Signature>"
    )

    xml1 = serialization.dumps(root)
    loaded = serialization.loads(xml1)
    assert loaded.namespaces  # the xmldsig namespace was captured, as documented

    # This is exactly the documented load-modify-dump workflow
    # (LoadedMaiml.namespaces docstring: "Pass this straight back as
    # dumps(..., extra_namespaces=namespaces)") -- it must not raise.
    xml2 = serialization.dumps(loaded.root, extra_namespaces=loaded.namespaces)

    # ...and the result must itself be stable under a second round trip.
    loaded2 = serialization.loads(xml2)
    xml3 = serialization.dumps(loaded2.root, extra_namespaces=loaded2.namespaces)
    assert xml2 == xml3


def test_dumps_rejects_genuinely_conflicting_root_namespace_declaration():
    """The fix above must not silently pick a winner when two *different*
    namespace URIs end up declared under the same prefix on the root
    element -- that would silently point some tags/keys at the wrong
    namespace instead of failing loudly."""
    from pymaiml.serialization import _dedupe_root_namespace_decls

    xml_text = (
        '<maiml xmlns:ns0="http://example.org/a" xmlns:ns0="http://example.org/b">'
        "<x/></maiml>"
    )
    with pytest.raises(ValueError, match="conflicting declarations"):
        _dedupe_root_namespace_decls(xml_text)


def test_empty_property_value_and_description_round_trip_as_empty_string():
    """<description/> is a valid, present-but-empty xs:string element
    (minOccurs="0") distinct from the element being absent. Before the
    fix, both _read_global_content's use of _text_of() and
    _read_property_or_content's own inline description-reading loop used
    `child.text` directly -- None for an empty element in both lxml and
    ElementTree -- so an empty <description/> was indistinguishable from a
    missing one, and dumps() silently dropped it on the next round trip."""
    import maiml_domain as m

    prop = m.StringType(key="ex:note", value="", description="")
    root = _minimal_root_with_result_property(prop)

    xml_text = serialization.dumps(root, extra_namespaces={"ex": "http://example.org/ex"})
    assert "<description/>" in xml_text or "<description />" in xml_text

    loaded = serialization.loads(xml_text)
    loaded_prop = _find_property(loaded.root, "ex:note")
    assert loaded_prop.value == ""
    assert loaded_prop.description == ""


def test_absent_property_description_still_round_trips_as_none():
    """Companion to the test above: the fix must not turn "absent" into
    "" -- only "present but empty" should become ''."""
    import maiml_domain as m

    prop = m.StringType(key="ex:note", value="x")
    root = _minimal_root_with_result_property(prop)

    xml_text = serialization.dumps(root, extra_namespaces={"ex": "http://example.org/ex"})
    loaded = serialization.loads(xml_text)
    loaded_prop = _find_property(loaded.root, "ex:note")
    assert loaded_prop.description is None


def _minimal_root_with_result_insertion(insertion):
    """Build the smallest MaimlRootType whose single result carries
    `insertion` -- mirrors _minimal_root_with_result_property, but for the
    insertion* branch of globalObjectContentGroup instead of property*."""
    import maiml_domain as m

    from pymaiml.builders import IdFactory, new_complete_event

    ids = IdFactory()
    place = m.PlaceType(id=ids.new_id("place"))
    trans = m.TransitionType(id=ids.new_id("trans"))
    arc = m.ArcType(id=ids.new_id("arc"), source=place.id, target=trans.id)
    pnml = m.PnmlType(id=ids.new_id("pnml"), places=[place], transitions=[trans], arcs=[arc],
                       content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    instr = m.InstructionType(id=ids.new_id("instr"),
                               transition_refs=[m.TransitionRefType(id=ids.new_id("ref"), ref=trans.id)],
                               content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    program = m.ProgramType(id=ids.new_id("program"), instructions=[instr], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    method = m.MethodType(id=ids.new_id("method"), pnmls=[pnml], programs=[program], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    rt = m.ResultTemplateType(id=ids.new_id("rt"), place_refs=[m.PlaceRefType(id=ids.new_id("ref"), ref=place.id)],
                               content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    protocol = m.ProtocolType(id=ids.new_id("protocol"), methods=[method], result_templates=[rt],
                               content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    vendor = m.VendorType(id=ids.new_id("vendor"), content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    owner = m.OwnerType(id=ids.new_id("owner"), content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    creator = m.CreatorType(id=ids.new_id("creator"),
                             vendor_refs=[m.VendorRefType(id=ids.new_id("ref"), ref=vendor.id)],
                             content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    document = m.DocumentType(id=ids.new_id("doc"), date=dt.datetime.now(dt.timezone.utc),
                               creators=[creator], vendors=[vendor], owners=[owner],
                               content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    result = m.ResultType(id=ids.new_id("result"), ref=rt.id,
                           content=m.GlobalObjectContent(uuid=ids.new_uuid(), insertions=[insertion]))
    results = m.ResultsType(id=ids.new_id("results"), results=[result], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    data = m.DataType(id=ids.new_id("data"), results_list=[results], content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    event = new_complete_event(ids.new_id("event"), instr.id, id_factory=ids)
    trace = m.TraceType(id=ids.new_id("trace"), ref=program.id, events=[event], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    log = m.LogType(id=ids.new_id("log"), ref=method.id, traces=[trace], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    event_log = m.EventLogType(id=ids.new_id("eventlog"), logs=[log], content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    return m.MaimlRootType(document=document, protocol=protocol, data=data, event_log=event_log)


def _find_insertion(root_obj):
    result = root_obj.data.results_list[0].results[0]
    return result.content.insertions[0]


def test_empty_insertion_format_round_trips_as_empty_string():
    """Same absent-vs-empty bug as the property description test above,
    but for InsertionType.format (_read_insertion() had its own,
    independent instance of the same `child.text if ... else None`
    pattern)."""
    import maiml_domain as m

    insertion = m.InsertionType(uri="a.png", hash=m.HashType(value=b"\x00" * 32), format="")
    root = _minimal_root_with_result_insertion(insertion)

    xml_text = serialization.dumps(root)
    assert "<format/>" in xml_text or "<format />" in xml_text

    loaded = serialization.loads(xml_text)
    assert _find_insertion(loaded.root).format == ""


def test_absent_insertion_format_still_round_trips_as_none():
    """Companion to the test above: an insertion with no format at all
    must still come back as None, not ""."""
    import maiml_domain as m

    insertion = m.InsertionType(uri="a.png", hash=m.HashType(value=b"\x00" * 32))
    root = _minimal_root_with_result_insertion(insertion)

    loaded = serialization.loads(serialization.dumps(root))
    assert _find_insertion(loaded.root).format is None



# ---------------------------------------------------------------------------
# Regression test for the external review's "worth considering" finding 05
# (2026-09-07): units/formatString/scaleFactor are only valid on numeric
# property/content classes, but loads() used to pass them through
# unconditionally and let a raw TypeError from the domain class's __init__
# reach the caller.
# ---------------------------------------------------------------------------

def test_units_on_a_class_that_does_not_accept_it_raises_a_clear_error():
    """stringType has no `units` parameter (only numeric xsi:types do), so
    a file that puts units="..." on one is not MaiML-Schema-1_0 valid.
    Before the fix, this reached the caller as a raw
    `TypeError: _ScalarPropertyBase.__init__() got an unexpected keyword
    argument 'units'`; it must now be a clear, MaiML-specific ValueError
    instead."""
    import xml.etree.ElementTree as ET

    el = ET.fromstring(
        '<property xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'key="ex:k" xsi:type="stringType" units="Pa"><value>x</value></property>'
    )
    with pytest.raises(ValueError, match="does not accept a 'units' value"):
        serialization._read_property_or_content(el)


def test_units_formatstring_scalefactor_on_a_class_that_accepts_them_still_work():
    """Companion to the test above: the guard must not reject the normal,
    valid case (a numeric xsi:type that does accept these attributes)."""
    import xml.etree.ElementTree as ET

    el = ET.fromstring(
        '<property xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'key="ex:k" xsi:type="floatType" units="Pa" formatString="0.00" '
        'scaleFactor="2"><value>1.5</value></property>'
    )
    prop = serialization._read_property_or_content(el)
    assert prop.units == "Pa"
    assert prop.format_string == "0.00"
    assert prop.scale_factor == 2
    assert prop.value == 1.5
