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

Known limitations (documented rather than silently guessed at):
  - <uncertainty> children of property/content are not modelled by
    maiml_domain yet, so they are never written.
  - EncryptionType's ``encrypted_data`` is stored (by maiml_domain) as a
    raw <xenc:EncryptedData> XML string; it is inserted into the tree
    as-is (must be well-formed and self-contained re: its own xmlns).
  - Reading MaiML XML back into maiml_domain objects (``loads``/``load``)
    is not implemented yet -- see the NotImplementedError raised below for
    the reasoning. Round-tripping an existing file currently requires a
    separate parse step outside pymaiml.
  - Custom key prefixes (e.g. "KYL:Cantilever", "ISO18115-3:Wavenumber")
    must have their namespace declared via ``extra_namespaces`` -- MaiML's
    key attributes are xs:QName, which XSD validation rejects if the
    prefix has no xmlns declaration in scope.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Union
from xml.dom import minidom
from xml.etree import ElementTree as ET

import maiml_domain as m

from ._xsi_registry import is_content_class, xsi_type_for

MAIML_NS = "http://www.maiml.org/schemas"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

__all__ = ["dumps", "dump", "loads", "load"]


# ---------------------------------------------------------------------------
# scalar value formatting
# ---------------------------------------------------------------------------

def _format_value(value, xsi_type: str) -> str:
    """Render a single Python value as MaiML XML text, per its xsi:type."""
    if isinstance(value, (bytes, bytearray)):
        if "hexBinary" in xsi_type:
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


def _write_property_or_content(parent_el: ET.Element, obj) -> ET.Element:
    """
    A propertyBaseType/contentBaseType instance:
      description? -> value? -> uncertainty*(unsupported) -> property* -> content*
    OR (xs:choice) an encryptionGroup payload.
    contentBaseType additionally carries axis/size/id/ref attributes.
    """
    xsi_type = xsi_type_for(obj)
    is_content = is_content_class(type(obj))
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

    # uncertainty*: not structurally modelled by maiml_domain -- skipped.

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
    instrument* -> date -> chain* -> parent*."""
    doc_el = ET.SubElement(parent_el, "document", {"id": doc.id})
    if doc.signature is not None:
        doc_el.append(ET.fromstring(doc.signature))
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
    """
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

    rough = ET.tostring(maiml_el, encoding="unicode")
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


def loads(xml_text: str):
    """
    Parse MaiML XML text back into a maiml_domain object tree.

    Not implemented yet: reconstructing the object graph correctly requires
    resolving id/IDREF relationships (e.g. deciding which MaterialType a
    <material ref="..."> instance points back to) and reversing the xsi:type
    dispatch for every property/content leaf, in a way that hasn't been
    exercised against real MaiML files yet. Raising loudly here rather than
    shipping an unverified implementation that looks like it works.
    """
    raise NotImplementedError(
        "pymaiml.serialization.loads() is not implemented yet -- writing "
        "MaiML XML (dumps/dump) is supported; reading it back into "
        "maiml_domain objects is planned but not built. See the module "
        "docstring."
    )


def load(path: Union[str, Path]):
    """Read `path` and parse it via loads(). See loads() for current status."""
    return loads(Path(path).read_text(encoding="utf-8"))
