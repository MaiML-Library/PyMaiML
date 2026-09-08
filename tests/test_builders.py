from __future__ import annotations

import datetime as dt
from decimal import Decimal

import maiml_domain as m
import pytest

from pymaiml.builders import IdFactory, XsiTypeRegistry, infer_content, infer_property, new_complete_event


def test_id_factory_generates_unique_ids_per_prefix():
    ids = IdFactory()
    assert ids.new_id("material") == "material1"
    assert ids.new_id("material") == "material2"
    assert ids.new_id("event") == "event1"  # separate counter per prefix


def test_id_factory_uuids_are_valid_maiml_uuids():
    ids = IdFactory()
    u = ids.new_uuid()
    assert isinstance(u, m.Uuid)


# ---------------------------------------------------------------------------
# IdFactory.new_id(): prefix must itself be a valid xs:ID (NCName), since
# every generated id is prefix + an integer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_prefix",
    [
        "123",          # starts with a digit -- "1231" would not be a valid xs:ID
        "",              # empty -- "1" alone is a valid NCName, but the intent (a prefix) is not
        "ns:foo",        # ':' is exactly what makes Name -> NCName invalid
        "has space",     # whitespace is not a NameChar
        "a!b",           # '!' is not a NameChar
    ],
)
def test_new_id_rejects_prefix_that_would_not_be_a_valid_xs_id(bad_prefix):
    with pytest.raises(ValueError, match="valid xs:ID"):
        IdFactory().new_id(bad_prefix)


@pytest.mark.parametrize(
    "good_prefix",
    ["material", "material_template", "material-template", "material.template", "_material", "ex1"],
)
def test_new_id_accepts_a_prefix_that_is_itself_a_valid_xs_id(good_prefix):
    assert IdFactory().new_id(good_prefix) == f"{good_prefix}1"


def test_new_id_rejects_bad_prefix_even_after_a_good_prefix_was_already_used():
    ids = IdFactory()
    ids.new_id("material")
    with pytest.raises(ValueError, match="valid xs:ID"):
        ids.new_id("123")


def test_new_id_only_validates_a_prefix_once_per_factory():
    # Once a prefix has been accepted, reusing it should never re-raise --
    # only the first call for a given prefix needs to validate it.
    ids = IdFactory()
    assert ids.new_id("material") == "material1"
    assert ids.new_id("material") == "material2"


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


# ---------------------------------------------------------------------------
# values=: homogeneity is checked across the whole list, not just values[0]
# ---------------------------------------------------------------------------

def test_infer_property_rejects_heterogeneous_values():
    # Before the fix, only values[0] (int) was inspected, so this silently
    # produced an IntListType carrying the string "abc" as one of its ints.
    with pytest.raises(TypeError, match="homogeneous"):
        infer_property("ex:k", values=[1, 2, "abc"])


def test_infer_content_rejects_heterogeneous_values():
    with pytest.raises(TypeError, match="homogeneous"):
        infer_content("ex:wave", values=[1.0, 2.0, "abc"])


def test_infer_property_rejects_bool_mixed_with_int():
    # bool is a Python subclass of int, so a naive `isinstance(v, int)`
    # homogeneity check would wrongly accept this; bool/int must map to
    # different (BooleanListType vs IntListType) MaiML list types.
    with pytest.raises(TypeError, match="homogeneous"):
        infer_property("ex:k", values=[True, False, 1])


def test_infer_property_accepts_bytes_and_bytearray_together():
    # bytes and bytearray both legitimately map to Base64BinaryListType --
    # an exact type(values[0]) == type(v) check would wrongly reject this.
    prop = infer_property("ex:k", values=[b"abc", bytearray(b"xyz")])
    assert isinstance(prop, m.Base64BinaryListType)


def test_infer_property_heterogeneous_error_names_the_offending_element():
    with pytest.raises(TypeError, match=r"element 2 is 'str'"):
        infer_property("ex:k", values=[1, 2, "abc"])


# ---------------------------------------------------------------------------
# xsi_type=: explicit override, mainly for protocol placeholders with no
# value yet (xsi:type is still required by the schema even then)
# ---------------------------------------------------------------------------

def test_infer_property_xsi_type_class_builds_value_less_placeholder():
    prop = infer_property("ex:temperature", xsi_type=m.FloatType, units="degC")
    assert isinstance(prop, m.FloatType)
    assert prop.value is None
    assert prop.units == "degC"


def test_infer_property_xsi_type_accepts_the_xsi_type_name_too():
    prop = infer_property("ex:temperature", xsi_type="floatType")
    assert isinstance(prop, m.FloatType)


def test_infer_property_without_xsi_type_or_value_raises():
    with pytest.raises(ValueError, match="xsi:type"):
        infer_property("ex:temperature")


def test_infer_property_xsi_type_overrides_inference_even_when_a_value_is_given():
    # a Python int would normally infer IntType -- xsi_type= forces DecimalType
    prop = infer_property("ex:count", value=5, xsi_type=m.DecimalType)
    assert isinstance(prop, m.DecimalType)
    assert prop.value == 5


def test_infer_property_rejects_a_content_class_as_xsi_type():
    with pytest.raises(TypeError, match="not a maiml_domain property class"):
        infer_property("ex:foo", xsi_type=m.ContentFloatListType)


def test_infer_property_xsi_type_property_list_type_has_no_value_or_values_param():
    """PropertyListType is a pure container (its own __init__ hardcodes
    values=[] and accepts neither value= nor values=) -- infer_property must
    still be able to build it via xsi_type=, forwarding only kwargs that
    class actually accepts."""
    child = infer_property("ex:child", value=1)
    group = infer_property("ex:group", xsi_type=m.PropertyListType, properties=[child])
    assert isinstance(group, m.PropertyListType)
    assert group.properties == [child]


def test_infer_content_xsi_type_builds_value_less_placeholder():
    content = infer_content("ex:spectrum", xsi_type=m.ContentFloatListType, axis="wavenumber", size=10)
    assert isinstance(content, m.ContentFloatListType)
    assert content.values == []
    assert content.axis == "wavenumber"


def test_infer_content_without_xsi_type_or_values_raises():
    with pytest.raises(ValueError, match="xsi:type"):
        infer_content("ex:spectrum")


def test_infer_content_rejects_a_property_class_as_xsi_type():
    with pytest.raises(TypeError, match="not a maiml_domain content class"):
        infer_content("ex:foo", xsi_type=m.FloatType)


# ---------------------------------------------------------------------------
# XsiTypeRegistry: keep a protocol placeholder and its matching <data>
# recording on the same xsi:type for a given key
# ---------------------------------------------------------------------------

def test_xsi_type_registry_keeps_protocol_placeholder_and_measured_data_in_sync():
    registry = XsiTypeRegistry()
    placeholder = infer_property("ex:temperature", xsi_type=m.FloatType, registry=registry)
    assert placeholder.value is None

    # the measured value is an int (20) -- would normally infer IntType, but
    # the registry remembers the protocol declared floatType for this key
    measured = infer_property("ex:temperature", value=20, registry=registry)
    assert type(measured) is m.FloatType
    assert measured.value == 20


def test_xsi_type_registry_conflicting_registration_raises():
    registry = XsiTypeRegistry()
    infer_property("ex:temperature", xsi_type=m.FloatType, registry=registry)
    with pytest.raises(ValueError, match="already registered"):
        infer_property("ex:temperature", xsi_type=m.IntType, registry=registry)


def test_xsi_type_registry_rejects_property_content_key_reuse():
    registry = XsiTypeRegistry()
    infer_property("ex:foo", xsi_type=m.FloatType, registry=registry)
    with pytest.raises(TypeError, match="not a content class"):
        infer_content("ex:foo", values=[1.0], registry=registry)


def test_xsi_type_registry_works_for_content_too():
    registry = XsiTypeRegistry()
    infer_content("ex:spectrum", xsi_type=m.ContentFloatListType, registry=registry)
    measured = infer_content("ex:spectrum", values=[1, 2, 3], registry=registry)  # ints
    assert type(measured) is m.ContentFloatListType
    assert measured.values == [1, 2, 3]


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
