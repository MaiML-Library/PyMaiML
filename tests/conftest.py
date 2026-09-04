"""Shared pytest fixtures: build a minimal-but-complete MaimlRootType."""
from __future__ import annotations

import datetime as dt

import maiml_domain as m
import pytest

from pymaiml.builders import IdFactory, new_complete_event, LIFECYCLE_NS


@pytest.fixture
def id_factory() -> IdFactory:
    return IdFactory()


@pytest.fixture
def minimal_root(id_factory: IdFactory) -> m.MaimlRootType:
    """The smallest object tree that is both maiml_domain-valid and
    MaiML-Schema-1_0-valid: one of everything required, nothing optional."""
    ids = id_factory

    vendor = m.VendorType(id=ids.new_id("vendor"), content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    owner = m.OwnerType(id=ids.new_id("owner"), content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    creator = m.CreatorType(
        id=ids.new_id("creator"),
        vendor_refs=[m.VendorRefType(id=ids.new_id("ref"), ref=vendor.id)],
        content=m.GlobalObjectContent(uuid=ids.new_uuid()),
    )
    document = m.DocumentType(
        id=ids.new_id("doc"),
        date=dt.datetime.now(dt.timezone.utc),
        creators=[creator], vendors=[vendor], owners=[owner],
        content=m.GlobalObjectContent(uuid=ids.new_uuid()),
    )

    place = m.PlaceType(id=ids.new_id("place"))
    trans = m.TransitionType(id=ids.new_id("trans"))
    arc = m.ArcType(id=ids.new_id("arc"), source=place.id, target=trans.id)
    pnml = m.PnmlType(
        id=ids.new_id("pnml"), places=[place], transitions=[trans], arcs=[arc],
        content=m.GlobalObjectContent(uuid=ids.new_uuid()),
    )
    instr = m.InstructionType(
        id=ids.new_id("instr"),
        transition_refs=[m.TransitionRefType(id=ids.new_id("ref"), ref=trans.id)],
        content=m.GlobalObjectContent(uuid=ids.new_uuid()),
    )
    program = m.ProgramType(id=ids.new_id("program"), instructions=[instr], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    method = m.MethodType(id=ids.new_id("method"), pnmls=[pnml], programs=[program], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    mt = m.MaterialTemplateType(
        id=ids.new_id("mt"), place_refs=[m.PlaceRefType(id=ids.new_id("ref"), ref=place.id)],
        content=m.GlobalObjectContent(uuid=ids.new_uuid()),
    )
    protocol = m.ProtocolType(id=ids.new_id("protocol"), methods=[method], material_templates=[mt], content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    material = m.MaterialType(id=ids.new_id("material"), ref=mt.id, content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    results = m.ResultsType(id=ids.new_id("results"), materials=[material], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    data = m.DataType(id=ids.new_id("data"), results_list=[results], content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    event = new_complete_event(ids.new_id("event"), instr.id, id_factory=ids)
    trace = m.TraceType(id=ids.new_id("trace"), ref=program.id, events=[event], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    log = m.LogType(id=ids.new_id("log"), ref=method.id, traces=[trace], content=m.GlobalObjectContent(uuid=ids.new_uuid()))
    event_log = m.EventLogType(id=ids.new_id("eventlog"), logs=[log], content=m.GlobalObjectContent(uuid=ids.new_uuid()))

    return m.MaimlRootType(document=document, protocol=protocol, data=data, event_log=event_log)
