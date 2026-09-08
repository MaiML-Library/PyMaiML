"""
pymaiml._xml_security
========================

A single, explicit place that answers "how does pymaiml configure an lxml
parser for XML it does not (yet) trust?" -- so that policy exists exactly
once, instead of being copied (and potentially drifting) between
pymaiml.validation and pymaiml.serialization, the two modules that parse
externally-supplied .maiml bytes.

"Untrusted" here means: XML whose *content* was not produced by this
process a moment ago -- a file path or bytes handed to
pymaiml.validation.validate() or pymaiml.serialization.loads()/load(),
whether the caller is a local script today or, in the future, an HTTP API
endpoint / an "upload a .maiml file" form. It does NOT include the
MaiML-Schema-1_0 *.xsd files bundled inside this package under
pymaiml/schema/MaiML-Schema-1_0/: those ship with pymaiml itself and
legitimately need <xs:import>/<xs:include> resolution between the local
schema files in that directory. See
pymaiml.validation._load_schema()'s own docstring for why that parser is
deliberately kept separate from the one built here.
"""
from __future__ import annotations

from lxml import etree


def make_untrusted_input_parser(*, remove_blank_text: bool = False) -> etree.XMLParser:
    """
    Build an lxml XMLParser configured for parsing untrusted MaiML XML.

    Pins two settings explicitly, rather than relying on whatever lxml's
    current defaults happen to be -- the point is to make "this library
    never resolves external entities or network resources when reading
    MaiML input" an explicit, auditable policy in the code, not an
    incidental side effect of a library default that could change:

      resolve_entities=False
        Never substitute the content of a general entity declared in the
        document's own DTD. Without this, a crafted document could (a)
        trigger "billion laughs"-style exponential entity expansion from a
        tiny input, or (b) declare an external entity that reads a local
        file or fetches a URL and smuggles the result into the parsed tree
        or into a validation error message (classic XXE).
      no_network=True
        Never let libxml2 fetch a DTD, external entity, or XInclude target
        over the network while parsing. This overlaps with
        resolve_entities=False for entities specifically, but also blocks
        other network-triggering constructs (e.g. XInclude), so it is kept
        as an independent, defense-in-depth setting rather than folded
        into "just disable entities."

    remove_blank_text is exposed because pymaiml.validation and
    pymaiml.serialization each parse for a different purpose (schema
    validation vs. building a maiml_domain tree) and may want it set
    differently; the two security-relevant settings above are never
    parameterized -- every untrusted-input parser this function builds
    has them fixed.
    """
    return etree.XMLParser(
        remove_blank_text=remove_blank_text,
        resolve_entities=False,
        no_network=True,
    )
