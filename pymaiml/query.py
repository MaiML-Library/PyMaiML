"""
pymaiml.query
==============

Independent, read-only "list the X used in this file" utilities over a
MaiML (JIS K 0200 / MaiML-Schema-1_0) document: every UUID, every
property/content/chain/parent key=, every declared namespace prefix, and
every external <insertion> file URI.

This module deliberately does NOT go through pymaiml.serialization.loads():
loads() requires the input to be fully schema-valid (maiml_domain's
constructors enforce cardinality and raise ValueError otherwise -- see
pymaiml.serialization's own "Known limitations"), and it reconstructs a
full maiml_domain object tree that does not itself carry namespace
declarations at all (those are an XML-level concept dumps() re-derives
from extra_namespaces=, not something any maiml_domain class stores).
The four functions here instead walk the parsed XML directly with a
handful of generic tag-name/attribute lookups (<uuid> text,
key= attributes, xmlns:* declarations, <insertion>/<uri> text) -- they
work even on a file that isn't schema-valid yet, which makes them useful
as a lightweight triage/inventory step before deciding whether (or how)
to fully load() a file, not just after.

Every function takes the same xml_text: Union[str, bytes] MaiML XML that
pymaiml.serialization.loads() takes (a str is UTF-8 encoded; pass
Path(...).read_bytes() for a file), and every function parses it with
pymaiml._xml_security.make_untrusted_input_parser() -- the exact same
XXE/entity-expansion/network-resource hardening loads() uses, since a
"just list what's in this file" utility is exactly the kind of thing that
gets pointed at untrusted/uploaded input.

get_keys() and get_insertion_uris() preserve first-appearance (document)
order and remove duplicates -- the second and later occurrences of an
already-seen value are dropped, not the first. This matters in practice:
MaiML-Schema-1_0 does not enforce key= uniqueness even within the same
parent element (see pymaiml/README.md), so recording the same key=
multiple times (e.g. a repeated measurement) is normal, and get_keys()
reports the distinct keys used, not one entry per occurrence.

get_uuids() is the exception: it returns every occurrence, in document
order, WITHOUT removing duplicates. A repeated key= or a repeated
insertion URI is unremarkable, but a uuid exists specifically to identify
one object uniquely, so the same uuid appearing more than once is itself
something worth being able to see -- silently collapsing it away would
hide exactly the kind of thing a caller may be using this function to
catch (e.g. via collections.Counter(get_uuids(xml_text)) or by comparing
len(get_uuids(xml_text)) to len(set(get_uuids(xml_text)))).
"""
from __future__ import annotations

from typing import Dict, List, Union

from lxml import etree

from ._xml_security import make_untrusted_input_parser

__all__ = ["get_uuids", "get_keys", "get_namespaces", "get_insertion_uris"]


def _local_name(tag) -> str:
    """Strip a lxml/Clark-notation {uri}localname tag down to localname."""
    if not isinstance(tag, str):
        return ""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _parse_root(xml_text: Union[str, bytes]):
    """Parse xml_text with the same untrusted-input hardening
    pymaiml.serialization.loads() uses, and return the root element."""
    data = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
    return etree.fromstring(data, parser=make_untrusted_input_parser())


def get_uuids(xml_text: Union[str, bytes]) -> List[str]:
    """
    Every <uuid> element's text in xml_text, in document order, INCLUDING
    duplicates -- unlike get_keys()/get_insertion_uris(), this does not
    deduplicate. A uuid is meant to uniquely identify one object, so a
    uuid that appears more than once is a fact about the file worth being
    able to observe (e.g. two distinct objects that were accidentally
    given the same identity), and deduplicating here would hide it. If you
    want the distinct set instead, wrap the result yourself, e.g.
    set(get_uuids(xml_text)) or list(dict.fromkeys(get_uuids(xml_text))).

    Walks the whole tree, so this includes every kind of <uuid> the
    schema uses this element name for: a globalObjectContentGroup's own
    identity uuid (document/creator/vendor/.../material/.../eventLog...),
    an <insertion>'s uuid (identifying the inserted external file, a
    distinct concept from the uuid of the object doing the inserting),
    and a <chain>/<parent>'s uuid. Returned as plain strings (not
    maiml_domain.Uuid) -- this module does not validate or otherwise
    depend on maiml_domain at all, so a file with a syntactically invalid
    uuid string is still listed rather than raising.
    """
    root = _parse_root(xml_text)
    return [
        el.text.strip()
        for el in root.iter()
        if _local_name(el.tag) == "uuid" and el.text and el.text.strip()
    ]


def get_keys(xml_text: Union[str, bytes]) -> List[str]:
    """
    Every key= attribute value in xml_text, in document order, with
    duplicates removed (first occurrence kept).

    Walks the whole tree and collects key= from whichever element carries
    it -- <property>, <content>, <chain>, and <parent> all do. MaiML-
    Schema-1_0 does not require key= to be unique, even within the same
    parent element (see pymaiml/README.md's note on this under
    pymaiml.builders.XsiTypeRegistry), so this is the set of distinct
    keys used, not a one-entry-per-occurrence list.
    """
    root = _parse_root(xml_text)
    values = [el.get("key") for el in root.iter() if el.get("key") is not None]
    return list(dict.fromkeys(values))


def get_namespaces(xml_text: Union[str, bytes]) -> Dict[str, str]:
    """
    Every custom xmlns:<prefix>="uri" declaration anywhere in xml_text, as
    {prefix: uri} (insertion order == first-appearance order, since a
    plain dict already preserves that).

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
    Every <insertion>/<uri> element's text in xml_text -- the external
    file references a globalObjectContentGroup's insertion* children
    record (see pymaiml.serialization._write_insertion/_read_insertion,
    and the maiml-data-merger skill's INSERTION attachment handling) -- in
    document order, with duplicates removed (first occurrence kept).
    """
    root = _parse_root(xml_text)
    values: List[str] = []
    for el in root.iter():
        if _local_name(el.tag) != "insertion":
            continue
        uri_el = next((c for c in el if _local_name(c.tag) == "uri"), None)
        if uri_el is not None and uri_el.text and uri_el.text.strip():
            values.append(uri_el.text.strip())
    return list(dict.fromkeys(values))
