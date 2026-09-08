"""
XSD/Domain-model drift detection.

MaiML-Schema-1_0 is the source of truth; maiml_domain and pymaiml's
_xsi_registry are both hand-written to mirror it. Nothing enforces that
mirroring automatically -- if the bundled schema (pymaiml/schema/) gains
(or loses) a complexType, or a property/content xsi:type, and MaiML-Domain
/ pymaiml aren't updated to match, nothing currently notices until some
much later, harder-to-diagnose failure (an opaque XSD validation error, or
a value that silently vanishes on serialization). These tests exist to
catch that drift right here, the moment it happens, rather than downstream.
"""
from __future__ import annotations

import inspect

import maiml_domain as m
from lxml import etree

from pymaiml._xsi_registry import XSI_TYPE_TO_CLASS
from pymaiml.validation import _BUNDLED_SCHEMA_DIR

XS = "{http://www.w3.org/2001/XMLSchema}"

# maiml_domain classes that legitimately have no XSD complexType of the
# same name -- either because they correspond to an xs:simpleType instead
# (Uuid and the *FormatString/IsoLanguageName classes), an xs:group rather
# than a complexType (GlobalObjectContent -> globalObjectContentGroup,
# EncryptionType -> encryptionGroup's encrypted-content branch), or because
# they are this codebase's own implementation detail with no XSD
# counterpart at all (_StrictAttributesMixin). Kept explicit (rather than
# just skipping the reverse check below) so that a genuine drift -- a
# renamed or orphaned class -- can't silently hide behind it.
_DOMAIN_CLASSES_WITH_NO_COMPLEX_TYPE = {
    "Uuid", "IsoLanguageName", "DecimalFormatString", "FloatFormatString",
    "IntegerFormatString", "DateTimeFormatString",
    "GlobalObjectContent", "EncryptionType",
    "_StrictAttributesMixin",
}


def _all_complex_type_names() -> list:
    """Every <xs:complexType name="..."> across the whole bundled schema."""
    paths = sorted(_BUNDLED_SCHEMA_DIR.glob("maiml-*.xsd")) + [_BUNDLED_SCHEMA_DIR / "maiml.xsd"]
    names = []
    for path in paths:
        for ct in etree.parse(str(path)).iter(f"{XS}complexType"):
            name = ct.get("name")
            if name:
                names.append(name)
    return names


def _property_and_content_xsi_type_names():
    """
    The xsi:type names for every concrete (non-abstract) property/content
    type in maiml-property.xsd: every complexType whose base is literally
    'propertyBaseType' or 'contentBaseType' (the two abstract roots that
    every real property/content leaf type extends directly in this
    schema) -- not the roots themselves, and not the shared
    uncertaintyBaseType both of them extend.
    """
    tree = etree.parse(str(_BUNDLED_SCHEMA_DIR / "maiml-property.xsd"))
    property_names, content_names = [], []
    for ct in tree.iter(f"{XS}complexType"):
        name = ct.get("name")
        if not name:
            continue
        ext = ct.find(f".//{XS}extension")
        base = ext.get("base") if ext is not None else None
        if base == "propertyBaseType":
            property_names.append(name)
        elif base == "contentBaseType":
            content_names.append(name)
    return property_names, content_names


def _domain_class_names() -> set:
    return {name for name in dir(m) if inspect.isclass(getattr(m, name))}


# ---------------------------------------------------------------------------
# XSD complexType <-> maiml_domain class
# ---------------------------------------------------------------------------

def test_every_xsd_complex_type_has_a_matching_domain_class():
    """
    Every <xs:complexType name="fooType"> must have a maiml_domain.FooType
    class (first-letter-uppercased -- the naming convention this whole
    codebase relies on; see pymaiml._xsi_registry's docstring for the
    property/content half of it).

    Catches: the bundled XSD gained a new complexType (a schema update)
    and MaiML-Domain was never given the matching class.
    """
    domain_classes = _domain_class_names()
    missing = [
        (xsd_name, xsd_name[0].upper() + xsd_name[1:])
        for xsd_name in _all_complex_type_names()
        if (xsd_name[0].upper() + xsd_name[1:]) not in domain_classes
    ]
    assert not missing, (
        "XSD complexType(s) with no matching maiml_domain class (naming "
        f"convention fooType -> FooType): {missing}. Add the class to "
        "MaiML-Domain, or -- if this type is genuinely never meant to be "
        "instantiated on its own -- add it to an exclusion list here."
    )


def test_no_domain_class_is_missing_its_xsd_complex_type_without_being_documented():
    """
    Reverse direction: a maiml_domain class whose name matches no XSD
    complexType, and isn't in the documented exclusion list above, is
    either a typo/rename that drifted from the XSD, or a legitimate new
    exception this test's exclusion list needs to learn about.
    """
    domain_classes = _domain_class_names()
    expected = {name[0].upper() + name[1:] for name in _all_complex_type_names()}
    unexpected = domain_classes - expected - _DOMAIN_CLASSES_WITH_NO_COMPLEX_TYPE
    assert not unexpected, (
        "maiml_domain class(es) with no matching XSD complexType, and not "
        f"in _DOMAIN_CLASSES_WITH_NO_COMPLEX_TYPE: {sorted(unexpected)}"
    )


# ---------------------------------------------------------------------------
# property/content xsi:type <-> pymaiml._xsi_registry
# ---------------------------------------------------------------------------

def test_every_xsd_property_xsi_type_is_registered():
    """
    Catches: a new property xsi:type was added to maiml-property.xsd, but
    the matching maiml_domain.property class was never added -- or was
    added without being listed in property.py's own __all__, which is
    what pymaiml._xsi_registry actually iterates at import time (see its
    docstring). That second case is invisible to the two tests above,
    since a class missing from __all__ is also missing from dir(m).
    """
    property_names, _ = _property_and_content_xsi_type_names()
    missing = [n for n in property_names if n not in XSI_TYPE_TO_CLASS]
    assert not missing, f"property xsi:type(s) missing from pymaiml._xsi_registry: {missing}"


def test_every_xsd_content_xsi_type_is_registered():
    _, content_names = _property_and_content_xsi_type_names()
    missing = [n for n in content_names if n not in XSI_TYPE_TO_CLASS]
    assert not missing, f"content xsi:type(s) missing from pymaiml._xsi_registry: {missing}"


def test_registry_has_no_xsi_type_absent_from_the_xsd():
    """
    Reverse direction: an xsi:type in pymaiml._xsi_registry that no
    longer corresponds to any complexType in the XSD -- a rename/removal
    on the MaiML-Domain side that drifted from the schema.
    """
    property_names, content_names = _property_and_content_xsi_type_names()
    expected = set(property_names) | set(content_names)
    extra = set(XSI_TYPE_TO_CLASS) - expected
    assert not extra, f"pymaiml._xsi_registry has xsi:type(s) absent from the XSD: {sorted(extra)}"
