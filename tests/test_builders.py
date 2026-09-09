from __future__ import annotations

import datetime as dt
from decimal import Decimal

import maiml_domain as m
import pytest

from pymaiml.builders import (
    IdFactory,
    InsertionValue,
    XsiTypeRegistry,
    create_instance,
    create_instances,
    infer_content,
    infer_property,
    new_complete_event,
)


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


# ---------------------------------------------------------------------------
# create_instance() / create_instances(): Template -> Instance
# ---------------------------------------------------------------------------

def _place_ref(id_factory: IdFactory, place_id: str) -> m.PlaceRefType:
    # MaterialTemplateType/ConditionTemplateType/ResultTemplateType all
    # require at least one PlaceRefType -- these tests don't exercise PNML
    # topology at all, so the referenced place doesn't need to exist as its
    # own PlaceType anywhere; it just needs to be present to satisfy that
    # constructor-level requirement.
    return m.PlaceRefType(id=id_factory.new_id("ref"), ref=place_id)


def _material_template(id_factory: IdFactory, template_id: str, **content_kwargs) -> m.MaterialTemplateType:
    content = m.GlobalObjectContent(uuid=id_factory.new_uuid(), **content_kwargs)
    return m.MaterialTemplateType(
        id=template_id,
        place_refs=[_place_ref(id_factory, f"{template_id}-place")],
        content=content,
        template_refs=[],
    )


def test_create_instance_picks_matching_instance_class_per_template_kind(id_factory):
    material_tmpl = m.MaterialTemplateType(
        id="mt1", place_refs=[_place_ref(id_factory, "p1")], content=None, template_refs=[]
    )
    condition_tmpl = m.ConditionTemplateType(
        id="ct1", place_refs=[_place_ref(id_factory, "p2")], content=None, template_refs=[]
    )
    result_tmpl = m.ResultTemplateType(
        id="rt1", place_refs=[_place_ref(id_factory, "p3")], content=None, template_refs=[]
    )

    material = create_instance(material_tmpl, id="material1", id_factory=id_factory)
    condition = create_instance(condition_tmpl, id="condition1", id_factory=id_factory)
    result = create_instance(result_tmpl, id="result1", id_factory=id_factory)

    assert isinstance(material, m.MaterialType)
    assert isinstance(condition, m.ConditionType)
    assert isinstance(result, m.ResultType)


def test_create_instance_rejects_a_non_template_object():
    with pytest.raises(TypeError, match="not a template class"):
        create_instance(m.MaterialType(id="x", ref="y", content=None, instance_refs=[]), id="z", id_factory=IdFactory())


def test_create_instance_sets_ref_to_the_template_id_and_generates_a_fresh_id(id_factory):
    template = _material_template(id_factory, "template-A", name="Sample A")
    instance = create_instance(template, id="material1", id_factory=id_factory)

    assert instance.id == "material1"
    assert instance.ref == "template-A"
    assert instance.id != template.id


def test_create_instance_copies_name_description_annotation_as_is(id_factory):
    template = _material_template(
        id_factory, "template-A", name="Sample A", description="desc", annotation="note"
    )
    instance = create_instance(template, id="material1", id_factory=id_factory)

    assert instance.content.name == "Sample A"
    assert instance.content.description == "desc"
    assert instance.content.annotation == "note"


def test_create_instance_always_generates_a_fresh_content_uuid(id_factory):
    template = _material_template(id_factory, "template-A", name="Sample A")
    instance = create_instance(template, id="material1", id_factory=id_factory)

    assert instance.content.uuid is not None
    assert instance.content.uuid != template.content.uuid


def test_create_instance_gives_a_fresh_content_when_template_has_none(id_factory):
    template = m.MaterialTemplateType(
        id="template-A", place_refs=[_place_ref(id_factory, "p1")], content=None, template_refs=[]
    )
    instance = create_instance(template, id="material1", id_factory=id_factory)

    assert instance.content is not None
    assert instance.content.uuid is not None


def test_create_instance_deep_copies_properties_and_contents_so_instance_edits_do_not_leak_back(id_factory):
    template = _material_template(
        id_factory,
        "template-A",
        properties=[m.StringType(key="ex:color", value="blue")],
        contents=[m.ContentIntListType(key="ex:series", values=[1, 2, 3])],
    )
    instance = create_instance(template, id="material1", id_factory=id_factory)

    assert instance.content.properties[0].value == "blue"
    assert instance.content.contents[0].values == [1, 2, 3]

    instance.content.properties[0].value = "red"
    instance.content.contents[0].values.append(4)

    assert template.content.properties[0].value == "blue"
    assert template.content.contents[0].values == [1, 2, 3]


def test_create_instance_deep_copies_encryption_and_skips_insertions_properties_contents(id_factory):
    # GlobalObjectContent's own __post_init__ makes encryption mutually
    # exclusive with name/description/annotation/insertions/properties/
    # contents (globalObjectContentGroup is an xs:choice), so a template
    # using encryption has nothing else for _build_instance_content to
    # copy -- and, by that same constraint, the template's content could
    # never have had a name/description/annotation set alongside it either.
    encryption = m.EncryptionType(encrypted_data="ZGF0YQ==")
    template = _material_template(id_factory, "template-A", encryption=encryption)

    instance = create_instance(template, id="material1", id_factory=id_factory)

    assert instance.content.encryption is not None
    assert instance.content.encryption is not template.content.encryption
    assert instance.content.encryption.encrypted_data == "ZGF0YQ=="
    assert instance.content.name is None
    assert instance.content.properties == []
    assert instance.content.insertions == []


def test_create_instance_regenerates_insertions_with_new_uri_and_hash(id_factory):
    old_insertion = m.InsertionType(
        uri="file://template.csv",
        hash=m.HashType(value=b"0" * 32, method="SHA-256"),
        uuid=id_factory.new_uuid(),
        format="text/csv",
    )
    template = _material_template(id_factory, "template-A", insertions=[old_insertion])

    new_value = InsertionValue(uri="file://instance-001.csv", hash=m.HashType(value=b"1" * 32, method="SHA-256"))
    instance = create_instance(template, id="material1", id_factory=id_factory, insertion_values=[new_value])

    new_insertion = instance.content.insertions[0]
    assert new_insertion.uri == "file://instance-001.csv"
    assert new_insertion.hash.value == b"1" * 32
    assert new_insertion.format == "text/csv"  # inherited from the template's insertion
    assert new_insertion.uuid != old_insertion.uuid


def test_create_instance_insertion_value_can_override_format_and_uuid(id_factory):
    old_insertion = m.InsertionType(
        uri="file://template.csv", hash=m.HashType(value=b"0" * 32), uuid=id_factory.new_uuid(), format="text/csv"
    )
    template = _material_template(id_factory, "template-A", insertions=[old_insertion])
    explicit_uuid = id_factory.new_uuid()

    new_value = InsertionValue(
        uri="file://instance-001.json",
        hash=m.HashType(value=b"1" * 32),
        uuid=explicit_uuid,
        format="application/json",
    )
    instance = create_instance(template, id="material1", id_factory=id_factory, insertion_values=[new_value])

    new_insertion = instance.content.insertions[0]
    assert new_insertion.format == "application/json"
    assert new_insertion.uuid is explicit_uuid


def test_create_instance_insertions_are_matched_to_insertion_values_by_position(id_factory):
    # The whole point of matching by position rather than by uri: two
    # template insertions may legitimately share the same uri (schema
    # does not require uri to be unique among one content's insertions),
    # and each must still get its own distinct new uri/hash.
    old_a = m.InsertionType(uri="data.csv", hash=m.HashType(value=b"0" * 32), uuid=id_factory.new_uuid())
    old_b = m.InsertionType(uri="data.csv", hash=m.HashType(value=b"0" * 32), uuid=id_factory.new_uuid())
    template = _material_template(id_factory, "template-A", insertions=[old_a, old_b])

    value_a = InsertionValue(uri="file://instance-a.csv", hash=m.HashType(value=b"1" * 32))
    value_b = InsertionValue(uri="file://instance-b.csv", hash=m.HashType(value=b"2" * 32))
    instance = create_instance(
        template, id="material1", id_factory=id_factory, insertion_values=[value_a, value_b]
    )

    assert instance.content.insertions[0].uri == "file://instance-a.csv"
    assert instance.content.insertions[1].uri == "file://instance-b.csv"


def test_create_instance_missing_insertion_values_raises(id_factory):
    old_insertion = m.InsertionType(uri="file://template.csv", hash=m.HashType(value=b"0" * 32), uuid=id_factory.new_uuid())
    template = _material_template(id_factory, "template-A", insertions=[old_insertion])

    with pytest.raises(ValueError, match="insertion_values was not supplied"):
        create_instance(template, id="material1", id_factory=id_factory)


def test_create_instance_insertion_values_length_mismatch_raises(id_factory):
    old_a = m.InsertionType(uri="file://a.csv", hash=m.HashType(value=b"0" * 32), uuid=id_factory.new_uuid())
    old_b = m.InsertionType(uri="file://b.csv", hash=m.HashType(value=b"0" * 32), uuid=id_factory.new_uuid())
    template = _material_template(id_factory, "template-A", insertions=[old_a, old_b])

    only_one_value = [InsertionValue(uri="file://instance-a.csv", hash=m.HashType(value=b"1" * 32))]
    with pytest.raises(ValueError, match="exactly one entry"):
        create_instance(template, id="material1", id_factory=id_factory, insertion_values=only_one_value)

    too_many_values = [
        InsertionValue(uri="file://instance-a.csv", hash=m.HashType(value=b"1" * 32)),
        InsertionValue(uri="file://instance-b.csv", hash=m.HashType(value=b"2" * 32)),
        InsertionValue(uri="file://instance-c.csv", hash=m.HashType(value=b"3" * 32)),
    ]
    with pytest.raises(ValueError, match="exactly one entry"):
        create_instance(template, id="material1", id_factory=id_factory, insertion_values=too_many_values)


def test_create_instance_ignores_insertion_values_when_template_has_no_insertions(id_factory):
    # A template with zero insertions needs no insertion_values at all --
    # confirms the empty case short-circuits before the length check.
    template = _material_template(id_factory, "template-A", insertions=[])
    instance = create_instance(template, id="material1", id_factory=id_factory)
    assert instance.content.insertions == []


def test_create_instance_translates_template_refs_to_instance_refs_via_map(id_factory):
    template_b = _material_template(id_factory, "template-B", name="B")
    template_a = m.MaterialTemplateType(
        id="template-A",
        place_refs=[_place_ref(id_factory, "p-a")],
        content=m.GlobalObjectContent(uuid=id_factory.new_uuid(), name="A"),
        template_refs=[m.TemplateRefType(id="tref1", ref="template-B", name="see B", description=None)],
    )

    instance_b = create_instance(template_b, id="material-B-1", id_factory=id_factory)
    instance_a = create_instance(
        template_a,
        id="material-A-1",
        id_factory=id_factory,
        template_instance_map={"template-B": instance_b.id},
    )

    assert len(instance_a.instance_refs) == 1
    ref = instance_a.instance_refs[0]
    assert isinstance(ref, m.InstanceRefType)
    assert ref.ref == instance_b.id
    assert ref.name == "see B"


def test_create_instance_never_copies_the_template_id_itself_as_an_instance_ref(id_factory):
    # A templateRef with no entry anywhere in template_instance_map must
    # raise, not silently fall back to copying the template's own id as if
    # it were a valid instance id (template id space and instance id space
    # are never the same value).
    template_a = m.MaterialTemplateType(
        id="template-A",
        place_refs=[_place_ref(id_factory, "p-a")],
        content=None,
        template_refs=[m.TemplateRefType(id="tref1", ref="template-B", name=None, description=None)],
    )

    with pytest.raises(ValueError, match="template_instance_map has no entry"):
        create_instance(template_a, id="material-A-1", id_factory=id_factory)


def test_create_instance_has_no_place_refs_attribute_to_copy():
    # MaterialType/ConditionType/ResultType simply don't have a place_refs
    # parameter -- confirms create_instance() has nothing to (and cannot)
    # copy there.
    import inspect

    assert "place_refs" not in inspect.signature(m.MaterialType.__init__).parameters


# ---------------------------------------------------------------------------
# create_instances(): batch orchestration
# ---------------------------------------------------------------------------

def test_create_instances_reserves_ids_up_front_so_forward_references_resolve(id_factory):
    # Template A references Template B, but B comes *after* A in the list --
    # this only works if every id is reserved before any instance is built.
    template_b = _material_template(id_factory, "template-B", name="B")
    template_a = m.MaterialTemplateType(
        id="template-A",
        place_refs=[_place_ref(id_factory, "p-a")],
        content=None,
        template_refs=[m.TemplateRefType(id="tref1", ref="template-B", name=None, description=None)],
    )

    instances = create_instances([template_a, template_b], id_factory=id_factory)
    instance_a, instance_b = instances

    assert instance_a.ref == "template-A"
    assert instance_b.ref == "template-B"
    assert instance_a.instance_refs[0].ref == instance_b.id


def test_create_instances_returns_instances_in_the_same_order_as_templates(id_factory):
    templates = [_material_template(id_factory, f"template-{i}") for i in range(3)]
    instances = create_instances(templates, id_factory=id_factory)
    assert [instance.ref for instance in instances] == ["template-0", "template-1", "template-2"]


def test_create_instances_assigns_instance_ids_with_the_kind_specific_prefix(id_factory):
    material_tmpl = m.MaterialTemplateType(id="mt1", place_refs=[_place_ref(id_factory, "p1")], content=None, template_refs=[])
    condition_tmpl = m.ConditionTemplateType(id="ct1", place_refs=[_place_ref(id_factory, "p2")], content=None, template_refs=[])
    result_tmpl = m.ResultTemplateType(id="rt1", place_refs=[_place_ref(id_factory, "p3")], content=None, template_refs=[])

    instances = create_instances([material_tmpl, condition_tmpl, result_tmpl], id_factory=id_factory)

    assert instances[0].id.startswith("material")
    assert instances[1].id.startswith("condition")
    assert instances[2].id.startswith("result")


def test_create_instances_rejects_the_same_template_id_twice_in_one_batch(id_factory):
    template = _material_template(id_factory, "template-A")
    with pytest.raises(ValueError, match="more than once"):
        create_instances([template, template], id_factory=id_factory)


def test_create_instances_rejects_a_non_template_object():
    with pytest.raises(TypeError, match="not a template class"):
        create_instances([m.MaterialType(id="x", ref="y", content=None, instance_refs=[])], id_factory=IdFactory())


def test_create_instances_existing_instance_map_resolves_references_outside_the_batch(id_factory):
    # template-B was instantiated in an earlier, separate call/batch --
    # only template-A is being instantiated now, and its templateRef must
    # still resolve via the caller-supplied existing_instance_map.
    template_a = m.MaterialTemplateType(
        id="template-A",
        place_refs=[_place_ref(id_factory, "p-a")],
        content=None,
        template_refs=[m.TemplateRefType(id="tref1", ref="template-B", name=None, description=None)],
    )

    instances = create_instances(
        [template_a], id_factory=id_factory, existing_instance_map={"template-B": "material-B-existing"}
    )

    assert instances[0].instance_refs[0].ref == "material-B-existing"


def test_create_instances_own_batch_wins_over_existing_instance_map_on_collision(id_factory):
    # If a template id appears in both this batch and existing_instance_map,
    # the batch's own freshly-generated instance id must take precedence --
    # a template being instantiated right now is never "already existing".
    template_b = _material_template(id_factory, "template-B", name="B")
    template_a = m.MaterialTemplateType(
        id="template-A",
        place_refs=[_place_ref(id_factory, "p-a")],
        content=None,
        template_refs=[m.TemplateRefType(id="tref1", ref="template-B", name=None, description=None)],
    )

    instances = create_instances(
        [template_a, template_b],
        id_factory=id_factory,
        existing_instance_map={"template-B": "stale-instance-id"},
    )
    instance_a, instance_b = instances

    assert instance_a.instance_refs[0].ref == instance_b.id
    assert instance_a.instance_refs[0].ref != "stale-instance-id"


def test_create_instances_missing_reference_raises_even_across_the_whole_batch(id_factory):
    template_a = m.MaterialTemplateType(
        id="template-A",
        place_refs=[_place_ref(id_factory, "p-a")],
        content=None,
        template_refs=[m.TemplateRefType(id="tref1", ref="template-missing", name=None, description=None)],
    )
    template_b = _material_template(id_factory, "template-B")

    with pytest.raises(ValueError, match="template_instance_map has no entry"):
        create_instances([template_a, template_b], id_factory=id_factory)


def test_create_instances_insertion_values_are_keyed_by_template_id_then_positional(id_factory):
    old_insertion = m.InsertionType(uri="file://template.csv", hash=m.HashType(value=b"0" * 32), uuid=id_factory.new_uuid())
    template = _material_template(id_factory, "template-A", insertions=[old_insertion])

    instances = create_instances(
        [template],
        id_factory=id_factory,
        insertion_values={
            "template-A": [InsertionValue(uri="file://instance.csv", hash=m.HashType(value=b"1" * 32))]
        },
    )

    assert instances[0].content.insertions[0].uri == "file://instance.csv"
