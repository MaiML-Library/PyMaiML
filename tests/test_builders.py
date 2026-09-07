from __future__ import annotations

import datetime as dt
from decimal import Decimal

import maiml_domain as m
import pytest

from pymaiml.builders import IdFactory, infer_content, infer_property, new_complete_event


def test_id_factory_generates_unique_ids_per_prefix():
    ids = IdFactory()
    assert ids.new_id("material") == "material1"
    assert ids.new_id("material") == "material2"
    assert ids.new_id("event") == "event1"  # separate counter per prefix


def test_id_factory_uuids_are_valid_maiml_uuids():
    ids = IdFactory()
    u = ids.new_uuid()
    assert isinstance(u, m.Uuid)


@pytest.mark.parametrize(
    "value, expected_cls",
    [
        (True, m.BooleanType),
        (Decimal("1.5"), m.DecimalType),
        (5, m.IntType),
        (1.5, m.FloatType),
        ("hello", m.StringType),
        (dt.datetime(2026, 1, 1), m.DateTimeType),
        (b"abc", m.Base64BinaryType),
    ],
)
def test_infer_property_scalar_dispatch(value, expected_cls):
    prop = infer_property("ex:k", value)
    assert isinstance(prop, expected_cls)
    assert prop.value == value


def test_infer_property_list_dispatch():
    prop = infer_property("ex:k", values=[1, 2, 3])
    assert isinstance(prop, m.IntListType)
    assert prop.values == [1, 2, 3]


def test_infer_property_requires_exactly_one_of_value_or_values():
    with pytest.raises(ValueError):
        infer_property("ex:k")
    with pytest.raises(ValueError):
        infer_property("ex:k", value=1, values=[1])


def test_infer_content_dispatch():
    content = infer_content("ex:wave", values=[1.0, 2.0], size=2, units="cm-1")
    assert isinstance(content, m.ContentFloatListType)
    assert content.units == "cm-1"


def test_id_factory_reserve_prevents_collisions_with_loaded_ids():
    ids = IdFactory()
    ids.reserve(["material1", "material2"])
    assert ids.new_id("material") == "material3"


def test_id_factory_from_existing_ids_is_equivalent_to_reserve():
    ids = IdFactory.from_existing_ids(["material1", "place7"])
    assert ids.new_id("material") == "material2"
    assert ids.new_id("place") == "place1"  # unaffected prefix still starts at 1
    # reserving again (e.g. loading a second file) must not un-reserve or crash
    ids.reserve(["material2"])  # already issued by this same factory -- safe
    assert ids.new_id("material") == "material3"


def test_new_complete_event_sets_lifecycle_property():
    ids = IdFactory()
    event = new_complete_event("event1", "instr1", id_factory=ids)
    assert event.id == "event1"
    assert event.ref == "instr1"
    assert event.content.uuid is not None
    assert event.content.properties[0].key == "lifecycle:transition"
    assert event.content.properties[0].value == "complete"
