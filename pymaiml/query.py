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

get_templates() and get_instances() are a second family of functions in
this module, alongside the four "list the X used in this file" functions
above: instead of returning a flat list of strings, they return the
actual maiml_domain objects themselves (MaterialTemplateType/
ConditionTemplateType/ResultTemplateType for get_templates(),
MaterialType/ConditionType/ResultType for get_instances() -- see
maiml_domain.protocol and maiml_domain.data), filtered by keyword-only
arguments. This is deliberately extensible: "get everything" is
kind=None (the default), "get just ids" is not a separate function but
[obj.id for obj in get_templates(xml_text)] on the caller's side (the
object is already in hand, so there is nothing this module needs to do
specially for that case), and a new way to narrow the result -- like
get_instances()'s instruction_id= -- is a new keyword argument on the
existing function, not a new function name. Both call
pymaiml.serialization.loads(xml_text) and walk loaded.root with the same
_iter_domain_objects() helper the four functions above use, so the same
schema-validity requirement applies (see above).

  - get_templates(xml_text, *, kind=None): kind, when given, must be one
    of "material"/"condition"/"result" (anything else raises ValueError)
    and restricts the result to just that template kind; kind=None (the
    default) returns all three kinds together, in document order. A
    template is only ever nested under a program/method/protocol
    (maiml_domain.protocol.ProgramType/MethodType/ProtocolType's own
    material_templates/condition_templates/result_templates lists), and
    each of those three structural levels can define its own, separate
    templates -- get_templates() does not distinguish which level a given
    template came from, since maiml_domain does not tag a template object
    with that itself; inspect the returned object's own id/ref_types, or
    walk loaded.root directly, if that distinction matters to a caller.
    There is no instruction_id= filter here: a template's only documented
    connection to an instruction is indirect, through PNML place/
    transition/arc topology (place_refs/transition_refs), which is too
    loosely defined to implement as a keyword filter without a more
    specific request for it.
  - get_instances(xml_text, *, kind=None, instruction_id=None): kind
    works exactly like get_templates()'s, restricting the result to
    "material"/"condition"/"result" (ValueError for anything else),
    default None returns all three kinds. instruction_id, when given,
    restricts the result to instances reachable from that
    <instruction id="...">: via every <event ref="instruction_id"> in
    xml_text's eventLog, through that event's own results_refs, to the
    <results> element(s) those refer to, and finally that <results>
    element's own materials/conditions/results (in that field order --
    see maiml_domain.data.ResultsType). This is the only link from an
    instruction to instances the MaiML schema documents (see
    maiml_domain.event_log.EventType.ref/results_refs and
    maiml_domain.data.ResultsType) -- there is no direct
    instruction-to-instance reference. instruction_id must name an
    <instruction> that actually exists in xml_text or this raises
    ValueError (a typo'd id is a mistake worth failing loudly on); an
    instruction_id that does exist but has no events/instances linked to
    it (yet) is not an error and returns an empty list -- those are two
    different, deliberately distinguished situations. A
    ProtocolFileRootType document (a protocol-only file, no <data> or
    <eventLog> -- see maiml_domain.root) has no instances at all, so
    get_instances() on one always returns [] regardless of kind/
    instruction_id -- a legitimate instruction_id there still resolves
    without raising (protocol-only files still have <instruction>
    elements), it just always finds zero linked events, since there is no
    eventLog at all to hold one; only an unknown instruction_id raises
    ValueError there, same as for any other file.

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

__all__ = [
    "get_uuids",
    "get_keys",
    "get_namespaces",
    "get_insertion_uris",
    "get_templates",
    "get_instances",
]

# get_templates()/get_instances(): kind= maps a short, stable name to the
# maiml_domain class(es) it means. Adding a new kind (there is no fourth
# one documented today) is a one-line addition to these two dicts, not a
# new function.
_TEMPLATE_CLASSES = {
    "material": m.MaterialTemplateType,
    "condition": m.ConditionTemplateType,
    "result": m.ResultTemplateType,
}

_INSTANCE_CLASSES = {
    "material": m.MaterialType,
    "condition": m.ConditionType,
    "result": m.ResultType,
}


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


def _kind_classes(mapping: Dict[str, type], kind: Optional[str]) -> tuple:
    """Resolve get_templates()/get_instances()'s kind= keyword to the
    maiml_domain class(es) isinstance() should filter by: every class in
    `mapping` when kind is None, or just mapping[kind] when kind is given
    -- raising ValueError (not KeyError) for a kind that isn't one of
    mapping's keys, since that is a caller mistake worth naming clearly
    (and listing the valid options for) rather than leaking a bare
    KeyError."""
    if kind is None:
        return tuple(mapping.values())
    try:
        return (mapping[kind],)
    except KeyError:
        raise ValueError(
            f"unknown kind {kind!r} -- expected one of {sorted(mapping)}, or None for all of them"
        ) from None


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


def get_templates(xml_text: Union[str, bytes], *, kind: Optional[str] = None) -> List[object]:
    """
    Every material/condition/resultTemplate in xml_text's maiml_domain
    object tree (loads(xml_text).root), in document order, as the actual
    maiml_domain objects themselves (MaterialTemplateType/
    ConditionTemplateType/ResultTemplateType -- see maiml_domain.protocol),
    not ids or strings. Want just the ids? [t.id for t in
    get_templates(xml_text)] -- there is no separate "ids only" function,
    the object already has everything on it.

    kind, if given, must be one of "material"/"condition"/"result" and
    restricts the result to just that template kind (ValueError for
    anything else); the default None returns all three kinds together.

    A template can be defined at any of three structural levels --
    ProgramType, MethodType, or ProtocolType each have their own
    material_templates/condition_templates/result_templates -- and this
    walks all of them without distinguishing which level a given result
    came from (maiml_domain does not tag a template object with that
    itself); compare returned objects' .id/template_refs, or walk
    loaded.root directly, if that distinction matters. There is no
    instruction_id= filter: a template's only documented connection to an
    instruction is indirect, through PNML place/transition/arc topology,
    which is too loosely defined to implement as a keyword filter here
    (see the module docstring).

    xml_text must be schema-valid MaiML: this calls
    pymaiml.serialization.loads(xml_text) and raises whatever loads()
    raises for anything else (see the module docstring).
    """
    loaded = serialization.loads(xml_text)
    classes = _kind_classes(_TEMPLATE_CLASSES, kind)
    return [obj for obj in _iter_domain_objects(loaded.root) if isinstance(obj, classes)]


def get_instances(
    xml_text: Union[str, bytes],
    *,
    kind: Optional[str] = None,
    instruction_id: Optional[str] = None,
) -> List[object]:
    """
    Every material/condition/result *instance* in xml_text's maiml_domain
    object tree (loads(xml_text).root), in document order, as the actual
    maiml_domain objects themselves (MaterialType/ConditionType/
    ResultType -- see maiml_domain.data; each carries its own .ref back to
    the template it is an instance of). Want just the ids? [i.id for i in
    get_instances(xml_text)] -- same as get_templates(), no separate
    function for that.

    kind works exactly like get_templates()'s: one of "material"/
    "condition"/"result" to restrict to that kind (ValueError for
    anything else), or the default None for all three kinds together.

    instruction_id, if given, restricts the result to instances reachable
    from the <instruction id=instruction_id> in xml_text: via every
    <event ref=instruction_id> in its eventLog, through that event's own
    results_refs, to the <results> element(s) they refer to, and finally
    that <results> element's own materials/conditions/results (see
    maiml_domain.event_log.EventType and maiml_domain.data.ResultsType).
    This is the only link from an instruction to instances the MaiML
    schema documents -- there is no direct instruction-to-instance
    reference, only this instruction -> event -> results -> instance
    chain.

    instruction_id must name an <instruction> that actually exists
    somewhere in xml_text, or this raises ValueError -- a typo'd id is a
    mistake worth failing loudly on, not silently returning []. An
    instruction_id that does exist but has no events/instances linked to
    it (yet) is not an error: that returns [], deliberately distinct from
    the ValueError case above.

    A protocolFileRootType document (a protocol-only file -- see
    maiml_domain.root.ProtocolFileRootType, which has no data/eventLog at
    all) has no instances to find, so get_instances() on one always
    returns [] regardless of kind or instruction_id -- a legitimate
    instruction_id there still resolves without raising (the
    <instruction> itself is still present), it just always finds zero
    linked events (there is no eventLog at all to hold one) and so
    returns []; only an instruction_id that does not match any
    <instruction> in the file raises ValueError, exactly as for any other
    file.

    xml_text must be schema-valid MaiML: this calls
    pymaiml.serialization.loads(xml_text) and raises whatever loads()
    raises for anything else (see the module docstring).
    """
    loaded = serialization.loads(xml_text)
    all_objs = list(_iter_domain_objects(loaded.root))
    classes = _kind_classes(_INSTANCE_CLASSES, kind)

    if instruction_id is None:
        return [obj for obj in all_objs if isinstance(obj, classes)]

    instruction_ids = {obj.id for obj in all_objs if isinstance(obj, m.InstructionType)}
    if instruction_id not in instruction_ids:
        raise ValueError(
            f"get_instances(): no <instruction id={instruction_id!r}> found in xml_text"
        )

    results_ids = {
        results_ref.ref
        for obj in all_objs
        if isinstance(obj, m.EventType) and obj.ref == instruction_id
        for results_ref in obj.results_refs
    }

    instances: List[object] = []
    for obj in all_objs:
        if isinstance(obj, m.ResultsType) and obj.id in results_ids:
            instances.extend(obj.materials)
            instances.extend(obj.conditions)
            instances.extend(obj.results)

    return [obj for obj in instances if isinstance(obj, classes)]
