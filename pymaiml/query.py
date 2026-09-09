"""
pymaiml.query
=============

Read-only query utilities for MaiML documents.

get_uuids(), get_keys(), get_insertion_uris(), get_templates(), and
get_instances() all read their answer off the maiml_domain object tree
that pymaiml.serialization.loads(xml_text) builds -- so xml_text must be
schema-valid MaiML for all five (loads() raises otherwise -- typically
ValueError, or an lxml parse error for input that is not even
well-formed XML -- and these functions do not catch or soften that).
Their XXE/entity-expansion/network hardening is therefore whatever
loads() does; see pymaiml._xml_security.make_untrusted_input_parser()
and tests/test_xml_security.py's loads() coverage.

get_namespaces() is the one exception: namespace declarations are an
XML-level concept that maiml_domain's object tree does not represent at
all (see pymaiml.serialization's own "Known limitations" -- dumps()
re-derives them from extra_namespaces=, no maiml_domain class stores
them anywhere), so it parses xml_text directly instead, with the same
untrusted-input hardening. xml_text does NOT need to be schema-valid for
get_namespaces() specifically.

Two families of functions live here:

  - get_uuids(), get_keys(), get_namespaces(), get_insertion_uris()
    return flat lists of strings (a dict, for get_namespaces()) -- every
    X used in this file. get_uuids() keeps duplicates (a uuid is meant to
    identify one object, so a repeated one is itself a fact worth seeing
    -- see its own docstring); the other three deduplicate, first
    occurrence kept.
  - get_templates() and get_instances() return the actual maiml_domain
    objects themselves (see the Template/Instance type aliases below),
    filtered by keyword-only arguments: kind= picks material/condition/
    result, instruction_id= narrows by PNML topology (see each
    function's own docstring for the exact semantics -- they share the
    same instruction_id= chain via _templates_linked_to_instruction()).
    This is deliberately extensible: "get everything" is kind=None (the
    default); "get just ids" is [obj.id for obj in get_templates(xml)]
    on the caller's side, not a separate function; a new way to narrow
    the result is a new keyword argument on the existing function, not a
    new function name.

All five loads()-based functions walk the maiml_domain object tree with
the same generic, no-per-class-knowledge helper, _iter_domain_objects():
depth-first through every non-leaf attribute (vars(obj), in each class's
own __init__ assignment order) and every list/tuple element. A class
maiml_domain adds in the future is automatically covered without this
module needing to know about it specifically -- which is also why the
"document order" these functions report is only approximate, not
guaranteed byte-for-byte identical to the source XML's element order in
every edge case.

See CHANGELOG.md for the history of this module (it originally parsed
raw XML directly instead of going through maiml_domain).
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
    "Template",
    "Instance",
]

# get_templates()/get_instances() return the actual maiml_domain objects,
# not a separate DTO -- these aliases just make that precise in type
# hints (IDE completion, static checking) instead of the two functions
# being typed as List[object].
Template = Union[m.MaterialTemplateType, m.ConditionTemplateType, m.ResultTemplateType]
Instance = Union[m.MaterialType, m.ConditionType, m.ResultType]

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


def _find_instruction(all_objs: List[object], instruction_id: str, fn_name: str) -> "m.InstructionType":
    """Look up the InstructionType with id == instruction_id among all_objs,
    or raise ValueError naming fn_name -- shared by get_templates()'s and
    get_instances()'s instruction_id= handling so both fail the same way on
    a typo'd id."""
    for obj in all_objs:
        if isinstance(obj, m.InstructionType) and obj.id == instruction_id:
            return obj
    raise ValueError(f"{fn_name}(): no <instruction id={instruction_id!r}> found in xml_text")


def _templates_linked_to_instruction(instruction: "m.InstructionType", all_objs: List[object]) -> List[Template]:
    """Every template (MaterialTemplateType/ConditionTemplateType/
    ResultTemplateType) reachable from `instruction` via PNML topology:
    instruction.transition_refs -> the TransitionType(s) they name -> every
    <arc> touching one of those transitions -> the PlaceType on the arc's
    other end -> every template whose own place_refs names that place.

    Every hop is checked against the actual maiml_domain objects present
    in all_objs, not against id strings alone: transition_refs/place_refs
    are IDREFs that could in principle name an id nothing in the document
    actually has (maiml_domain does not itself enforce IDREF resolvability
    the way MaiML-Schema-1_0's XSD does -- see the maiml-schema-validator
    skill's REF-01/02/03 rules), and pymaiml.query's own rule is to answer
    "what does the Domain say" rather than resolve a coincidental string
    match. Concretely: instruction.transition_refs' ids are intersected
    against real TransitionType.id values before matching them against
    <arc> endpoints, and the ids arcs point at are intersected against
    real PlaceType.id values before matching them against a template's
    place_refs.

    An arc's source/target can be either a place or a transition id
    (ArcType does not distinguish -- see maiml_domain.pnml), so this checks
    both ends of every arc against the instruction's (verified) transition
    ids and takes whichever end matched as the candidate place id, then
    keeps only candidates that are actually a PlaceType's id. Used only by
    get_templates()/get_instances()'s instruction_id= filter, shared so
    both walk the exact same path.
    """
    requested_transition_ids = {tref.ref for tref in instruction.transition_refs}
    transition_ids = {
        obj.id
        for obj in all_objs
        if isinstance(obj, m.TransitionType) and obj.id in requested_transition_ids
    }

    candidate_place_ids: Set[str] = set()
    for obj in all_objs:
        if not isinstance(obj, m.ArcType):
            continue
        if obj.source in transition_ids:
            candidate_place_ids.add(obj.target)
        if obj.target in transition_ids:
            candidate_place_ids.add(obj.source)

    actual_place_ids = {obj.id for obj in all_objs if isinstance(obj, m.PlaceType)}
    place_ids = candidate_place_ids & actual_place_ids

    template_classes = tuple(_TEMPLATE_CLASSES.values())
    return [
        obj
        for obj in all_objs
        if isinstance(obj, template_classes)
        and any(place_ref.ref in place_ids for place_ref in obj.place_refs)
    ]


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


def get_templates(
    xml_text: Union[str, bytes],
    *,
    kind: Optional[str] = None,
    instruction_id: Optional[str] = None,
) -> List[Template]:
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
    loaded.root directly, if that distinction matters.

    instruction_id, if given, restricts the result to templates reachable
    from the <instruction id=instruction_id> via PNML topology: every
    <transitionRef> the instruction names -> the <transition>(s) those
    identify -> every <arc> touching one of those transitions -> the
    <place> on the arc's other end -> every template whose own
    <placeRef> names that place (see _templates_linked_to_instruction(),
    maiml_domain.pnml.ArcType/PlaceType, maiml_domain.ref_types.
    TransitionRefType/PlaceRefType; every hop is checked against real
    maiml_domain objects, not id strings alone). This is the only link
    from an instruction to a template the MaiML schema documents -- there
    is no direct instruction-to-template reference. instruction_id must
    name an <instruction> that actually exists somewhere in xml_text, or
    this raises ValueError (a typo'd id is a mistake worth failing loudly
    on); an instruction_id that does exist but has no template reachable
    from it (yet) is not an error and returns [] instead -- see
    get_instances()'s docstring for the same distinction spelled out in
    more detail, it applies here identically. This works on a
    protocolFileRootType (a protocol-only file -- see maiml_domain.root.
    ProtocolFileRootType) exactly as well as on a full maimlRootType,
    since the whole chain lives under <protocol>, not under
    <data>/<eventLog>.

    xml_text must be schema-valid MaiML: this calls
    pymaiml.serialization.loads(xml_text) and raises whatever loads()
    raises for anything else (see the module docstring).
    """
    loaded = serialization.loads(xml_text)
    all_objs = list(_iter_domain_objects(loaded.root))
    classes = _kind_classes(_TEMPLATE_CLASSES, kind)

    if instruction_id is None:
        return [obj for obj in all_objs if isinstance(obj, classes)]

    instruction = _find_instruction(all_objs, instruction_id, "get_templates")
    linked = _templates_linked_to_instruction(instruction, all_objs)
    return [obj for obj in linked if isinstance(obj, classes)]


def get_instances(
    xml_text: Union[str, bytes],
    *,
    kind: Optional[str] = None,
    instruction_id: Optional[str] = None,
) -> List[Instance]:
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
    from the <instruction id=instruction_id> in xml_text via either of two
    independent paths, unioned together (an instance reachable via both is
    listed once):

      1. instruction -> event: every <event ref=instruction_id> in
         xml_text's eventLog, through that event's own results_refs, to
         the <results> element(s) they refer to, and finally that
         <results> element's own materials/conditions/results (see
         maiml_domain.event_log.EventType and maiml_domain.data.
         ResultsType). This is "which instances were actually recorded
         as the outcome of running this instruction".
      2. instruction -> PNML topology: the same instruction ->
         transitionRef -> transition -> arc -> place -> template chain
         get_templates()'s instruction_id= uses (see its docstring and
         _templates_linked_to_instruction()), one hop further to every
         instance whose own .ref names one of those templates. This is
         "which instances are of a template this instruction's
         transitions are wired to", independent of whether any event has
         actually recorded one yet.

    instruction_id must name an <instruction> that actually exists
    somewhere in xml_text, or this raises ValueError -- a typo'd id is a
    mistake worth failing loudly on, not silently returning []. An
    instruction_id that does exist but has nothing reachable via either
    path (yet) is not an error: that returns [], deliberately distinct
    from the ValueError case above.

    A protocolFileRootType document (a protocol-only file -- see
    maiml_domain.root.ProtocolFileRootType, which has no data/eventLog at
    all) has no instances to find, so get_instances() on one always
    returns [] regardless of kind or instruction_id -- a legitimate
    instruction_id there still resolves without raising (the
    <instruction> itself is still present, and path 2's templates can
    still be found), it just never finds any actual instance object to
    return (there is no <data> at all to hold one); only an
    instruction_id that does not match any <instruction> in the file
    raises ValueError, exactly as for any other file.

    xml_text must be schema-valid MaiML: this calls
    pymaiml.serialization.loads(xml_text) and raises whatever loads()
    raises for anything else (see the module docstring).
    """
    loaded = serialization.loads(xml_text)
    all_objs = list(_iter_domain_objects(loaded.root))
    classes = _kind_classes(_INSTANCE_CLASSES, kind)

    if instruction_id is None:
        return [obj for obj in all_objs if isinstance(obj, classes)]

    instruction = _find_instruction(all_objs, instruction_id, "get_instances")

    # Path 1: instruction -> event -> results_refs -> results -> instances.
    results_ids = {
        results_ref.ref
        for obj in all_objs
        if isinstance(obj, m.EventType) and obj.ref == instruction_id
        for results_ref in obj.results_refs
    }
    ids_via_events = {
        inst.id
        for obj in all_objs
        if isinstance(obj, m.ResultsType) and obj.id in results_ids
        for inst in (obj.materials + obj.conditions + obj.results)
    }

    # Path 2: instruction -> transitionRef -> transition -> arc -> place ->
    # template -> instances whose .ref names that template (see
    # _templates_linked_to_instruction() and get_templates()'s docstring).
    template_ids = {t.id for t in _templates_linked_to_instruction(instruction, all_objs)}
    instance_classes = tuple(_INSTANCE_CLASSES.values())
    ids_via_topology = {
        obj.id
        for obj in all_objs
        if isinstance(obj, instance_classes) and obj.ref in template_ids
    }

    matched_ids = ids_via_events | ids_via_topology
    return [obj for obj in all_objs if isinstance(obj, classes) and obj.id in matched_ids]
