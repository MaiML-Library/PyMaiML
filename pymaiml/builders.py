"""
pymaiml.builders
==================

Ergonomic helpers on top of the raw maiml_domain classes, aimed at the three
sources of boilerplate/mistakes identified while hand-building MaiML files
directly against maiml_domain during MaiML-Domain's own development:

  1. Picking the right one of ~70 property/content classes for a Python
     value (IdFactory-adjacent: `infer_property` / `infer_content`).
  2. Keeping id/uuid values unique across a large object tree
     (`IdFactory`).
  3. Remembering that recording a material/condition/result in <data>
     requires a matching lifecycle:transition="complete" <event> in
     <eventLog>, plus the exact XES namespace URI for the "lifecycle:"
     prefix -- this is EVT-02 in the maiml-schema-validator skill's rule
     set, and was hand-written three separate times in MaiML-Domain's own
     test script before this module existed (`new_complete_event`).

This module does not attempt a full "session"/fluent builder over the
entire object graph -- that would need to model every XSD content model's
ordering and cardinality a second time on top of maiml_domain and
pymaiml.serialization, and untested code for a ~70-class surface is worse
than no code. What's here is scoped to what could be written and verified
against real validation output.
"""
from __future__ import annotations

import itertools
import uuid as _uuidlib
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Type

import maiml_domain as m

__all__ = [
    "IdFactory",
    "LIFECYCLE_NS",
    "infer_property",
    "infer_content",
    "new_complete_event",
]

# The exact XES lifecycle extension URI that maiml-schema-validator's NS-01
# rule requires the "lifecycle:" key prefix to be bound to. Declare this as
# xmlns:lifecycle on the root <maiml> element (see
# pymaiml.serialization.dumps' extra_namespaces parameter).
LIFECYCLE_NS = "http://www.xes-standard.org/lifecycle.xesext#"


# ---------------------------------------------------------------------------
# IdFactory
# ---------------------------------------------------------------------------

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
    """

    def __init__(self) -> None:
        self._counters: Dict[str, itertools.count] = {}
        self._issued: set = set()

    def new_id(self, prefix: str) -> str:
        counter = self._counters.setdefault(prefix, itertools.count(1))
        while True:
            candidate = f"{prefix}{next(counter)}"
            if candidate not in self._issued:
                self._issued.add(candidate)
                return candidate

    def new_uuid(self) -> "m.Uuid":
        return m.Uuid(str(_uuidlib.uuid4()))


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


def infer_property(key: str, value: Any = None, values: Optional[List[Any]] = None, **kwargs):
    """
    Build a maiml_domain property instance, choosing the concrete class
    from the Python type of `value` (scalar) or the elements of `values`
    (list -- must be non-empty and homogeneous).

    Extra kwargs (description=, units=, format_string=, encryption=, ...)
    are forwarded to the chosen class's constructor -- pass whatever that
    concrete class accepts; an unsupported kwarg (e.g. units= on a
    non-numeric type) raises TypeError from the underlying constructor,
    same as calling it directly.

    Exactly one of `value`/`values` must be given. For anything the
    inference table doesn't cover (xs:QName/IDREF/token/uri/language
    scalars, enumerations, list-of-mixed-types), construct the
    maiml_domain class directly -- this is a convenience for the common
    cases, not a replacement for the full class list.
    """
    if (value is None) == (values is None):
        raise ValueError("infer_property: pass exactly one of value= or values=")

    if values is not None:
        if not values:
            raise ValueError("infer_property: values must be non-empty to infer a type")
        cls = _match(type(values[0]), _LIST_CLASS_BY_TYPE)
        if cls is None:
            raise TypeError(
                f"infer_property: no known property list type for element type {type(values[0])!r}; "
                "construct the maiml_domain class directly."
            )
        return cls(key=key, values=values, **kwargs)

    cls = _match(type(value), _SCALAR_CLASS_BY_TYPE)
    if cls is None:
        raise TypeError(
            f"infer_property: no known scalar property type for {type(value)!r}; "
            "construct the maiml_domain class directly."
        )
    return cls(key=key, value=value, **kwargs)


def infer_content(key: str, values: List[Any], **kwargs):
    """
    Build a maiml_domain content instance (always a list type -- MaiML has
    no scalar content type) from the Python type of `values`' elements.

    Extra kwargs (axis=, size=, units=, format_string=, id=, ref=, ...) are
    forwarded to the chosen class's constructor.
    """
    if not values:
        raise ValueError("infer_content: values must be non-empty to infer a type")
    cls = _match(type(values[0]), _CONTENT_LIST_CLASS_BY_TYPE)
    if cls is None:
        raise TypeError(
            f"infer_content: no known content list type for element type {type(values[0])!r}; "
            "construct the maiml_domain class directly."
        )
    return cls(key=key, values=values, **kwargs)


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
