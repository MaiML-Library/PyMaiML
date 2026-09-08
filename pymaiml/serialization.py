"""
pymaiml.serialization
======================

Converts maiml_domain object trees into real MaiML (JIS K 0200 /
MaiML-Schema-1_0) XML text/files.

maiml_domain deliberately has no XML (de)serialization of its own -- see
its README. This module is the "graduated" version of the throwaway
converter that MaiML-Domain/tests/build_sample_maiml.py used to validate
the domain model during development: the same recursive property/content
handling, but now generalized (via pymaiml._xsi_registry) to cover every
property/content type maiml_domain defines, and extended to cover every
structural element (document/protocol/data/eventLog/pnml), not just the
narrow slice one sample file happened to exercise.

Element ordering in every writer function below follows MaiML-Schema-1_0
directly (maiml.xsd / maiml-document.xsd / maiml-protocol.xsd /
maiml-data.xsd / maiml-eventLog.xsd / maiml-pnml.xsd / maiml-core.xsd /
maiml-property.xsd) -- see the docstring of each _write_* function for the
specific xs:sequence it mirrors.

loads()/load() are the inverse: parse MaiML XML (via lxml, so attribute
namespace maps are easy to inspect) back into a maiml_domain object tree,
returned wrapped in a LoadedMaiml along with the root's own custom
namespace declarations and every id encountered in the file -- both are
needed by the "load an existing protocol, keep it, add new data/eventLog"
workflow: the namespaces so dumps() can be given the same extra_namespaces=
again, and the ids so pymaiml.builders.IdFactory.from_existing_ids() can
avoid generating a new id that collides with one already in the file.

Known limitations (documented rather than silently guessed at):
  - <uncertainty> elements reuse the exact same concrete property/content
    classes as top-level <property>/<content> -- the schema's
    uncertaintyBaseType is the common abstract ancestor of both
    propertyBaseType and contentBaseType (see maiml-property.xsd), so a
    FloatType/ContentFloatListType/etc. instance can be written under
    either tag. _write_property_or_content()/_read_property_or_content()
    take an optional tag= override for exactly this purpose.
  - EncryptionType's ``encrypted_data`` is stored (by maiml_domain) as a
    raw <xenc:EncryptedData> XML string on both the way in and the way
    out; it is not decrypted, inspected, or re-encrypted.
  - Custom key prefixes (e.g. "KYL:Cantilever", "ISO18115-3:Wavenumber")
    must have their namespace declared via ``extra_namespaces`` when
    writing -- MaiML's key attributes are xs:QName, which XSD validation
    rejects if the prefix has no xmlns declaration in scope. loads()
    reports whatever was declared on the root element via
    LoadedMaiml.namespaces so a load-modify-dump round trip can reuse it
    without the caller having to re-track it by hand.
  - document.signature (a <Signature> read back by loads()) is read for
    inspection but never re-emitted by dumps()/dump() -- see dumps()'s
    docstring for why. If you need a signed output, sign the bytes dumps()
    produces with a dedicated tool (e.g. the maiml-signer skill), after
    dumping, not before.
"""
from __future__ import annotations

import base64
import binascii
import inspect
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union
from xml.dom import minidom
from xml.etree import ElementTree as ET

from lxml import etree as _lxml_etree

import maiml_domain as m

from ._xml_security import make_untrusted_input_parser
from ._xsi_registry import class_for_xsi_type, is_content_class, is_list_shaped, xsi_type_for

MAIML_NS = "http://www.maiml.org/schemas"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

__all__ = ["dumps", "dump", "loads", "load", "LoadedMaiml"]


# ---------------------------------------------------------------------------
# scalar value formatting
# ---------------------------------------------------------------------------

def _format_value(value, xsi_type: str) -> str:
    """Render a single Python value as MaiML XML text, per its xsi:type."""
    if isinstance(value, (bytes, bytearray)):
        # Case-insensitive, whole-string match -- see _parse_scalar_text's
        # docstring for why a literal "hexBinary" substring check silently
        # misses ContentHexBinaryListType (its "Hex" keeps the capital H
        # that only the very first letter of the *class name* loses).
        if "hexbinary" in xsi_type.lower():
            return binascii.hexlify(bytes(value)).decode("ascii")
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


# ---------------------------------------------------------------------------
# property / content  (genericDataContainerGroup, encryptionGroup)
# ---------------------------------------------------------------------------

def _write_encryption(parent_el: ET.Element, enc: "m.EncryptionType") -> None:
    """encryptionGroup: childUri* + childHash* + childUuid* + xenc:EncryptedData."""
    for uri in enc.child_uris:
        ET.SubElement(parent_el, "childUri").text = uri
    for h in enc.child_hashes:
        ET.SubElement(parent_el, "childHash").text = base64.b64encode(bytes(h)).decode("ascii")
    for u in enc.child_uuids:
        ET.SubElement(parent_el, "childUuid").text = str(u)
    frag = ET.fromstring(enc.encrypted_data)
    parent_el.append(frag)


def _write_property_or_content(parent_el: ET.Element, obj, tag: Optional[str] = None) -> ET.Element:
    """
    A propertyBaseType/contentBaseType instance:
      description? -> value? -> uncertainty* -> property* -> content*
    OR (xs:choice) an encryptionGroup payload.
    contentBaseType additionally carries axis/size/id/ref attributes.

    `tag` is normally left as None, in which case it is derived from the
    object's own kind ("content" for a content class, "property"
    otherwise). Pass tag="uncertainty" to instead write `obj` as an
    <uncertainty> element -- valid for the same concrete classes, since
    uncertaintyBaseType is the schema's common ancestor of propertyBaseType
    and contentBaseType (see module docstring).
    """
    xsi_type = xsi_type_for(obj)
    is_content = is_content_class(type(obj))
    if tag is None:
        tag = "content" if is_content else "property"

    attrs = {"key": obj.key}
    if is_content:
        if obj.axis is not None:
            attrs["axis"] = obj.axis
        if obj.size is not None:
            attrs["size"] = str(obj.size)
        if obj.id is not None:
            attrs["id"] = obj.id
        if obj.ref is not None:
            attrs["ref"] = obj.ref

    el = ET.SubElement(parent_el, tag, attrs)
    el.set("xsi:type", xsi_type)

    if obj.encryption is not None:
        _write_encryption(el, obj.encryption)
        return el

    if obj.description is not None:
        ET.SubElement(el, "description").text = obj.description

    if hasattr(obj, "values"):
        if obj.values:
            text = " ".join(_format_value(v, xsi_type) for v in obj.values)
            ET.SubElement(el, "value").text = text
    elif hasattr(obj, "value"):
        if obj.value is not None:
            ET.SubElement(el, "value").text = _format_value(obj.value, xsi_type)

    for u in obj.uncertainties:
        _write_property_or_content(el, u, tag="uncertainty")

    for child_prop in obj.properties:
        _write_property_or_content(el, child_prop)
    for child_content in obj.contents:
        _write_property_or_content(el, child_content)

    if hasattr(obj, "format_string") and obj.format_string is not None:
        el.set("formatString", str(obj.format_string))
    if hasattr(obj, "units") and obj.units is not None:
        el.set("units", obj.units)
    if hasattr(obj, "scale_factor") and obj.scale_factor is not None:
        el.set("scaleFactor", str(obj.scale_factor))

    return el


# ---------------------------------------------------------------------------
# globalObjectContentGroup:  uuid, then (encryptionGroup | insertion*,name?,
# description?,annotation?,property*,content*)
# ---------------------------------------------------------------------------

def _write_insertion(parent_el: ET.Element, ins: "m.InsertionType") -> None:
    el = ET.SubElement(parent_el, "insertion")
    ET.SubElement(el, "uri").text = ins.uri
    _write_hash(el, ins.hash)
    if ins.uuid is not None:
        ET.SubElement(el, "uuid").text = str(ins.uuid)
    if ins.format is not None:
        ET.SubElement(el, "format").text = ins.format


def _write_hash(parent_el: ET.Element, h: "m.HashType") -> None:
    el = ET.SubElement(parent_el, "hash")
    el.text = base64.b64encode(h.value).decode("ascii")
    if h.method is not None:
        el.set("method", h.method)


def _write_global_content(parent_el: ET.Element, content: "m.GlobalObjectContent") -> None:
    if content.uuid is not None:
        ET.SubElement(parent_el, "uuid").text = str(content.uuid)

    if content.encryption is not None:
        _write_encryption(parent_el, content.encryption)
        return

    for ins in content.insertions:
        _write_insertion(parent_el, ins)
    if content.name is not None:
        ET.SubElement(parent_el, "name").text = content.name
    if content.description is not None:
        ET.SubElement(parent_el, "description").text = content.description
    if content.annotation is not None:
        ET.SubElement(parent_el, "annotation").text = content.annotation
    for prop in content.properties:
        _write_property_or_content(parent_el, prop)
    for c in content.contents:
        _write_property_or_content(parent_el, c)


# ---------------------------------------------------------------------------
# small shared shapes: refTypes, simpleObjectType (place/transition), arc
# ---------------------------------------------------------------------------

def _write_ref(parent_el: ET.Element, tag: str, ref_obj) -> ET.Element:
    """referenceObjectType: id/ref attributes + name?/description? child elements."""
    el = ET.SubElement(parent_el, tag, {"id": ref_obj.id, "ref": ref_obj.ref})
    if ref_obj.name is not None:
        ET.SubElement(el, "name").text = ref_obj.name
    if ref_obj.description is not None:
        ET.SubElement(el, "description").text = ref_obj.description
    initial_marking = getattr(ref_obj, "initial_marking", None)
    if initial_marking is not None:
        el.set("initialMarking", "true" if initial_marking else "false")
    return el


def _write_simple_object(parent_el: ET.Element, tag: str, obj) -> ET.Element:
    """simpleObjectType: id attribute + name?/description? child elements."""
    el = ET.SubElement(parent_el, tag, {"id": obj.id})
    if obj.name is not None:
        ET.SubElement(el, "name").text = obj.name
    if obj.description is not None:
        ET.SubElement(el, "description").text = obj.description
    return el


def _write_arc(parent_el: ET.Element, arc: "m.ArcType") -> ET.Element:
    """tripleObjectType: id/source/target attributes + name?/description?."""
    el = ET.SubElement(parent_el, "arc", {"id": arc.id, "source": arc.source, "target": arc.target})
    if arc.name is not None:
        ET.SubElement(el, "name").text = arc.name
    if arc.description is not None:
        ET.SubElement(el, "description").text = arc.description
    return el


# ---------------------------------------------------------------------------
# document  (maiml-document.xsd)
# ---------------------------------------------------------------------------

def _write_document(parent_el: ET.Element, doc: "m.DocumentType") -> ET.Element:
    """documentType: Signature? -> content -> creator+ -> vendor+ -> owner+ ->
    instrument* -> date -> chain* -> parent*.

    An existing doc.signature (as read back by loads()) is intentionally
    never re-emitted here: dumps() always drops it. See dumps()'s
    docstring for the rationale (an enveloped XML signature is a claim
    about the exact serialized byte form pymaiml cannot guarantee to
    reproduce, and pymaiml does not implement signing/verification
    itself)."""
    doc_el = ET.SubElement(parent_el, "document", {"id": doc.id})
    _write_global_content(doc_el, doc.content)
    for c in doc.creators:
        c_el = ET.SubElement(doc_el, "creator", {"id": c.id})
        _write_global_content(c_el, c.content)
        for vr in c.vendor_refs:
            _write_ref(c_el, "vendorRef", vr)
        for ir in c.instrument_refs:
            _write_ref(c_el, "instrumentRef", ir)
    for v in doc.vendors:
        v_el = ET.SubElement(doc_el, "vendor", {"id": v.id})
        _write_global_content(v_el, v.content)
    for o in doc.owners:
        o_el = ET.SubElement(doc_el, "owner", {"id": o.id})
        _write_global_content(o_el, o.content)
    for inst in doc.instruments:
        i_el = ET.SubElement(doc_el, "instrument", {"id": inst.id})
        _write_global_content(i_el, inst.content)
    ET.SubElement(doc_el, "date").text = doc.date.isoformat()
    for chain in doc.chains:
        _write_chain_or_parent(doc_el, "chain", chain)
    for parent in doc.parents:
        _write_chain_or_parent(doc_el, "parent", parent)
    return doc_el


def _write_chain_or_parent(parent_el: ET.Element, tag: str, obj) -> ET.Element:
    """chainType/parentType: uuid -> hash -> nested chain*/parent* (recursive)."""
    el = ET.SubElement(parent_el, tag)
    if obj.key is not None:
        el.set("key", obj.key)
    ET.SubElement(el, "uuid").text = str(obj.uuid)
    _write_hash(el, obj.hash)
    nested = obj.chains if tag == "chain" else obj.parents
    for child in nested:
        _write_chain_or_parent(el, tag, child)
    return el


# ---------------------------------------------------------------------------
# protocol  (maiml-protocol.xsd, maiml-pnml.xsd)
# ---------------------------------------------------------------------------

def _write_template(parent_el: ET.Element, tag: str, tmpl) -> ET.Element:
    """materialTemplateType/conditionTemplateType/resultTemplateType:
    content -> placeRef+ -> templateRef*."""
    el = ET.SubElement(parent_el, tag, {"id": tmpl.id})
    _write_global_content(el, tmpl.content)
    for pr in tmpl.place_refs:
        _write_ref(el, "placeRef", pr)
    for tr in tmpl.template_refs:
        _write_ref(el, "templateRef", tr)
    return el


def _write_templates(parent_el: ET.Element, holder) -> None:
    for mt in holder.material_templates:
        _write_template(parent_el, "materialTemplate", mt)
    for ct in holder.condition_templates:
        _write_template(parent_el, "conditionTemplate", ct)
    for rt in holder.result_templates:
        _write_template(parent_el, "resultTemplate", rt)


def _write_instruction(parent_el: ET.Element, instr: "m.InstructionType") -> ET.Element:
    """instructionType: content -> transitionRef+."""
    el = ET.SubElement(parent_el, "instruction", {"id": instr.id})
    _write_global_content(el, instr.content)
    for tref in instr.transition_refs:
        _write_ref(el, "transitionRef", tref)
    return el


def _write_program(parent_el: ET.Element, prog: "m.ProgramType") -> ET.Element:
    """programType: content -> instruction+ -> materialTemplate*/conditionTemplate*/resultTemplate*."""
    el = ET.SubElement(parent_el, "program", {"id": prog.id})
    _write_global_content(el, prog.content)
    for instr in prog.instructions:
        _write_instruction(el, instr)
    _write_templates(el, prog)
    return el


def _write_pnml(parent_el: ET.Element, pn: "m.PnmlType") -> ET.Element:
    """pnmlType: content -> place+ -> transition+ -> arc+."""
    el = ET.SubElement(parent_el, "pnml", {"id": pn.id})
    _write_global_content(el, pn.content)
    for pl in pn.places:
        _write_simple_object(el, "place", pl)
    for tr in pn.transitions:
        _write_simple_object(el, "transition", tr)
    for arc in pn.arcs:
        _write_arc(el, arc)
    return el


def _write_method(parent_el: ET.Element, meth: "m.MethodType") -> ET.Element:
    """methodType: content -> pnml+ -> program+ -> materialTemplate*/conditionTemplate*/resultTemplate*."""
    el = ET.SubElement(parent_el, "method", {"id": meth.id})
    _write_global_content(el, meth.content)
    for pn in meth.pnmls:
        _write_pnml(el, pn)
    for prog in meth.programs:
        _write_program(el, prog)
    _write_templates(el, meth)
    return el


def _write_protocol(parent_el: ET.Element, proto: "m.ProtocolType") -> ET.Element:
    """protocolType: content -> method+ -> materialTemplate*/conditionTemplate*/resultTemplate*."""
    el = ET.SubElement(parent_el, "protocol", {"id": proto.id})
    _write_global_content(el, proto.content)
    for meth in proto.methods:
        _write_method(el, meth)
    _write_templates(el, proto)
    return el


# ---------------------------------------------------------------------------
# data  (maiml-data.xsd)
# ---------------------------------------------------------------------------

def _write_instance(parent_el: ET.Element, tag: str, obj) -> ET.Element:
    """materialType/conditionType/resultType: content -> instanceRef*; ref attribute."""
    el = ET.SubElement(parent_el, tag, {"id": obj.id, "ref": obj.ref})
    _write_global_content(el, obj.content)
    for ir in obj.instance_refs:
        _write_ref(el, "instanceRef", ir)
    return el


def _write_results(parent_el: ET.Element, res: "m.ResultsType") -> ET.Element:
    """resultsType: content -> material* -> condition* -> result*."""
    el = ET.SubElement(parent_el, "results", {"id": res.id})
    _write_global_content(el, res.content)
    for mat in res.materials:
        _write_instance(el, "material", mat)
    for cond in res.conditions:
        _write_instance(el, "condition", cond)
    for result in res.results:
        _write_instance(el, "result", result)
    return el


def _write_data(parent_el: ET.Element, data: "m.DataType") -> ET.Element:
    """dataType: content -> results+."""
    el = ET.SubElement(parent_el, "data", {"id": data.id})
    _write_global_content(el, data.content)
    for res in data.results_list:
        _write_results(el, res)
    return el


# ---------------------------------------------------------------------------
# eventLog  (maiml-eventLog.xsd)
# ---------------------------------------------------------------------------

def _write_event(parent_el: ET.Element, ev: "m.EventType") -> ET.Element:
    """eventType: content -> resultsRef* -> creatorRef* -> ownerRef*; ref attribute."""
    el = ET.SubElement(parent_el, "event", {"id": ev.id, "ref": ev.ref})
    _write_global_content(el, ev.content)
    for rr in ev.results_refs:
        _write_ref(el, "resultsRef", rr)
    for cr in ev.creator_refs:
        _write_ref(el, "creatorRef", cr)
    for orf in ev.owner_refs:
        _write_ref(el, "ownerRef", orf)
    return el


def _write_trace(parent_el: ET.Element, tc: "m.TraceType") -> ET.Element:
    """traceType: content -> event+ -> creatorRef* -> ownerRef*; ref attribute."""
    el = ET.SubElement(parent_el, "trace", {"id": tc.id, "ref": tc.ref})
    _write_global_content(el, tc.content)
    for ev in tc.events:
        _write_event(el, ev)
    for cr in tc.creator_refs:
        _write_ref(el, "creatorRef", cr)
    for orf in tc.owner_refs:
        _write_ref(el, "ownerRef", orf)
    return el


def _write_log(parent_el: ET.Element, lg: "m.LogType") -> ET.Element:
    """logType: content -> extension* -> global* -> classifier* -> trace+ ->
    creatorRef* -> ownerRef*; ref attribute."""
    el = ET.SubElement(parent_el, "log", {"id": lg.id, "ref": lg.ref})
    _write_global_content(el, lg.content)
    for ext in lg.extensions:
        ET.SubElement(el, "extension", {"name": ext.name, "prefix": ext.prefix, "uri": ext.uri})
    for g in lg.globals:
        g_el = ET.SubElement(el, "global", {"scope": g.scope})
        for prop in g.properties:
            _write_property_or_content(g_el, prop)
    for cl in lg.classifiers:
        ET.SubElement(el, "classifier", {"name": cl.name, "scope": cl.scope, "keys": cl.keys})
    for tc in lg.traces:
        _write_trace(el, tc)
    for cr in lg.creator_refs:
        _write_ref(el, "creatorRef", cr)
    for orf in lg.owner_refs:
        _write_ref(el, "ownerRef", orf)
    return el


def _write_event_log(parent_el: ET.Element, elog: "m.EventLogType") -> ET.Element:
    """eventLogType: content -> log+."""
    el = ET.SubElement(parent_el, "eventLog", {"id": elog.id})
    _write_global_content(el, elog.content)
    for lg in elog.logs:
        _write_log(el, lg)
    return el


# ---------------------------------------------------------------------------
# root  (maiml.xsd)
# ---------------------------------------------------------------------------

_ROOT_OPEN_TAG_RE = re.compile(r"^(<maiml)((?:\s+[^\s=]+=\"[^\"]*\")*)\s*(/?>)")


def _dedupe_root_namespace_decls(xml_text: str) -> str:
    """Collapse duplicate xmlns/xmlns:<prefix> declarations on the root
    <maiml> element.

    dumps() can end up declaring the same prefix twice on <maiml>: once
    because MAIML_NS/XSI_NS/extra_namespaces are set as literal attributes
    up front, and once more because xml.etree.ElementTree's own namespace
    machinery auto-declares a prefix (ns0, ns1, ...) for whatever real
    {uri}-qualified content got appended verbatim from a loaded
    <EncryptedData> block (_write_encryption parses that with
    ET.fromstring() and appends it as-is; unlike the rest of this module
    it carries genuine namespace-qualified tags, which ElementTree's
    serializer discovers by scanning the whole tree and declares at the
    root -- it has no way to know a literal same-named attribute is
    already there). The result is a root element with the same attribute
    name twice, which is a well-formedness error (ExpatError: duplicate
    attribute) once fed through minidom, and invalid XML even with
    pretty=False.

    A load-modify-dump round trip of pymaiml's own output always
    produces the *same* URI for a colliding prefix (ElementTree assigns
    ns0/ns1/... deterministically from tree order), so dropping the
    duplicate and keeping the first occurrence is safe for that case. A
    genuine conflict (same prefix, two different URIs) is a caller error
    -- e.g. passing an extra_namespaces mapping that reuses a prefix
    ElementTree also needs for an embedded signature -- and is raised
    explicitly instead of silently picking one and corrupting the file.
    """
    match = _ROOT_OPEN_TAG_RE.match(xml_text)
    if not match:
        return xml_text
    open_tag, attrs_blob, closer = match.group(1), match.group(2), match.group(3)
    pairs = re.findall(r'([^\s=]+)="([^"]*)"', attrs_blob)
    seen: Dict[str, str] = {}
    ordered_names: List[str] = []
    for name, value in pairs:
        if name in seen:
            if seen[name] != value:
                raise ValueError(
                    f"dumps(): conflicting declarations for {name!r} on the root "
                    f"<maiml> element ({seen[name]!r} vs {value!r}). This can "
                    "happen when extra_namespaces reuses a prefix that "
                    "xml.etree.ElementTree also auto-assigns to a namespace used "
                    "inside an embedded <EncryptedData> block -- pass "
                    "a non-conflicting extra_namespaces mapping (e.g. drop the "
                    "auto-assigned prefix from loaded.namespaces before "
                    "re-dumping)."
                )
            continue
        seen[name] = value
        ordered_names.append(name)
    rebuilt_attrs = "".join(f' {name}="{seen[name]}"' for name in ordered_names)
    return xml_text[: match.start()] + open_tag + rebuilt_attrs + closer + xml_text[match.end():]


def _build_maiml_element(
    root_obj: Union["m.MaimlRootType", "m.ProtocolFileRootType"],
    *,
    extra_namespaces: Optional[Dict[str, str]] = None,
) -> ET.Element:
    """Build the <maiml> ElementTree tree for root_obj (the single
    field-by-field walk of the object tree that dumps() uses)."""
    if not isinstance(root_obj, (m.MaimlRootType, m.ProtocolFileRootType)):
        raise TypeError(
            "dumps() requires a maiml_domain.MaimlRootType or "
            f"ProtocolFileRootType instance, got {type(root_obj)!r}"
        )

    maiml_el = ET.Element("maiml")
    maiml_el.set("xmlns", MAIML_NS)
    maiml_el.set("xmlns:xsi", XSI_NS)
    for prefix, uri in (extra_namespaces or {}).items():
        maiml_el.set(f"xmlns:{prefix}", uri)

    xsi_type = "maimlRootType" if isinstance(root_obj, m.MaimlRootType) else "protocolFileRootType"
    maiml_el.set("xsi:type", xsi_type)
    maiml_el.set("version", root_obj.version)
    if root_obj.features:
        maiml_el.set("features", root_obj.features)

    _write_document(maiml_el, root_obj.document)
    _write_protocol(maiml_el, root_obj.protocol)
    if isinstance(root_obj, m.MaimlRootType):
        _write_data(maiml_el, root_obj.data)
        _write_event_log(maiml_el, root_obj.event_log)
    return maiml_el


def dumps(
    root_obj: Union["m.MaimlRootType", "m.ProtocolFileRootType"],
    *,
    extra_namespaces: Optional[Dict[str, str]] = None,
    pretty: bool = True,
) -> str:
    """
    Serialize a MaimlRootType/ProtocolFileRootType object tree to a MaiML
    XML string.

    extra_namespaces: {prefix: uri} declared as xmlns:<prefix> on the root
    <maiml> element. Required for any custom key= prefix used on a
    property/content (e.g. {"KYL": "http://example.org/kyl-instrument-properties"})
    -- MaiML's key attributes are xs:QName, so XSD validation fails if the
    prefix has no namespace declaration in scope. The XES lifecycle/concept/
    time extensions, if used via property keys like "lifecycle:transition",
    must likewise be declared here with their exact standard URIs
    (http://www.xes-standard.org/<name>.xesext#).

    root_obj.document.signature (a <Signature> loads() read back from an
    existing file) is ALWAYS dropped from the output, unconditionally --
    there is no parameter to keep it. Earlier versions had a
    drop_stale_signature= parameter that kept a signature through when
    dumps() could tell nothing besides the signature had changed since
    load; that has been removed.

    The reason is not merely "an edited file's signature is stale" -- it's
    that dumps() cannot make ANY serialization of this object tree a safe
    carrier of a pre-existing enveloped signature, changed or not. MaiML's
    <Signature> is an enveloped XML signature under JIS X 5093 / ETSI TS
    101 903 (XAdES): the digest is computed over the exact serialized byte
    form of the document at the moment of signing, and JIS's own signing
    procedure treats that byte form as fixed afterwards (nothing may be
    added after the closing </Signature> tag but a trailing newline).
    dumps() reconstructs the tree from maiml_domain objects and re-applies
    its own formatting (indentation, namespace-declaration placement,
    attribute ordering, empty-element representation, ...); it does not
    reproduce another implementation's exact byte form, and pymaiml does
    not implement XAdES signing or verification itself (see
    CONTRIBUTING.md) -- so it has no way to certify that any particular
    dumps() output is still a valid carrier for a signature it did not
    just compute itself. Treating "detectably unchanged content" as
    grounds for keeping the old signature (the previous behavior) implied
    a safety guarantee pymaiml cannot actually make.

    Practically: pymaiml.serialization.loads() still reads
    root_obj.document.signature back for inspection (e.g. to hand to an
    external verifier), but dumps()/dump() never write it back out. If you
    need a signed MaiML file, dump the content first, then sign the
    resulting bytes with a dedicated tool (e.g. the maiml-signer skill) --
    treat "build/edit the MaiML content" and "sign the finished file" as
    two separate steps, in that order, never the other way around.
    """
    maiml_el = _build_maiml_element(root_obj, extra_namespaces=extra_namespaces)

    rough = ET.tostring(maiml_el, encoding="unicode")
    rough = _dedupe_root_namespace_decls(rough)
    if not pretty:
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + rough

    pretty_xml = minidom.parseString(rough).toprettyxml(indent="  ")
    pretty_xml = "\n".join(line for line in pretty_xml.split("\n") if line.strip())
    pretty_xml = pretty_xml.split("\n", 1)[1]  # drop minidom's own XML declaration
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + pretty_xml


def dump(
    root_obj: Union["m.MaimlRootType", "m.ProtocolFileRootType"],
    path: Union[str, Path],
    **kwargs,
) -> None:
    """Serialize root_obj and write it to `path` (parent directories created as needed)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(root_obj, **kwargs), encoding="utf-8")


def _local(tag) -> Optional[str]:
    if not isinstance(tag, str):
        return None
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _find(el, name):
    """First direct child of `el` with local-name == name, or None."""
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _find_all(el, name):
    """All direct children of `el` with local-name == name."""
    return [c for c in el if _local(c.tag) == name]


def _text_of(el, name) -> Optional[str]:
    """Text of the first `name` child, or None if that child is absent.

    Distinguishes "the element is missing" (None) from "the element is
    present but empty" (""), which is a valid, distinct value for any
    XSD xs:string field with minOccurs="0" (e.g. <description/>). Both
    lxml and ElementTree report .text as None for an empty element, so
    callers must not use `child.text` directly for that distinction --
    doing so silently drops the element on the next dumps() call.
    """
    child = _find(el, name)
    if child is None:
        return None
    return child.text or ""


# ---------------------------------------------------------------------------
# reading: scalar value parsing (inverse of _format_value)
# ---------------------------------------------------------------------------

def _parse_scalar_text(text: str, xsi_type: str):
    """Convert one whitespace-delimited MaiML value token back to a Python
    value, dispatching on the xsi:type name the same way _format_value's
    caller chose how to render it. See is_list_shaped()/_format_value() for
    the write-side counterpart of this table.

    The dispatch is deliberately case-insensitive on the *whole* xsi_type
    string (lowercased once into `t`), not a naive substring check against
    the token's original capitalization. pymaiml._xsi_registry derives an
    xsi:type name from a maiml_domain class name by lowercasing only the
    class name's FIRST character (e.g. "FloatType" -> "floatType"), so a
    keyword that sits at position 0 of the class name loses its capital
    letter in the resulting xsi:type -- meaning "Float" in "floatType" is
    False! Only class names where the keyword appears later (e.g.
    "UnsignedLongType" -> "unsignedLongType", "ContentHexBinaryListType" ->
    "contentHexBinaryListType") kept their original-case substring by
    accident. Comparing lowercased tokens against a lowercased xsi_type
    avoids this trap uniformly.
    """
    t = xsi_type.lower()
    if "boolean" in t:
        return text.strip() == "true"
    if "datetime" in t:
        return datetime.fromisoformat(text.strip())
    if "base64binary" in t:
        return base64.b64decode(text.strip())
    if "hexbinary" in t:
        return binascii.unhexlify(text.strip())
    if "uuid" in t:
        return m.Uuid(text.strip())
    if "decimal" in t:
        from decimal import Decimal
        return Decimal(text.strip())
    if "double" in t or "float" in t:
        return float(text.strip())
    if any(token in t for token in ("long", "short", "byte", "int")):
        return int(text.strip())
    return text  # String/Token/Id/IdRef/QualifiedName/Uri/Language/StringEnum


# ---------------------------------------------------------------------------
# reading: property / content  (inverse of _write_property_or_content)
# ---------------------------------------------------------------------------

_ENCRYPTION_CHILD_NAMES = {"childUri", "childHash", "childUuid", "EncryptedData"}


def _read_encryption(el) -> "m.EncryptionType":
    child_uris: list = []
    child_hashes: list = []
    child_uuids: list = []
    encrypted_data_xml: Optional[str] = None
    for child in el:
        name = _local(child.tag)
        if name == "childUri":
            child_uris.append(child.text)
        elif name == "childHash":
            child_hashes.append(base64.b64decode((child.text or "").strip()))
        elif name == "childUuid":
            child_uuids.append(m.Uuid((child.text or "").strip()))
        elif name == "EncryptedData":
            encrypted_data_xml = _lxml_etree.tostring(child, encoding="unicode")
    return m.EncryptionType(
        encrypted_data=encrypted_data_xml,
        child_uris=child_uris, child_hashes=child_hashes, child_uuids=child_uuids,
    )


def _read_property_or_content(el):
    """
    Inverse of _write_property_or_content: reconstruct one property/content
    instance from its <property>/<content> element, recursing into any
    nested property*/content*.
    """
    xsi_type = el.get(f"{{{XSI_NS}}}type")
    cls = class_for_xsi_type(xsi_type)
    key = el.get("key")

    kwargs: Dict = {}
    if is_content_class(cls):
        if el.get("axis") is not None:
            kwargs["axis"] = el.get("axis")
        if el.get("size") is not None:
            kwargs["size"] = int(el.get("size"))
        if el.get("id") is not None:
            kwargs["id"] = el.get("id")
        if el.get("ref") is not None:
            kwargs["ref"] = el.get("ref")
    init_params = inspect.signature(cls.__init__).parameters

    def _require_param(param_name: str, xml_attr: str) -> None:
        if param_name in init_params:
            return
        raise ValueError(
            f"<property>/<content> key={key!r} xsi:type={xsi_type!r} has a "
            f"{xml_attr!r} attribute, but {cls.__name__} does not accept a "
            f"{param_name!r} value -- units/formatString/scaleFactor only "
            "apply to numeric property/content types. This file is not "
            "MaiML-Schema-1_0 valid; run pymaiml.validation.validate() on "
            "it to see every such error at once instead of stopping at the "
            "first one loads() happens to reach."
        )

    if el.get("formatString") is not None:
        _require_param("format_string", "formatString")
        kwargs["format_string"] = el.get("formatString")
    if el.get("units") is not None:
        _require_param("units", "units")
        kwargs["units"] = el.get("units")
    if el.get("scaleFactor") is not None:
        _require_param("scale_factor", "scaleFactor")
        raw = el.get("scaleFactor")
        try:
            kwargs["scale_factor"] = int(raw)
        except ValueError:
            kwargs["scale_factor"] = float(raw)

    children = list(el)
    if any(_local(c.tag) in _ENCRYPTION_CHILD_NAMES for c in children):
        kwargs["encryption"] = _read_encryption(el)
        return cls(key=key, **kwargs)

    description = None
    value_text = None
    nested_properties = []
    nested_contents = []
    nested_uncertainties = []
    for child in children:
        name = _local(child.tag)
        if name == "description":
            description = child.text or ""
        elif name == "value":
            value_text = child.text if child.text is not None else ""
        elif name == "uncertainty":
            nested_uncertainties.append(_read_property_or_content(child))
        elif name == "property":
            nested_properties.append(_read_property_or_content(child))
        elif name == "content":
            nested_contents.append(_read_property_or_content(child))

    if description is not None:
        kwargs["description"] = description
    if nested_properties:
        kwargs["properties"] = nested_properties
    if nested_contents:
        kwargs["contents"] = nested_contents
    if nested_uncertainties:
        kwargs["uncertainties"] = nested_uncertainties

    if value_text is not None:
        if is_list_shaped(cls):
            kwargs["values"] = [_parse_scalar_text(tok, xsi_type) for tok in value_text.split()]
        else:
            kwargs["value"] = _parse_scalar_text(value_text, xsi_type)

    return cls(key=key, **kwargs)


# ---------------------------------------------------------------------------
# reading: globalObjectContentGroup, insertion, hash, chain/parent
# ---------------------------------------------------------------------------

def _read_insertion(el) -> "m.InsertionType":
    hash_el = _find(el, "hash")
    uuid_el = _find(el, "uuid")
    format_el = _find(el, "format")
    return m.InsertionType(
        uri=_text_of(el, "uri"),
        hash=m.HashType(value=base64.b64decode((hash_el.text or "").strip()), method=hash_el.get("method")),
        uuid=m.Uuid(uuid_el.text.strip()) if uuid_el is not None else None,
        format=(format_el.text or "") if format_el is not None else None,
    )


def _read_global_content(el) -> "m.GlobalObjectContent":
    """
    Inverse of _write_global_content. Scans el's direct children for the
    globalObjectContentGroup shape (uuid, then either an encryption payload
    or insertion*/name/description/annotation/property*/content*) --
    ignores any other direct children el may have (e.g. <document>'s
    <creator>/<vendor>/.../<date>), which the caller reads separately.
    """
    children = list(el)
    if any(_local(c.tag) in _ENCRYPTION_CHILD_NAMES for c in children):
        uuid_el = _find(el, "uuid")
        uuid_val = m.Uuid(uuid_el.text.strip()) if uuid_el is not None else None
        return m.GlobalObjectContent(uuid=uuid_val, encryption=_read_encryption(el))

    uuid_el = _find(el, "uuid")
    uuid_val = m.Uuid(uuid_el.text.strip()) if uuid_el is not None else None
    insertions = [_read_insertion(c) for c in _find_all(el, "insertion")]
    name_val = _text_of(el, "name")
    description = _text_of(el, "description")
    annotation = _text_of(el, "annotation")
    properties = [_read_property_or_content(c) for c in _find_all(el, "property")]
    contents = [_read_property_or_content(c) for c in _find_all(el, "content")]
    return m.GlobalObjectContent(
        uuid=uuid_val, insertions=insertions, name=name_val,
        description=description, annotation=annotation,
        properties=properties, contents=contents,
    )


def _read_hash(el) -> "m.HashType":
    hash_el = _find(el, "hash")
    return m.HashType(value=base64.b64decode((hash_el.text or "").strip()), method=hash_el.get("method"))


def _read_chain_or_parent(el, tag: str):
    cls = m.ChainType if tag == "chain" else m.ParentType
    nested = [_read_chain_or_parent(c, tag) for c in _find_all(el, tag)]
    kwargs = {"chains": nested} if tag == "chain" else {"parents": nested}
    uuid_el = _find(el, "uuid")
    return cls(uuid=m.Uuid(uuid_el.text.strip()), hash=_read_hash(el), key=el.get("key"), **kwargs)


# ---------------------------------------------------------------------------
# reading: refTypes / simpleObjectType / arc
# ---------------------------------------------------------------------------

_REF_CLASS_BY_TAG = {
    "vendorRef": m.VendorRefType,
    "instrumentRef": m.InstrumentRefType,
    "placeRef": m.PlaceRefType,
    "transitionRef": m.TransitionRefType,
    "templateRef": m.TemplateRefType,
    "instanceRef": m.InstanceRefType,
    "creatorRef": m.CreatorRefType,
    "ownerRef": m.OwnerRefType,
    "resultsRef": m.ResultsRefType,
}


def _read_ref(el, tag: str):
    cls = _REF_CLASS_BY_TAG[tag]
    kwargs: Dict = {"id": el.get("id"), "ref": el.get("ref")}
    name_val = _text_of(el, "name")
    if name_val is not None:
        kwargs["name"] = name_val
    description = _text_of(el, "description")
    if description is not None:
        kwargs["description"] = description
    if tag == "placeRef" and el.get("initialMarking") is not None:
        kwargs["initial_marking"] = el.get("initialMarking") == "true"
    return cls(**kwargs)


def _read_simple_object(el, cls):
    return cls(id=el.get("id"), name=_text_of(el, "name"), description=_text_of(el, "description"))


def _read_arc(el) -> "m.ArcType":
    return m.ArcType(
        id=el.get("id"), source=el.get("source"), target=el.get("target"),
        name=_text_of(el, "name"), description=_text_of(el, "description"),
    )


# ---------------------------------------------------------------------------
# reading: document
# ---------------------------------------------------------------------------

def _read_document(el) -> "m.DocumentType":
    signature_el = _find(el, "Signature")
    signature = _lxml_etree.tostring(signature_el, encoding="unicode") if signature_el is not None else None

    creators = []
    for c_el in _find_all(el, "creator"):
        creators.append(m.CreatorType(
            id=c_el.get("id"),
            vendor_refs=[_read_ref(vr, "vendorRef") for vr in _find_all(c_el, "vendorRef")],
            instrument_refs=[_read_ref(ir, "instrumentRef") for ir in _find_all(c_el, "instrumentRef")],
            content=_read_global_content(c_el),
        ))
    vendors = [m.VendorType(id=v.get("id"), content=_read_global_content(v)) for v in _find_all(el, "vendor")]
    owners = [m.OwnerType(id=o.get("id"), content=_read_global_content(o)) for o in _find_all(el, "owner")]
    instruments = [m.InstrumentType(id=i.get("id"), content=_read_global_content(i)) for i in _find_all(el, "instrument")]
    date_el = _find(el, "date")
    chains = [_read_chain_or_parent(c, "chain") for c in _find_all(el, "chain")]
    parents = [_read_chain_or_parent(p, "parent") for p in _find_all(el, "parent")]

    return m.DocumentType(
        id=el.get("id"),
        date=datetime.fromisoformat(date_el.text.strip()),
        creators=creators, vendors=vendors, owners=owners,
        content=_read_global_content(el),
        instruments=instruments, chains=chains, parents=parents,
        signature=signature,
    )


# ---------------------------------------------------------------------------
# reading: protocol / pnml
# ---------------------------------------------------------------------------

def _read_pnml(el) -> "m.PnmlType":
    return m.PnmlType(
        id=el.get("id"),
        places=[_read_simple_object(p, m.PlaceType) for p in _find_all(el, "place")],
        transitions=[_read_simple_object(t, m.TransitionType) for t in _find_all(el, "transition")],
        arcs=[_read_arc(a) for a in _find_all(el, "arc")],
        content=_read_global_content(el),
    )


def _read_instruction(el) -> "m.InstructionType":
    return m.InstructionType(
        id=el.get("id"),
        transition_refs=[_read_ref(tr, "transitionRef") for tr in _find_all(el, "transitionRef")],
        content=_read_global_content(el),
    )


def _read_template(el, cls):
    return cls(
        id=el.get("id"),
        place_refs=[_read_ref(pr, "placeRef") for pr in _find_all(el, "placeRef")],
        content=_read_global_content(el),
        template_refs=[_read_ref(tr, "templateRef") for tr in _find_all(el, "templateRef")],
    )


def _read_templates(el) -> Dict:
    return dict(
        material_templates=[_read_template(t, m.MaterialTemplateType) for t in _find_all(el, "materialTemplate")],
        condition_templates=[_read_template(t, m.ConditionTemplateType) for t in _find_all(el, "conditionTemplate")],
        result_templates=[_read_template(t, m.ResultTemplateType) for t in _find_all(el, "resultTemplate")],
    )


def _read_program(el) -> "m.ProgramType":
    return m.ProgramType(
        id=el.get("id"),
        instructions=[_read_instruction(i) for i in _find_all(el, "instruction")],
        content=_read_global_content(el),
        **_read_templates(el),
    )


def _read_method(el) -> "m.MethodType":
    return m.MethodType(
        id=el.get("id"),
        pnmls=[_read_pnml(p) for p in _find_all(el, "pnml")],
        programs=[_read_program(p) for p in _find_all(el, "program")],
        content=_read_global_content(el),
        **_read_templates(el),
    )


def _read_protocol(el) -> "m.ProtocolType":
    return m.ProtocolType(
        id=el.get("id"),
        methods=[_read_method(me) for me in _find_all(el, "method")],
        content=_read_global_content(el),
        **_read_templates(el),
    )


# ---------------------------------------------------------------------------
# reading: data
# ---------------------------------------------------------------------------

def _read_instance(el, cls):
    return cls(
        id=el.get("id"), ref=el.get("ref"),
        content=_read_global_content(el),
        instance_refs=[_read_ref(ir, "instanceRef") for ir in _find_all(el, "instanceRef")],
    )


def _read_results(el) -> "m.ResultsType":
    return m.ResultsType(
        id=el.get("id"),
        content=_read_global_content(el),
        materials=[_read_instance(x, m.MaterialType) for x in _find_all(el, "material")],
        conditions=[_read_instance(x, m.ConditionType) for x in _find_all(el, "condition")],
        results=[_read_instance(x, m.ResultType) for x in _find_all(el, "result")],
    )


def _read_data(el) -> "m.DataType":
    return m.DataType(
        id=el.get("id"),
        results_list=[_read_results(r) for r in _find_all(el, "results")],
        content=_read_global_content(el),
    )


# ---------------------------------------------------------------------------
# reading: eventLog
# ---------------------------------------------------------------------------

def _read_event(el) -> "m.EventType":
    return m.EventType(
        id=el.get("id"), ref=el.get("ref"),
        content=_read_global_content(el),
        results_refs=[_read_ref(x, "resultsRef") for x in _find_all(el, "resultsRef")],
        creator_refs=[_read_ref(x, "creatorRef") for x in _find_all(el, "creatorRef")],
        owner_refs=[_read_ref(x, "ownerRef") for x in _find_all(el, "ownerRef")],
    )


def _read_trace(el) -> "m.TraceType":
    return m.TraceType(
        id=el.get("id"), ref=el.get("ref"),
        events=[_read_event(e) for e in _find_all(el, "event")],
        content=_read_global_content(el),
        creator_refs=[_read_ref(x, "creatorRef") for x in _find_all(el, "creatorRef")],
        owner_refs=[_read_ref(x, "ownerRef") for x in _find_all(el, "ownerRef")],
    )


def _read_log(el) -> "m.LogType":
    globals_ = []
    for g_el in _find_all(el, "global"):
        globals_.append(m.GlobalsType(
            scope=g_el.get("scope"),
            properties=[_read_property_or_content(p) for p in _find_all(g_el, "property")],
        ))
    return m.LogType(
        id=el.get("id"), ref=el.get("ref"),
        traces=[_read_trace(t) for t in _find_all(el, "trace")],
        content=_read_global_content(el),
        extensions=[
            m.ExtensionType(name=x.get("name"), prefix=x.get("prefix"), uri=x.get("uri"))
            for x in _find_all(el, "extension")
        ],
        globals=globals_,
        classifiers=[
            m.ClassifierType(name=x.get("name"), scope=x.get("scope"), keys=x.get("keys"))
            for x in _find_all(el, "classifier")
        ],
        creator_refs=[_read_ref(x, "creatorRef") for x in _find_all(el, "creatorRef")],
        owner_refs=[_read_ref(x, "ownerRef") for x in _find_all(el, "ownerRef")],
    )


def _read_event_log(el) -> "m.EventLogType":
    return m.EventLogType(
        id=el.get("id"),
        logs=[_read_log(lg) for lg in _find_all(el, "log")],
        content=_read_global_content(el),
    )


# ---------------------------------------------------------------------------
# root: loads() / load()
# ---------------------------------------------------------------------------

@dataclass
class LoadedMaiml:
    """
    Result of loads()/load(): the parsed object tree plus the two things a
    "load an existing file, keep its protocol, add new data/eventLog"
    workflow needs and can't get from the maiml_domain objects alone.

    root: a MaimlRootType or ProtocolFileRootType, matching the file's own
        xsi:type. For a ProtocolFileRootType, build a new MaimlRootType
        re-using `root.document` and `root.protocol` as-is, plus your own
        new DataType/EventLogType, then dumps() that.
    namespaces: every xmlns:<prefix> declared on the root <maiml> element,
        other than the fixed default (MAIML_NS) and xsi: bindings -- e.g.
        {"KYL": "...", "lifecycle": "http://www.xes-standard.org/..."}.
        Pass this straight back as dumps(..., extra_namespaces=namespaces)
        so a load-modify-dump round trip doesn't have to re-track which
        custom prefixes the original file declared.
    ids: every id= value found anywhere in the file, in document order.
        Feed this to pymaiml.builders.IdFactory.from_existing_ids(ids) so
        newly generated ids for the data you add cannot collide with ids
        already used by the loaded content.
    """
    root: Union["m.MaimlRootType", "m.ProtocolFileRootType"]
    namespaces: Dict[str, str] = field(default_factory=dict)
    ids: List[str] = field(default_factory=list)


def loads(xml_text: Union[str, bytes]) -> LoadedMaiml:
    """
    Parse MaiML XML text (or bytes) into a LoadedMaiml.

    xml_text is treated as untrusted input -- it may be a local file's
    contents today, but this is also the entry point a future API/upload
    surface would call directly, without necessarily running it through
    pymaiml.validation.validate() first. Parsing therefore explicitly
    disables external entity resolution and network access (see
    pymaiml._xml_security.make_untrusted_input_parser()) rather than
    relying on lxml's current defaults.
    """
    data = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
    root_el = _lxml_etree.fromstring(data, parser=make_untrusted_input_parser())

    xsi_type = root_el.get(f"{{{XSI_NS}}}type")
    namespaces = {
        prefix: uri
        for prefix, uri in root_el.nsmap.items()
        if prefix is not None and prefix != "xsi"
    }
    all_ids = [el.get("id") for el in root_el.iter() if el.get("id") is not None]

    document_el = _find(root_el, "document")
    document = _read_document(document_el)
    protocol_el = _find(root_el, "protocol")
    protocol = _read_protocol(protocol_el) if protocol_el is not None else None
    features = root_el.get("features")

    if xsi_type == "maimlRootType":
        data_el = _find(root_el, "data")
        event_log_el = _find(root_el, "eventLog")
        root_obj = m.MaimlRootType(
            document=document, protocol=protocol,
            data=_read_data(data_el), event_log=_read_event_log(event_log_el),
            features=features,
        )
    elif xsi_type == "protocolFileRootType":
        root_obj = m.ProtocolFileRootType(document=document, protocol=protocol, features=features)
    else:
        raise ValueError(
            f"Unknown maiml/@xsi:type: {xsi_type!r} (expected 'maimlRootType' or 'protocolFileRootType')"
        )

    return LoadedMaiml(root=root_obj, namespaces=namespaces, ids=all_ids)


def load(path: Union[str, Path]) -> LoadedMaiml:
    """Read `path` and parse it via loads()."""
    return loads(Path(path).read_bytes())
