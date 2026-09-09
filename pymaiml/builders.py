"""
pymaiml.builders
==================

Ergonomic helpers on top of the raw maiml_domain classes, aimed at six
sources of boilerplate/mistakes identified while hand-building MaiML files
directly against maiml_domain during MaiML-Domain's own development:

  1. Picking the right one of ~70 property/content classes for a Python
     value (`infer_property` / `infer_content`).
  2. A protocol element's generic data container is usually a *placeholder*
     -- it declares what will eventually be measured, but (unlike the
     corresponding <data> element built later) has no value/values of its
     own yet. xsi:type is still required by the schema even then, so it
     must be possible to say it explicitly instead of inferring it from a
     value that doesn't exist (`infer_property`/`infer_content`'s
     `xsi_type=` parameter).
  3. Keeping that placeholder's xsi:type and the xsi:type of the matching
     <data> property/content for the *same* key in sync -- a protocol
     declaring `ex:temperature` as floatType must not end up with a
     `<data>` recording of `ex:temperature` that serializes as intType just
     because the measured Python value happened to be a whole number
     (`XsiTypeRegistry`, shared across the `infer_property`/`infer_content`
     calls for both the protocol and the data side).
  4. Keeping id/uuid values unique across a large object tree
     (`IdFactory`).
  5. Remembering that recording a material/condition/result in <data>
     requires a matching lifecycle:transition="complete" <event> in
     <eventLog>, plus the exact XES namespace URI for the "lifecycle:"
     prefix -- this is EVT-02 in the maiml-schema-validator skill's rule
     set, and was hand-written three separate times in MaiML-Domain's own
     test script before this module existed (`new_complete_event`).
  6. Turning a materialTemplate/conditionTemplate/resultTemplate into the
     material/condition/result instance it describes -- assigning the
     instance's own id/uuid (never reused from the template), copying the
     template's generic data container, and re-pointing every templateRef
     to the right instanceRef once its target has been instantiated too
     (`create_instance` / `create_instances`).

This is the pymaiml.query -> pymaiml.builders handoff for this kind of
work: pymaiml.query.get_templates() selects which templates to act on
(by kind, by instruction_id, ...); pymaiml.builders.create_instance(s)()
turns the selected maiml_domain.protocol template objects into
maiml_domain.data instance objects. Neither module reaches into the
other for this -- the caller passes query's output as builders' input.

This module does not attempt a full "session"/fluent builder over the
entire object graph -- that would need to model every XSD content model's
ordering and cardinality a second time on top of maiml_domain and
pymaiml.serialization, and untested code for a ~70-class surface is worse
than no code. What's here is scoped to what could be written and verified
against real validation output.
"""
from __future__ import annotations

import copy
import dataclasses
import inspect
import itertools
import re
import uuid as _uuidlib
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Type, Union

import maiml_domain as m

from ._xsi_registry import class_for_xsi_type, is_content_class, is_property_class
from .query import Instance, Template

__all__ = [
    "IdFactory",
    "LIFECYCLE_NS",
    "XsiTypeRegistry",
    "infer_property",
    "infer_content",
    "new_complete_event",
    "InsertionValue",
    "create_instance",
    "create_instances",
]

# The exact XES lifecycle extension URI that maiml-schema-validator's NS-01
# rule requires the "lifecycle:" key prefix to be bound to. Declare this as
# xmlns:lifecycle on the root <maiml> element (see
# pymaiml.serialization.dumps' extra_namespaces parameter).
LIFECYCLE_NS = "http://www.xes-standard.org/lifecycle.xesext#"


# ---------------------------------------------------------------------------
# IdFactory
# ---------------------------------------------------------------------------

# xs:ID's lexical space is xs:NCName's (Name minus anything containing a
# colon). This is an ASCII-first, practical approximation of the real XML
# NCName production (NCNameStartChar/NCNameChar formally span specific
# Unicode "Letter"/"CombiningChar"/"Extender" ranges) rather than a
# byte-for-byte transcription of it: with re.UNICODE, `\w` already covers
# Unicode letters/digits/underscore, so `[^\W\d]` (a "word" character that
# is not a digit) is letters-or-underscore for the required non-digit
# first character, and `[\w.-]*` covers the rest (adding '.'/'-', which
# NCName allows but \w doesn't). It rejects what actually matters for a
# generated prefix -- a leading digit, ':', whitespace, and other
# punctuation -- without having to hand-encode the XML spec's Unicode
# character tables.
_NCNAME_RE = re.compile(r"^[^\W\d][\w.-]*$", re.UNICODE)


def _is_valid_ncname(value: str) -> bool:
    return bool(value) and _NCNAME_RE.match(value) is not None


class IdFactory:
    """
    Generates unique xs:ID values and MaiML uuid values.

    MaiML requires every id attribute to be unique within the file
    (xs:ID) and every global object to carry a uuid (a real, randomly
    generated one -- name-based v3/v5 UUIDs are a separate, deliberate
    choice for entities that must stay stable across files, so this
    factory does not attempt to guess when that applies).

    >>> ids = IdFactory()
    >>> ids.new_id("material")
    'material1'
    >>> ids.new_id("material")
    'material2'
    >>> isinstance(ids.new_uuid(), m.Uuid)
    True

    Every id this factory generates is `prefix` + an integer, so `prefix`
    itself must already be a valid xs:ID (NCName) on its own -- appending
    digits to a valid NCName always yields another valid NCName, but
    e.g. new_id("123") would produce "1231", which starts with a digit and
    is not a valid xs:ID. new_id() rejects such a prefix with ValueError
    the first time it's used, rather than silently handing back an id that
    passes through this SDK fine but fails XSD validation much later:

    >>> IdFactory().new_id("123")
    Traceback (most recent call last):
        ...
    ValueError: IdFactory.new_id: prefix='123' would not produce a valid xs:ID (NCName) -- xs:ID must not start with a digit, and must not contain ':' or other characters outside [A-Za-z0-9_.-] (plus Unicode letters). Pass a prefix that is itself a valid xs:ID.

    When adding new elements to a file that already has other elements in
    it (e.g. loading an existing protocol via
    pymaiml.serialization.load() and building new data/eventLog on top of
    it), reserve the loaded ids first so this factory's own numbering can
    never collide with them, even if a prefix happens to coincide:

    >>> ids = IdFactory.from_existing_ids(["material_template1", "place1"])
    >>> ids.new_id("material_template")  # skips 1 -- already reserved
    'material_template2'
    """

    def __init__(self) -> None:
        self._counters: Dict[str, itertools.count] = {}
        self._issued: set = set()

    def new_id(self, prefix: str) -> str:
        counter = self._counters.get(prefix)
        if counter is None:
            if not _is_valid_ncname(prefix):
                raise ValueError(
                    f"IdFactory.new_id: prefix={prefix!r} would not produce a "
                    "valid xs:ID (NCName) -- xs:ID must not start with a "
                    "digit, and must not contain ':' or other characters "
                    "outside [A-Za-z0-9_.-] (plus Unicode letters). Pass a "
                    "prefix that is itself a valid xs:ID."
                )
            counter = itertools.count(1)
            self._counters[prefix] = counter
        while True:
            candidate = f"{prefix}{next(counter)}"
            if candidate not in self._issued:
                self._issued.add(candidate)
                return candidate

    def new_uuid(self) -> "m.Uuid":
        return m.Uuid(str(_uuidlib.uuid4()))

    def reserve(self, ids) -> None:
        """
        Mark ids already used elsewhere (typically every id in a file
        loaded via pymaiml.serialization.load/loads -- see LoadedMaiml.ids)
        so new_id() will never return one of them. Safe to call more than
        once, and safe to call with ids this factory has already issued
        itself.
        """
        self._issued.update(ids)

    @classmethod
    def from_existing_ids(cls, ids) -> "IdFactory":
        """Convenience constructor: build a fresh IdFactory with `ids`
        pre-reserved. Equivalent to IdFactory() followed by .reserve(ids)."""
        factory = cls()
        factory.reserve(ids)
        return factory


# ---------------------------------------------------------------------------
# XsiTypeRegistry
# ---------------------------------------------------------------------------

class XsiTypeRegistry:
    """
    Remembers, per `key`, which concrete maiml_domain property/content class
    was chosen the first time infer_property()/infer_content() saw that key
    -- so a protocol's value-less placeholder (built with xsi_type= since
    there is no value to infer from) and the actual measured property/
    content recorded later in <data> for the *same* key are guaranteed to
    share one xsi:type, even when the measured Python value wouldn't by
    itself infer to that same class (e.g. a measured value of `20` (an
    `int`) for a key the protocol declared as floatType).

    Pass one shared XsiTypeRegistry instance to every infer_property()/
    infer_content() call across a document's protocol and data sections.
    This relies on MaiML's usual convention that a given `key` denotes one
    semantic property throughout a document (per the Annex A/B thesaurus)
    -- if a key genuinely needs a different type in a different place, give
    it a distinct key instead; registering a second, different class for a
    key already registered raises ValueError rather than silently
    overwriting it.

    >>> reg = XsiTypeRegistry()
    >>> placeholder = infer_property("ex:temperature", xsi_type=m.FloatType, registry=reg)
    >>> measured = infer_property("ex:temperature", value=20, registry=reg)
    >>> type(measured) is m.FloatType
    True

    Note -- repeated keys under one parent: MaiML-Schema-1_0 places no
    uniqueness constraint on `key` at all (genericDataContainerGroup is
    just ``property*, content*`` -- no xs:unique/xs:key anywhere in the
    schema), so the *same* key appearing more than once directly under the
    *same* parent (e.g. two temperature readings both keyed "ex:temperature"
    in one <material>'s properties) is schema-valid and passes validation.
    XsiTypeRegistry is fine with that as long as every occurrence resolves
    to the same xsi:type (which is the normal case, and all repeats after
    the first will simply reuse what's already registered). If you
    deliberately want a *different* xsi:type for a repeated key -- an
    unusual case -- pass `registry=` only on the calls where you want the
    shared-type check, and omit it (call infer_property()/infer_content()
    without registry=) for the one(s) that should be exempt from it.
    """

    def __init__(self) -> None:
        self._by_key: Dict[str, type] = {}

    def get(self, key: str) -> Optional[type]:
        return self._by_key.get(key)

    def register(self, key: str, cls: type) -> None:
        existing = self._by_key.get(key)
        if existing is not None and existing is not cls:
            raise ValueError(
                f"XsiTypeRegistry: key {key!r} is already registered as "
                f"{existing.__name__}; got {cls.__name__}. A given key must "
                "resolve to one xsi:type throughout a document -- use a "
                "different key if this is genuinely a different property."
            )
        self._by_key[key] = cls


# ---------------------------------------------------------------------------
# property / content type inference
# ---------------------------------------------------------------------------

# Order matters: bool is a subclass of int in Python, so it must be checked
# before int. Checked top-to-bottom via isinstance in _infer_scalar_class.
_SCALAR_CLASS_BY_TYPE = [
    (bool, m.BooleanType),
    (Decimal, m.DecimalType),
    (int, m.IntType),
    (float, m.FloatType),
    (datetime, m.DateTimeType),
    (bytes, m.Base64BinaryType),
    (bytearray, m.Base64BinaryType),
    (m.Uuid, m.UuidType),
    (str, m.StringType),
]

# For a homogeneous non-empty list of Python values -> the matching
# property *List type. Content types only ever come as lists (no scalar
# content type exists in MaiML), so infer_content reuses this same table
# against pymaiml's content-list equivalents.
_LIST_CLASS_BY_TYPE = [
    (bool, m.BooleanListType),
    (Decimal, m.DecimalListType),
    (int, m.IntListType),
    (float, m.FloatListType),
    (datetime, m.DateTimeListType),
    (bytes, m.Base64BinaryListType),
    (bytearray, m.Base64BinaryListType),
    (m.Uuid, m.UuidListType),
    (str, m.StringListType),
]

_CONTENT_LIST_CLASS_BY_TYPE = [
    (bool, m.ContentBooleanListType),
    (Decimal, m.ContentDecimalListType),
    (int, m.ContentIntListType),
    (float, m.ContentFloatListType),
    (datetime, m.ContentDateTimeListType),
    (bytes, m.ContentBase64BinaryListType),
    (bytearray, m.ContentBase64BinaryListType),
    (m.Uuid, m.ContentUuidListType),
    (str, m.ContentStringListType),
]


def _match(value_type: type, table) -> Optional[type]:
    for py_type, cls in table:
        if issubclass(value_type, py_type):
            return cls
    return None


def _infer_homogeneous_list_class(values: List[Any], table, *, caller: str, kind_noun: str) -> type:
    """
    Resolve the single list-type class every element of `values` maps to
    via `table`, raising TypeError if the elements are not homogeneous.

    Used by infer_property (list branch) and infer_content, both of which
    document their `values=` as "must be non-empty and homogeneous" but,
    before this helper existed, only ever looked at values[0] -- so e.g.
    values=[1, 2, "abc"] silently picked IntListType and let "abc" through,
    with the mistake surfacing (if at all) only much later as an opaque XSD
    validation failure instead of here, at the point a builder could still
    give a clear error.

    "Homogeneous" means every element resolves to the SAME cls via `table`
    (the same rule `_match` applies to values[0]) -- not that every
    element's exact Python class matches values[0]'s. That distinction
    matters in both directions:
      - bytes and bytearray are two separate `table` rows that both map to
        Base64Binary*ListType, and must be accepted together;
      - bool must NOT be accepted alongside int, even though bool is a
        Python subclass of int, because `table` checks bool before int
        (see _SCALAR_CLASS_BY_TYPE's comment) and so maps them to
        different, XSD-distinct list types (boolean vs int) -- an
        isinstance(v, int) check would miss this, since isinstance(True,
        int) is True.
    """
    first_cls = _match(type(values[0]), table)
    if first_cls is None:
        raise TypeError(
            f"{caller}: no known {kind_noun} list type for element type "
            f"{type(values[0])!r}; pass xsi_type= explicitly, or construct "
            "the maiml_domain class directly."
        )
    bad_index = next((i for i, v in enumerate(values) if _match(type(v), table) is not first_cls), None)
    if bad_index is not None:
        raise TypeError(
            f"{caller}: values must be non-empty and homogeneous -- element 0 is "
            f"{type(values[0]).__name__!r} (-> {first_cls.__name__}), but element "
            f"{bad_index} is {type(values[bad_index]).__name__!r}, which does not "
            "belong to the same inferred type. Pass xsi_type= explicitly, or "
            "construct the maiml_domain class directly, if a heterogeneous list "
            "is genuinely intended."
        )
    return first_cls


def _resolve_xsi_type(xsi_type: Optional[Union[str, type]]) -> Optional[type]:
    """xsi_type= accepts either the maiml_domain class itself (m.FloatType)
    or the xsi:type name it corresponds to ("floatType"), resolved via
    pymaiml._xsi_registry."""
    if xsi_type is None:
        return None
    if isinstance(xsi_type, str):
        return class_for_xsi_type(xsi_type)
    return xsi_type


def _instantiate(cls: type, key: str, value: Any, values: Optional[List[Any]], kwargs: dict):
    """
    Construct cls(key=key, ...), passing value= or values= only if cls's own
    __init__ actually declares that parameter. This is what lets a
    no-payload container class -- PropertyListType's __init__ hardcodes
    values=[] and accepts neither `value` nor `values` itself -- be built
    via xsi_type= exactly like every other property/content class, and
    lets a value-less placeholder (xsi_type= given, value=/values= both
    None) fall through to that parameter's own default instead of being
    forced to an explicit None/[].
    """
    params = inspect.signature(cls.__init__).parameters
    call_kwargs = dict(kwargs)
    if "values" in params:
        if values is not None:
            call_kwargs["values"] = values
    elif "value" in params:
        call_kwargs["value"] = value
    return cls(key=key, **call_kwargs)


def infer_property(
    key: str,
    value: Any = None,
    values: Optional[List[Any]] = None,
    *,
    xsi_type: Optional[Union[str, type]] = None,
    registry: Optional[XsiTypeRegistry] = None,
    **kwargs,
):
    """
    Build a maiml_domain property instance.

    Normally the concrete class is chosen from the Python type of `value`
    (scalar) or the elements of `values` (list -- must be non-empty and
    homogeneous; this is enforced -- every element must belong to the same
    inferred type as values[0], e.g. all int or all str, or a TypeError is
    raised naming the offending element, rather than silently choosing a
    type from values[0] alone and letting the rest through unchecked).
    xsi:type is required by the schema regardless, so when there is no
    value yet to infer it from -- the common case for a protocol element's
    placeholder property -- pass it explicitly via `xsi_type=` (either the
    maiml_domain class, e.g. `m.FloatType`, or the xsi:type name, e.g.
    `"floatType"`). It is an error to have neither: a value/values to infer
    from, nor an explicit xsi_type=.

    Pass a shared `registry=` (an `XsiTypeRegistry`) across a document's
    protocol and data sections to guarantee the placeholder declared in the
    protocol and the actual measurement recorded later in <data> for the
    same key end up with the same xsi:type -- see XsiTypeRegistry.

    Extra kwargs (description=, units=, format_string=, encryption=, ...)
    are forwarded to the chosen class's constructor -- pass whatever that
    concrete class accepts; an unsupported kwarg (e.g. units= on a
    non-numeric type) raises TypeError from the underlying constructor,
    same as calling it directly.

    At most one of `value`/`values` may be given. For anything the
    inference table doesn't cover (xs:QName/IDREF/token/uri/language
    scalars, enumerations, list-of-mixed-types), pass xsi_type= explicitly
    or construct the maiml_domain class directly.
    """
    if value is not None and values is not None:
        raise ValueError("infer_property: pass at most one of value= or values=")

    cls = _resolve_xsi_type(xsi_type)
    if cls is not None and not is_property_class(cls):
        raise TypeError(f"infer_property: xsi_type={cls!r} is not a maiml_domain property class")

    if cls is None and registry is not None:
        cls = registry.get(key)
        if cls is not None and not is_property_class(cls):
            raise TypeError(
                f"infer_property: registry has key={key!r} registered as "
                f"{cls.__name__}, which is not a property class -- the same key is "
                "being used for both a property and a content container"
            )

    if cls is None:
        if values is not None:
            if not values:
                raise ValueError("infer_property: values must be non-empty to infer a type")
            cls = _infer_homogeneous_list_class(
                values, _LIST_CLASS_BY_TYPE, caller="infer_property", kind_noun="property"
            )
        elif value is not None:
            cls = _match(type(value), _SCALAR_CLASS_BY_TYPE)
            if cls is None:
                raise TypeError(
                    f"infer_property: no known scalar property type for {type(value)!r}; "
                    "pass xsi_type= explicitly, or construct the maiml_domain class directly."
                )
        else:
            raise ValueError(
                f"infer_property: xsi:type is required by the schema but could not be "
                f"determined for key={key!r} -- no value=/values= to infer it from. Pass "
                "xsi_type=<maiml_domain class or xsi:type name> explicitly; this is the "
                "common case for a protocol placeholder property that has no value yet."
            )

    if registry is not None:
        registry.register(key, cls)

    return _instantiate(cls, key, value, values, kwargs)


def infer_content(
    key: str,
    values: Optional[List[Any]] = None,
    *,
    xsi_type: Optional[Union[str, type]] = None,
    registry: Optional[XsiTypeRegistry] = None,
    **kwargs,
):
    """
    Build a maiml_domain content instance (always a list type -- MaiML has
    no scalar content type).

    Normally the concrete class is chosen from the Python type of `values`'
    elements (must be non-empty and homogeneous; this is enforced -- every
    element must belong to the same inferred type as values[0], or a
    TypeError is raised naming the offending element). xsi:type is
    required by the schema regardless, so when there are no values yet --
    the common case for a protocol element's placeholder content, which
    may only describe axis=/size= for now -- pass it explicitly via
    `xsi_type=`
    (either the maiml_domain class, e.g. `m.ContentFloatListType`, or the
    xsi:type name, e.g. `"contentFloatListType"`). It is an error to have
    neither: non-empty values= to infer from, nor an explicit xsi_type=.

    Pass a shared `registry=` (an `XsiTypeRegistry`) across a document's
    protocol and data sections to guarantee the placeholder declared in the
    protocol and the actual measurement recorded later in <data> for the
    same key end up with the same xsi:type -- see XsiTypeRegistry.

    Extra kwargs (axis=, size=, units=, format_string=, id=, ref=, ...) are
    forwarded to the chosen class's constructor.
    """
    cls = _resolve_xsi_type(xsi_type)
    if cls is not None and not is_content_class(cls):
        raise TypeError(f"infer_content: xsi_type={cls!r} is not a maiml_domain content class")

    if cls is None and registry is not None:
        cls = registry.get(key)
        if cls is not None and not is_content_class(cls):
            raise TypeError(
                f"infer_content: registry has key={key!r} registered as "
                f"{cls.__name__}, which is not a content class -- the same key is "
                "being used for both a property and a content container"
            )

    if cls is None:
        if not values:
            raise ValueError(
                f"infer_content: xsi:type is required by the schema but could not be "
                f"determined for key={key!r} -- no non-empty values= to infer it from. Pass "
                "xsi_type=<maiml_domain class or xsi:type name> explicitly; this is the "
                "common case for a protocol placeholder content that has no values yet."
            )
        cls = _infer_homogeneous_list_class(
            values, _CONTENT_LIST_CLASS_BY_TYPE, caller="infer_content", kind_noun="content"
        )

    if registry is not None:
        registry.register(key, cls)

    return _instantiate(cls, key, None, values, kwargs)


# ---------------------------------------------------------------------------
# EVT-02: lifecycle:transition="complete" event
# ---------------------------------------------------------------------------

def new_complete_event(
    id: str,
    ref: str,
    *,
    id_factory: Optional[IdFactory] = None,
    extra_properties: Optional[list] = None,
) -> "m.EventType":
    """
    Build an EventType carrying the lifecycle:transition="complete"
    property that maiml-schema-validator's EVT-02 rule requires whenever
    <data> records a material/condition/result. `ref` must point at the
    id of the instruction (or program) this event completes.

    Remember to declare xmlns:lifecycle="<LIFECYCLE_NS>" on the root
    element (see pymaiml.serialization.dumps' extra_namespaces=) -- NS-01
    rejects the "lifecycle:" prefix if it resolves to any other URI.
    """
    complete_prop = m.StringType(key="lifecycle:transition", value="complete")
    properties = [complete_prop, *(extra_properties or [])]
    content_uuid = id_factory.new_uuid() if id_factory is not None else m.Uuid(str(_uuidlib.uuid4()))
    return m.EventType(
        id=id,
        ref=ref,
        content=m.GlobalObjectContent(uuid=content_uuid, properties=properties),
    )


# ---------------------------------------------------------------------------
# Template -> Instance: turning a materialTemplate/conditionTemplate/
# resultTemplate into the material/condition/result it describes
# ---------------------------------------------------------------------------

# Which maiml_domain instance class a given template class becomes, and
# the IdFactory prefix create_instances() reserves its id under (matching
# the "material"/"condition"/"result" prefixes already used for these
# instance kinds elsewhere in this project, e.g. tests/conftest.py).
_TEMPLATE_TO_INSTANCE: Dict[type, type] = {
    m.MaterialTemplateType: m.MaterialType,
    m.ConditionTemplateType: m.ConditionType,
    m.ResultTemplateType: m.ResultType,
}
_INSTANCE_ID_PREFIX: Dict[type, str] = {
    m.MaterialTemplateType: "material",
    m.ConditionTemplateType: "condition",
    m.ResultTemplateType: "result",
}


@dataclasses.dataclass(frozen=True)
class InsertionValue:
    """
    The new uri/hash (and optionally uuid/format) create_instance() should
    give one of a template's <insertion> elements when building the
    matching instance's own copy of it.

    A template's insertion is never copied to an instance as-is -- an
    <insertion> names an *external file*, and the instance's copy of an
    inserted file is a distinct file from the template's (the template's
    insertion is typically a placeholder or an example; the instance's is
    the file this particular measurement/analysis actually produced) --
    so its uri and hash must always be supplied fresh by the caller, who
    is the only one who knows what that new file's uri/hash actually are.
    uuid, if omitted, is generated fresh (via the same IdFactory
    create_instance()/create_instances() were given); format, if omitted,
    is copied from the template's insertion (the file *format* -- e.g.
    "text/csv" -- is the one part of an insertion that often does stay
    the same between a template's placeholder and an instance's real
    file, unlike uri/hash which by definition cannot).
    """

    uri: str
    hash: "m.HashType"
    uuid: Optional["m.Uuid"] = None
    format: Optional[str] = None


def _build_instance_insertions(
    template_insertions: List["m.InsertionType"],
    *,
    id_factory: IdFactory,
    insertion_values: Optional[Mapping[str, InsertionValue]],
) -> List["m.InsertionType"]:
    """Rebuild `template_insertions` as new InsertionType objects for an
    instance, using insertion_values (keyed by the template insertion's own
    uri -- InsertionType has no id of its own to key by) to supply each
    one's new uri/hash. Raises ValueError naming the uri if a template
    insertion has no matching entry -- see InsertionValue's docstring for
    why an instance's insertion can never just reuse the template's."""
    result: List["m.InsertionType"] = []
    for old in template_insertions:
        value = (insertion_values or {}).get(old.uri)
        if value is None:
            raise ValueError(
                f"create_instance: template has an <insertion uri={old.uri!r}> but "
                f"insertion_values has no entry for {old.uri!r} -- pass "
                f"insertion_values={{{old.uri!r}: InsertionValue(uri=..., hash=...), "
                "...} with a new uri/hash for the instance's own copy of this "
                "insertion (a template's insertion is never reused as-is -- see "
                "InsertionValue's docstring)."
            )
        result.append(
            m.InsertionType(
                uri=value.uri,
                hash=value.hash,
                uuid=value.uuid if value.uuid is not None else id_factory.new_uuid(),
                format=value.format if value.format is not None else old.format,
            )
        )
    return result


def _build_instance_content(
    template_content: Optional["m.GlobalObjectContent"],
    *,
    id_factory: IdFactory,
    insertion_values: Optional[Mapping[str, InsertionValue]],
) -> "m.GlobalObjectContent":
    """The instance's own GlobalObjectContent: a fresh uuid (never the
    template's own identity uuid -- see create_instance()'s docstring),
    name/description/annotation copied as-is (immutable strs), and either
    - encryption deep-copied, when the template's content used it (mutually
      exclusive with insertions/properties/contents on GlobalObjectContent,
      so there is nothing else to copy in that case), or
    - insertions rebuilt via _build_instance_insertions(), and
      properties/contents deep-copied (so editing the instance's copy can
      never mutate the template's own property/content objects).
    template_content=None (a template with no generic data container at
    all) still gets a fresh, otherwise-empty content -- an instance is
    itself a global object and needs its own identity uuid regardless of
    whether the template it comes from happened to declare one.
    """
    if template_content is None:
        return m.GlobalObjectContent(uuid=id_factory.new_uuid())

    if template_content.encryption is not None:
        return m.GlobalObjectContent(
            uuid=id_factory.new_uuid(),
            name=template_content.name,
            description=template_content.description,
            annotation=template_content.annotation,
            encryption=copy.deepcopy(template_content.encryption),
        )

    return m.GlobalObjectContent(
        uuid=id_factory.new_uuid(),
        name=template_content.name,
        description=template_content.description,
        annotation=template_content.annotation,
        insertions=_build_instance_insertions(
            template_content.insertions, id_factory=id_factory, insertion_values=insertion_values
        ),
        properties=copy.deepcopy(template_content.properties),
        contents=copy.deepcopy(template_content.contents),
    )


def _convert_template_refs(
    template_refs: List["m.TemplateRefType"],
    *,
    template_instance_map: Optional[Mapping[str, str]],
    id_factory: IdFactory,
) -> List["m.InstanceRefType"]:
    """Every <templateRef> on a template names another template of the
    same kind (see maiml-schema-validator's REF-01/02/03 rules); the
    matching <instanceRef> on the instance being built must name that
    other template's own instance instead -- never the other template's
    id itself, since a template id and its instance's id are never the
    same value. template_instance_map (built by create_instances(), or
    supplied directly to a standalone create_instance() call) is what
    resolves one to the other; a templateRef with no entry in it raises
    ValueError rather than silently leaving a dangling or template-id
    reference in the output."""
    result: List["m.InstanceRefType"] = []
    for tref in template_refs:
        try:
            target_instance_id = template_instance_map[tref.ref]
        except (KeyError, TypeError):
            raise ValueError(
                f"create_instance: template has a <templateRef ref={tref.ref!r}> but "
                f"template_instance_map has no entry for {tref.ref!r} -- every "
                "templateRef must resolve to the id of an instance, via "
                "template_instance_map (create_instances() builds this "
                "automatically for every template in the same batch) or "
                "existing_instance_map (for a template instantiated separately, "
                "e.g. in an earlier call). Instantiate the referenced template in "
                "the same create_instances() call, or supply its instance id via "
                "existing_instance_map, before instantiating this one."
            ) from None
        result.append(
            m.InstanceRefType(
                id=id_factory.new_id("ref"),
                ref=target_instance_id,
                name=tref.name,
                description=tref.description,
            )
        )
    return result


def create_instance(
    template: Template,
    *,
    id: str,
    id_factory: IdFactory,
    template_instance_map: Optional[Mapping[str, str]] = None,
    insertion_values: Optional[Mapping[str, InsertionValue]] = None,
) -> Instance:
    """
    Build the material/condition/result instance that `template`
    (a MaterialTemplateType/ConditionTemplateType/ResultTemplateType --
    see pymaiml.query.Template, typically obtained from
    pymaiml.query.get_templates()) describes, as the matching maiml_domain
    instance class (MaterialType/ConditionType/ResultType -- see
    pymaiml.query.Instance) determined automatically from `template`'s own
    type; callers never pick the instance class themselves.

    `id` is the new instance's own id -- this function does not generate
    it itself (see create_instances(), which reserves ids for a whole
    batch up front via an IdFactory before building any instance, so every
    templateRef in that batch can already resolve to a real instance id by
    the time it is needed). `id_factory` is still required here too: it is
    used to mint the instance's own fresh content uuid, every rebuilt
    <insertion>'s uuid (unless InsertionValue supplies one), and every
    <instanceRef> wrapper element's own id.

    What is copied from `template` to the new instance, and what is not:
      - template.id becomes instance.ref (this is *how* an instance says
        which template it is an instance of -- see maiml_domain.data).
      - template.content's name/description/annotation are copied as-is;
        its insertions/properties/contents (or encryption) are copied via
        a fresh GlobalObjectContent, never the same mutable list/object
        the template holds (see _build_instance_content()) -- editing the
        returned instance afterwards can never mutate `template`.
      - template.content's insertions are NOT copied as-is: each becomes a
        brand new InsertionType with a caller-supplied uri/hash (via
        insertion_values, keyed by the template insertion's own uri -- see
        InsertionValue's docstring for why the template's uri/hash can
        never just be reused). A template insertion with no matching
        insertion_values entry raises ValueError.
      - template.template_refs become instance.instance_refs, each
        translated via template_instance_map (see _convert_template_refs()
        and template_instance_map's own docstring below) rather than
        copied by id -- a templateRef with no entry in template_instance_map
        raises ValueError rather than silently pointing at a template's id
        (which is never a valid instance id) or being dropped.
      - The instance's own id (the `id` parameter) and its content's uuid
        are always newly assigned, never copied from `template` -- an
        instance is a distinct object from the template it instantiates,
        with its own identity, even though it shares the template's
        name/description/annotation/generic-data-container content.
      - template.place_refs is NOT copied: MaterialType/ConditionType/
        ResultType has no place_refs attribute at all (a template's
        connection to PNML topology has no instance-side equivalent).

    template_instance_map, if given, maps every OTHER template's id this
    template's own template_refs might point to, to that other template's
    already-decided instance id -- it does not need (and for a
    single-template call, will not have) an entry for `template.id`
    itself. Pass it whenever `template.template_refs` is non-empty;
    create_instances() builds and passes it automatically when
    instantiating a batch of related templates together.
    """
    instance_cls = _TEMPLATE_TO_INSTANCE.get(type(template))
    if instance_cls is None:
        raise TypeError(
            f"create_instance: {type(template).__name__} is not a template class -- "
            f"expected one of {[c.__name__ for c in _TEMPLATE_TO_INSTANCE]}"
        )

    content = _build_instance_content(
        template.content, id_factory=id_factory, insertion_values=insertion_values
    )
    instance_refs = _convert_template_refs(
        template.template_refs, template_instance_map=template_instance_map, id_factory=id_factory
    )
    return instance_cls(id=id, ref=template.id, content=content, instance_refs=instance_refs)


def create_instances(
    templates: Sequence[Template],
    *,
    id_factory: IdFactory,
    insertion_values: Optional[Mapping[str, Mapping[str, InsertionValue]]] = None,
    existing_instance_map: Optional[Mapping[str, str]] = None,
) -> List[Instance]:
    """
    Build one instance per template in `templates` (e.g. the result of
    pymaiml.query.get_templates(xml_text, instruction_id=...)), handling
    the two-phase sequencing create_instance() itself deliberately does
    not: every instance's id must be decided *before* any instance is
    built, because a template's templateRef can point at another template
    in the same batch whose own instance doesn't exist yet at the point
    this template is instantiated (see create_instance()'s
    template_instance_map parameter -- this is exactly why that map is
    not create_instance()'s own responsibility to build).

    Processing order:
      1. Reserve a fresh instance id for every template in `templates`
         (via id_factory, under the "material"/"condition"/"result"
         prefix matching each template's own kind) -- this is `own_ids`,
         {template.id: new_instance_id}. Raises ValueError if the same
         template.id appears more than once in `templates` (each must be
         instantiated at most once per call).
      2. Build template_instance_map = {**(existing_instance_map or {}),
         **own_ids} -- own_ids' entries win on a key collision, since a
         template being instantiated in this very call always takes
         precedence over a stale existing_instance_map entry for the same
         template id.
      3. Call create_instance() once per template, passing its reserved id
         from own_ids, the shared template_instance_map from step 2, and
         (if given) that template's own entry from insertion_values.

    insertion_values, if given, is keyed by template.id first and then by
    each insertion's own uri (see InsertionValue and
    create_instance()'s insertion_values -- this is create_instance()'s
    same, single-template-scoped parameter, just nested one level to
    cover a whole batch of templates that may each have their own
    insertions to re-key).

    existing_instance_map, if given, supplies instance ids for templates
    OUTSIDE this batch that some template here might still templateRef --
    e.g. a template instantiated in an earlier, separate call. Without an
    entry (here or in the freshly built own_ids) for every templateRef
    target, create_instance() raises ValueError (see its own
    template_instance_map docstring) rather than silently leaving a
    dangling or template-id reference in the output.

    Returns instances in the same order as `templates`.
    """
    templates = list(templates)

    seen_template_ids = set()
    own_ids: Dict[str, str] = {}
    for template in templates:
        if template.id in seen_template_ids:
            raise ValueError(
                f"create_instances: template id {template.id!r} appears more than "
                "once in `templates` -- each template can be instantiated at most "
                "once per call."
            )
        seen_template_ids.add(template.id)

        prefix = _INSTANCE_ID_PREFIX.get(type(template))
        if prefix is None:
            raise TypeError(
                f"create_instances: {type(template).__name__} is not a template "
                f"class -- expected one of {[c.__name__ for c in _INSTANCE_ID_PREFIX]}"
            )
        own_ids[template.id] = id_factory.new_id(prefix)

    template_instance_map: Dict[str, str] = {**(existing_instance_map or {}), **own_ids}

    return [
        create_instance(
            template,
            id=own_ids[template.id],
            id_factory=id_factory,
            template_instance_map=template_instance_map,
            insertion_values=(insertion_values or {}).get(template.id),
        )
        for template in templates
    ]
