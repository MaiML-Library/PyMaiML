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
