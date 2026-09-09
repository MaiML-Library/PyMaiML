"""
pymaiml.query
==============

"List the X used in this file" utilities: every UUID, every property/
content/chain/parent key=, and every external <insertion> file URI.

get_uuids(), get_keys(), and get_insertion_uris() are built on top of
maiml_domain: each calls pymaiml.serialization.loads(xml_text) first and
reads its answer off the resulting maiml_domain object tree
(loaded.root), not off the raw XML. This module used to walk the raw XML
directly instead (generic lxml tag-name/attribute scans), specifically so
it could work on input that was not yet schema-valid, without paying for
loads()'s full maiml_domain construction. That independence has been
given up in favor of a stronger rule: PyMaiML's Python-facing view of
"what's in this MaiML file" should always be read off maiml_domain, the
one canonical domain model every Python tool in this project shares, not
reconstructed a second time by an independent XML-scanning implementation
that knows the same tag/attribute names by coincidence and can silently
drift out of sync with what serialization.py actually reads and writes.

Consequences worth knowing before reaching for these three functions:

  - xml_text now has to be schema-valid MaiML -- a <maiml
    xsi:type="maimlRootType"|"protocolFileRootType"> document with every
    element maiml_domain's constructors require present. loads() raises
    (typically ValueError, or an lxml parse error for input that is not
    even well-formed XML) otherwise, exactly as it does for any other
    caller -- these functions do not catch or soften that. Using them as
    a pre-validation triage step on a file that is not schema-valid yet,
    which this module's raw-XML implementation used to support, is no
    longer possible: validate() or load() the file first.
  - XXE/entity-expansion/network hardening for these three functions is
    now whatever pymaiml.serialization.loads() does -- see
    pymaiml._xml_security.make_untrusted_input_parser() and
    tests/test_xml_security.py's loads() coverage. This module does not
    parse xml_text itself for them at all, so there is no separate
    hardening path here to regress.
  - An <insertion> with no uri is no longer representable as an input at
    all: maiml_domain.InsertionType.__post_init__ requires a non-empty
    uri, so get_insertion_uris() can no longer be handed that malformed
    shape in the first place (previously a raw-XML concern, this class of
    problem simply cannot reach this function anymore).

get_namespaces() is the one exception and still parses xml_text directly
with pymaiml._xml_security.make_untrusted_input_parser(): namespace
declarations are an XML-level concept that maiml_domain's object tree
does not represent at all (see pymaiml.serialization's own "Known
limitations" -- dumps() re-derives them from extra_namespaces=, no
maiml_domain class stores them anywhere), so there is no domain-model
form of this information for get_namespaces() to read instead.

Every maiml_domain object is a plain Python object (or dataclass) whose
own __init__ assigns its declared attributes in the same order its
docstring/the XSD sequence it implements lists them in. get_uuids(),
get_keys(), and get_insertion_uris() all walk the object tree with the
same generic, no-per-class-knowledge helper, _iter_domain_objects():
depth-first through every non-leaf attribute value (vars(obj), in
insertion order) and every list/tuple element, in whatever order that
happens to be for the class in question -- which is why the ordering
these three functions report is described as "document order" only
approximately, not guaranteed byte-for-byte identical to the original
XML's element order in every edge case. A class maiml_domain adds in the
future is automatically covered without this module needing to know
about it specifically.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, Iterator, List, Optional, Set, Union

import maiml_domain as m
from lxml import etree

from . import serialization
from ._xml_security import make_untrusted_input_parser

__all__ = ["get_uuids", "get_keys", "get_namespaces", "get_insertion_uris"]


# Values that are never themselves a maiml_domain object and are never
# recursed into -- note maiml_domain.Uuid (and IsoLanguageName etc.) are
# str subclasses, so they are already covered by the str check.
_LEAF_TYPES = (str, bytes, int, float, bool, Decimal, datetime)


def _iter_domain_objects(obj: object, _seen: Optional[Set[int]] = None) -> Iterator[object]:
    """Yield obj and every maiml_domain object reachable from it through
    plain attributes and list/tuple attributes, depth-first.

    Deliberately generic: no isinstance-per-class branching over
    maiml_domain's ~30 structural classes and ~50 property/content leaf
    classes. A leaf value (see _LEAF_TYPES, plus None) is not recursed
    into. An id()-keyed `_seen` guard prevents infinite recursion if a
    caller ever hand-builds a cyclic object graph -- maiml_domain itself
    never produces one; ChainType/ParentType nesting is a normal finite
    tree -- and does NOT deduplicate otherwise: the same value reachable
    through two different, independently-constructed objects is yielded
    twice, on purpose (see get_uuids()'s own docstring for why that
    matters for uuids specifically).
    """
    if obj is None or isinstance(obj, _LEAF_TYPES):
        return
    if _seen is None:
        _seen = set()
    if isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _iter_domain_objects(item, _seen)
        return
    oid = id(obj)
    if oid in _seen:
        return
    _seen.add(oid)
    yield obj
    for name, value in vars(obj).items():
        if name.startswith("_"):
            continue
        yield from _iter_domain_objects(value, _seen)


def _local_name(tag) -> str:
    """Strip a lxml/Clark-notation {uri}localname tag down to localname.
    Used only by get_namespaces(), the one function here that still
    parses xml_text directly -- see the module docstring for why."""
    if not isinstance(tag, str):
        return ""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _parse_root(xml_text: Union[str, bytes]):
    """Parse xml_text with the same untrusted-input hardening
    pymaiml.serialization.loads() uses, and return the root element. Used
    only by get_namespaces() -- see the module docstring."""
    data = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
    return etree.fromstring(data, parser=make_untrusted_input_parser())


def get_uuids(xml_text: Union[str, bytes]) -> List[str]:
    """
    Every uuid in xml_text's maiml_domain object tree (loads(xml_text).root),
    in document order, INCLUDING duplicates -- unlike get_keys()/
    get_insertion_uris(), this does not deduplicate. A uuid is meant to
    uniquely identify one object, so a uuid that appears more than once is
    a fact about the file worth being able to observe (e.g. two distinct
    objects accidentally sharing an identity), and deduplicating here
    would hide it. If you want the distinct set instead, wrap the result
    yourself, e.g. set(get_uuids(xml_text)) or
    list(dict.fromkeys(get_uuids(xml_text))).

    Covers every maiml_domain attribute that carries a uuid: a
    GlobalObjectContent's own identity uuid (document/creator/vendor/.../
    material/.../eventLog...), an InsertionType's uuid (identifying the
    inserted external file, a distinct concept from the uuid of the
    object doing the inserting), and a ChainType/ParentType's uuid.
    Returned as plain str (str(obj.uuid) -- maiml_domain.Uuid is itself a
    str subclass, this just normalizes the type callers see).

    xml_text must be schema-valid MaiML: this calls
    pymaiml.serialization.loads(xml_text) and raises whatever loads()
    raises for anything else (see the module docstring).
    """
    loaded = serialization.loads(xml_text)
    return [
        str(obj.uuid)
        for obj in _iter_domain_objects(loaded.root)
        if getattr(obj, "uuid", None) is not None
    ]


def get_keys(xml_text: Union[str, bytes]) -> List[str]:
    """
    Every key= value in xml_text's maiml_domain object tree
    (loads(xml_text).root), in document order, with duplicates removed
    (first occurrence kept).

    Covers every maiml_domain attribute that carries a key: every
    property/content instance (UncertaintyBaseType.key -- StringType,
    FloatType, and every other property*/content* leaf class this package
    defines, including <uncertainty> entries, which reuse those same
    classes), plus ChainType/ParentType's optional key. MaiML-Schema-1_0
    does not require key= to be unique, even within the same parent
    element (see pymaiml/README.md's note on this under
    pymaiml.builders.XsiTypeRegistry), so this is the set of distinct
    keys used, not a one-entry-per-occurrence list.

    xml_text must be schema-valid MaiML: this calls
    pymaiml.serialization.loads(xml_text) and raises whatever loads()
    raises for anything else (see the module docstring).
    """
    loaded = serialization.loads(xml_text)
    values = [
        obj.key
        for obj in _iter_domain_objects(loaded.root)
        if getattr(obj, "key", None) is not None
    ]
    return list(dict.fromkeys(values))


def get_namespaces(xml_text: Union[str, bytes]) -> Dict[str, str]:
    """
    Every custom xmlns:<prefix>="uri" declaration anywhere in xml_text, as
    {prefix: uri} (insertion order == first-appearance order, since a
    plain dict already preserves that).

    Unlike get_uuids()/get_keys()/get_insertion_uris(), this does NOT go
    through pymaiml.serialization.loads() or maiml_domain: namespace
    declarations are an XML-level concept that no maiml_domain class
    stores (see the module docstring), so there is nothing to read off
    the object tree here. This parses xml_text directly instead, with the
    same pymaiml._xml_security.make_untrusted_input_parser() hardening
    loads() uses. Because it does not go through loads(), xml_text does
    NOT need to be schema-valid for get_namespaces() specifically (though
    calling it on a file you also intend to get_uuids()/get_keys()/
    get_insertion_uris() from, or load(), still requires that elsewhere).

    Excludes the unprefixed default namespace (MaiML's own
    http://www.maiml.org/schemas, always implicit and not itself
    interesting to enumerate) and the xsi: binding, matching
    pymaiml.serialization.LoadedMaiml.namespaces's existing convention --
    the result of this function is suitable to pass straight through as
    dumps(..., extra_namespaces=get_namespaces(xml_text)).

    Unlike LoadedMaiml.namespaces (which only looks at the root <maiml>
    element -- sufficient for pymaiml's own dumps() output, since
    xml.etree.ElementTree's serializer hoists every namespace URI used
    anywhere in the tree up to a root-level declaration), this scans every
    element in the tree. An externally-authored, already-signed/encrypted
    MaiML file can legitimately declare a namespace (e.g. xmlns:ds on a
    <Signature> that was never round-tripped through pymaiml's own
    dumps()) somewhere other than the root, and this function is meant to
    work on exactly that kind of file, not only pymaiml's own output.

    Raises ValueError if the same prefix is bound to two different URIs
    at different points in the document -- silently keeping one would
    misrepresent which namespace some tag/key= in the file actually uses.
    """
    root = _parse_root(xml_text)
    result: Dict[str, str] = {}
    for el in root.iter():
        for prefix, uri in (el.nsmap or {}).items():
            if prefix is None or prefix == "xsi":
                continue
            if prefix in result and result[prefix] != uri:
                raise ValueError(
                    f"get_namespaces(): conflicting declarations for xmlns:{prefix} "
                    f"({result[prefix]!r} vs {uri!r}) at different points in the "
                    "document -- this function cannot report a single URI for "
                    "this prefix without misrepresenting the file."
                )
            result[prefix] = uri
    return result


def get_insertion_uris(xml_text: Union[str, bytes]) -> List[str]:
    """
    Every external file URI (InsertionType.uri) in xml_text's maiml_domain
    object tree (loads(xml_text).root) -- see maiml_domain.core.
    InsertionType; GlobalObjectContent.insertions is where these live --
    in document order, with duplicates removed (first occurrence kept).

    xml_text must be schema-valid MaiML: this calls
    pymaiml.serialization.loads(xml_text) and raises whatever loads()
    raises for anything else (see the module docstring). One direct
    consequence: an <insertion> with no uri, which the old raw-XML
    implementation had to explicitly skip, can no longer occur here at
    all -- InsertionType.__post_init__ itself rejects a missing/empty uri,
    so loads() would already have raised before this function ever runs.
    """
    loaded = serialization.loads(xml_text)
    values = [
        obj.uri
        for obj in _iter_domain_objects(loaded.root)
        if isinstance(obj, m.InsertionType)
    ]
    return list(dict.fromkeys(values))
