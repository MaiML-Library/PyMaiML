"""
Reflection-based xsi:type <-> maiml_domain class registry for property/content
types.

maiml_domain.property defines ~47 scalar/list property classes and ~22
content list classes. Every one of them follows a single naming rule shared
with the XSD: the Python class name equals the xsi:type name with the first
letter upper-cased (StringType <-> "stringType",
ContentDoubleListType <-> "contentDoubleListType", ...). Rather than hand
one 70-entry dict that will silently drift out of sync whenever
maiml_domain adds a type, this module builds both directions of the mapping
by introspecting maiml_domain.property.__all__ once at import time.
"""
from __future__ import annotations

from typing import Dict, Type

import maiml_domain.property as _property_mod
from maiml_domain.property import ContentBaseType, PropertyBaseType

# These three are abstract bases re-exported in __all__ for documentation
# purposes; they are never a concrete xsi:type on their own.
_ABSTRACT_BASE_NAMES = {"UncertaintyBaseType", "PropertyBaseType", "ContentBaseType"}


def _xsi_type_name(class_name: str) -> str:
    return class_name[0].lower() + class_name[1:]


def _build_registries():
    xsi_to_cls: Dict[str, type] = {}
    cls_to_xsi: Dict[type, str] = {}
    for name in _property_mod.__all__:
        if name in _ABSTRACT_BASE_NAMES:
            continue
        cls = getattr(_property_mod, name)
        if not isinstance(cls, type):
            continue
        xsi_name = _xsi_type_name(name)
        xsi_to_cls[xsi_name] = cls
        cls_to_xsi[cls] = xsi_name
    return xsi_to_cls, cls_to_xsi


XSI_TYPE_TO_CLASS: Dict[str, type] = {}
CLASS_TO_XSI_TYPE: Dict[type, str] = {}
XSI_TYPE_TO_CLASS.update(_build_registries()[0])
CLASS_TO_XSI_TYPE.update(_build_registries()[1])


def is_property_class(cls: type) -> bool:
    return isinstance(cls, type) and issubclass(cls, PropertyBaseType)


def is_content_class(cls: type) -> bool:
    return isinstance(cls, type) and issubclass(cls, ContentBaseType)


def xsi_type_for(obj_or_cls) -> str:
    """Return the xsi:type name for a property/content instance or class."""
    cls = obj_or_cls if isinstance(obj_or_cls, type) else type(obj_or_cls)
    try:
        return CLASS_TO_XSI_TYPE[cls]
    except KeyError as exc:
        raise ValueError(
            f"{cls!r} is not a known maiml_domain property/content class "
            "(is it registered in maiml_domain.property.__all__?)"
        ) from exc


def class_for_xsi_type(xsi_type: str) -> type:
    """Return the maiml_domain class for a given xsi:type name (e.g. 'floatType')."""
    try:
        return XSI_TYPE_TO_CLASS[xsi_type]
    except KeyError as exc:
        raise ValueError(f"Unknown property/content xsi:type: {xsi_type!r}") from exc
