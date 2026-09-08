"""
pymaiml.validation
====================

Validates a MaiML (JIS K 0200 / MaiML-Schema-1_0) file against:

  1. The official XSD schema (well-formedness, element/attribute
     cardinality and order, id/IDREF resolvability, xsi:type <-> content
     model consistency, UUID string format, etc).
  2. Supplementary business rules from the MaiML AI Common Specification
     that XSD alone cannot express (ref-target element-type checks, the
     lifecycle "complete" event bookkeeping, XES namespace exact-URI
     binding, the "layer-1 elements must never be concealed by
     EncryptedData" rule, chain/parent structure, file extension/encoding
     conventions).

This is a library-friendly port of the same checks used by the
maiml-schema-validator Claude skill's validate_maiml.py, restructured
around a ValidationResult object instead of argparse + stdout, so any
Python code (a CI step, another pymaiml module, a notebook) can call it
directly:

    from pymaiml.validation import validate
    result = validate("sample.maiml")
    if not result.ok:
        for finding in result.errors:
            print(finding)

The official schema files (MaiML-Schema-1_0) are bundled under
pymaiml/schema/MaiML-Schema-1_0/ so validation works offline with zero
configuration; pass schema_dir= to point at a different schema version.

Known gap vs. the full JIS K 0200 specification (documented, not silently
skipped): XML digital signature cryptographic verification, full Petri-net
reachability simulation of the material->operation->result flow (the
"complete" event check here is a simplified file-wide presence check, not a
per-instruction trace), cross-file UUID consistency, and thesaurus
(Annex A/B) vocabulary conformance for key= values. See the skill's
reference/maiml_validation_rules.md for the full rationale if/when those
need porting too.
"""
from __future__ import annotations

import json as _json
import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

try:
    from lxml import etree
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "pymaiml.validation requires lxml. Install it with: "
        "pip install lxml"
    ) from exc

from ._xml_security import make_untrusted_input_parser

__all__ = ["Finding", "ValidationResult", "validate"]

_BUNDLED_SCHEMA_DIR = Path(__file__).resolve().parent / "schema" / "MaiML-Schema-1_0"

MAIML_NS = "http://www.maiml.org/schemas"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

XES_NS_EXPECTED = {
    "concept": "http://www.xes-standard.org/concept.xesext#",
    "lifecycle": "http://www.xes-standard.org/lifecycle.xesext#",
    "time": "http://www.xes-standard.org/time.xesext#",
}

Q = "{%s}" % MAIML_NS
QXSI = "{%s}" % XSI_NS

KNOWN_MAIML_FEATURES = {"nested-attributes"}

FORBIDDEN_ENCRYPTED_TAGS = {
    "maiml", "document", "protocol", "data", "eventLog",
    "Signature", "uuid", "creator", "vendor", "owner", "instrument", "date",
    "chain", "parent", "method", "pnml", "program", "instruction",
    "materialTemplate", "conditionTemplate", "resultTemplate",
    "place", "transition", "arc",
    "results", "material", "condition", "result",
    "log", "trace", "event",
}

REF_TARGET_RULES = {
    "placeRef": {"place"},
    "transitionRef": {"transition"},
    "vendorRef": {"vendor"},
    "instrumentRef": {"instrument"},
    "creatorRef": {"creator"},
    "ownerRef": {"owner"},
    "resultsRef": {"results"},
    "material": {"materialTemplate"},
    "condition": {"conditionTemplate"},
    "result": {"resultTemplate"},
    "log": {"method"},
    "trace": {"program"},
    "event": {"instruction"},
}

SAME_KIND_PARENT_RULES = {
    "templateRef": {
        "materialTemplate": {"materialTemplate"},
        "conditionTemplate": {"conditionTemplate"},
        "resultTemplate": {"resultTemplate"},
    },
    "instanceRef": {
        "material": {"material"},
        "condition": {"condition"},
        "result": {"result"},
    },
}

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-([1-5])[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)


def _local(tag) -> Optional[str]:
    if not isinstance(tag, str):
        return None
    return tag.split("}", 1)[-1] if "}" in tag else tag


@dataclass
class Finding:
    level: str  # "error" | "warning" | "info"
    code: str
    message: str
    line: Optional[int] = None

    def to_dict(self) -> dict:
        d = {"level": self.level, "code": self.code, "message": self.message}
        if self.line is not None:
            d["line"] = self.line
        return d

    def __str__(self) -> str:
        loc = f" (line {self.line})" if self.line is not None else ""
        return f"[{self.level.upper()}] {self.code}: {self.message}{loc}"


@dataclass
class ValidationResult:
    path: str
    findings: List[Finding] = field(default_factory=list)

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    @property
    def info(self) -> List[Finding]:
        return [f for f in self.findings if f.level == "info"]

    @property
    def ok(self) -> bool:
        """True iff there are no MUST-level (error) findings."""
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "file": self.path,
            "valid": self.ok,
            "errors": [f.to_dict() for f in self.errors],
            "warnings": [f.to_dict() for f in self.warnings],
            "info": [f.to_dict() for f in self.info],
        }

    def to_json(self, **kwargs) -> str:
        return _json.dumps(self.to_dict(), ensure_ascii=False, indent=2, **kwargs)

    def __str__(self) -> str:
        lines = [f"MaiML validation report: {self.path}", "=" * 60]
        lines.append("結果: OK（MUSTレベルのエラーはありません）" if self.ok else f"結果: NG（エラー {len(self.errors)} 件）")
        for label, items in (("エラー", self.errors), ("警告", self.warnings), ("参考情報", self.info)):
            if items:
                lines.append("")
                lines.append(f"--- {label} ({len(items)}) ---")
                lines.extend(f"  {f}" for f in items)
        return "\n".join(lines)


def _load_schema(schema_dir: Path):
    """
    Compile maiml.xsd -- and everything it <xs:import>s/<xs:include>s from
    the same schema_dir -- into an lxml XMLSchema.

    schema_dir is always either the bundled, trusted copy under
    pymaiml/schema/MaiML-Schema-1_0/, or an explicit schema_dir= a caller
    passed in to validate against a different schema *version*; it is
    never untrusted end-user MaiML content. This function deliberately
    does NOT go through _xml_security.make_untrusted_input_parser(): schema
    compilation needs ordinary local-file <xs:import>/<xs:include>
    resolution between the *.xsd files in schema_dir, which is expected,
    routine behaviour for a schema bundle -- not something to lock down
    the way arbitrary MaiML input is locked down in _xsd_validate() below.
    (no_network=True would not even conflict with this -- xs:import/
    xs:include here use relative filesystem paths, not network URLs -- but
    the two parser configurations are kept as separate, independently
    named code paths on purpose, so that hardening or loosening one can
    never silently affect the other.)
    """
    maiml_xsd = schema_dir / "maiml.xsd"
    if not maiml_xsd.is_file():
        raise FileNotFoundError(f"maiml.xsd not found under {schema_dir}")
    return etree.XMLSchema(etree.parse(str(maiml_xsd)))


def _extract_xml_bytes(path: Path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            candidates = [n for n in zf.namelist() if n.lower().endswith((".maiml", ".mai"))]
            if not candidates:
                raise ValueError("ZIP package contains no .maiml/.mai file")
            candidates.sort(key=lambda n: (n.count("/"), n))
            name = candidates[0]
            return zf.read(name), f"{path}!{name}"
    return path.read_bytes(), str(path)


def _check_file_extension(path: Path, findings: List[Finding]) -> None:
    lower = str(path).lower()
    if lower.endswith((".maiml.zip", ".maiml", ".mai")):
        return
    findings.append(Finding(
        "warning", "EXT-01",
        f"ファイル拡張子が MaiML の規定(.maiml / .maiml.zip / .mai)と異なります: {path.name} [仕様書 1.3]",
    ))


def _check_encoding_declaration(xml_bytes: bytes, findings: List[Finding]) -> None:
    m = re.match(rb"<\?xml[^>]*encoding=[\"']([^\"']+)[\"']", xml_bytes.lstrip()[:200])
    if m:
        enc = m.group(1).decode("ascii", "ignore").lower()
        if enc not in ("utf-8", "utf8"):
            findings.append(Finding(
                "warning", "ENC-01",
                f"XML宣言のencodingが UTF-8 ではありません(検出値: {enc})。MaiMLはUTF-8を規定しています [R-22]",
            ))


def _xsd_validate(xml_bytes: bytes, schema, findings: List[Finding]):
    # xml_bytes is untrusted MaiML input (a local file today; potentially an
    # uploaded file or an API request body in the future) -- see
    # _xml_security.make_untrusted_input_parser() for why resolve_entities/
    # no_network are pinned explicitly here, and _load_schema() above for
    # why the *schema* is compiled with a separate, unhardened parser.
    parser = make_untrusted_input_parser(remove_blank_text=False)
    try:
        doc = etree.fromstring(xml_bytes, parser=parser)
    except etree.XMLSyntaxError as e:
        findings.append(Finding("error", "XML-01", f"XMLとして整形式ではありません: {e}", line=e.lineno))
        return None
    tree = doc.getroottree()
    try:
        is_valid = schema.validate(doc)
    except etree.XMLSchemaValidateError as e:
        # A DOCTYPE-declared entity reference that resolve_entities=False
        # deliberately left unresolved (see _xml_security) can leave an
        # Entity node inside the tree that libxml2's schema validator
        # cannot walk -- it reports that as an "internal error" exception
        # instead of a normal validation failure. Treat it as just another
        # XSD violation rather than letting it escape as an uncaught
        # exception; either way the input is rejected.
        findings.append(Finding(
            "error", "XSD-02",
            "スキーマ検証中にエラーが発生しました。DOCTYPEで宣言されたエンティティ参照が"
            f"解決されないまま残っている可能性があります(このライブラリは外部エンティティ"
            f"を解決しません): {e}",
        ))
        return tree
    if not is_valid:
        for err in schema.error_log:
            findings.append(Finding("error", "XSD-01", err.message, line=err.line))
    return tree


def _build_id_index(root):
    idx = {}
    for el in root.iter(etree.Element):
        eid = el.get("id")
        if eid:
            idx[eid] = el
    return idx


def _check_ref_target_types(root, id_index, findings: List[Finding]) -> None:
    for el in root.iter(etree.Element):
        name = _local(el.tag)
        ref = el.get("ref")
        if not ref:
            continue
        target = id_index.get(ref)
        if target is None:
            findings.append(Finding(
                "error", "REF-01",
                f'<{name} ref="{ref}"> の参照先 id がファイル内に存在しません [4.2]',
                line=el.sourceline,
            ))
            continue
        target_name = _local(target.tag)
        if name in SAME_KIND_PARENT_RULES:
            parent = el.getparent()
            parent_name = _local(parent.tag) if parent is not None else None
            allowed = SAME_KIND_PARENT_RULES[name].get(parent_name)
            if allowed and target_name not in allowed:
                findings.append(Finding(
                    "error", "REF-02",
                    f'<{parent_name}> 内の <{name} ref="{ref}"> は同種の要素'
                    f"({'/'.join(sorted(allowed))}) を参照する必要がありますが、"
                    f"実際の参照先は <{target_name}> です [3.2.2 / 3.3.4]",
                    line=el.sourceline,
                ))
            continue
        if name in REF_TARGET_RULES:
            allowed = REF_TARGET_RULES[name]
            if target_name not in allowed:
                findings.append(Finding(
                    "error", "REF-03",
                    f'<{name} ref="{ref}"> は {"/".join(sorted(allowed))} 要素を参照する必要がありますが、'
                    f"実際の参照先は <{target_name}> です [4.2 / 5.1]",
                    line=el.sourceline,
                ))


def _get_property_value(el) -> Optional[str]:
    for child in el:
        if _local(child.tag) == "value":
            return (child.text or "").strip()
    return None


def _get_property_by_key(parent, key):
    for child in parent:
        if _local(child.tag) == "property" and child.get("key") == key:
            return child
    return None


def _check_event_completion(root, findings: List[Finding]) -> None:
    data_el = root.find(f"{Q}data")
    if data_el is None:
        return
    has_instance = any(_local(e.tag) in ("material", "condition", "result") for e in data_el.iter(etree.Element))
    if not has_instance:
        return
    event_log = root.find(f"{Q}eventLog")
    if event_log is None:
        findings.append(Finding(
            "error", "EVT-01",
            "<data> に計測結果が記録されていますが <eventLog> がありません。"
            "対応する <event> (lifecycle:transition=complete) の記述が必須です [3.5.5 R-A / R-16]",
        ))
        return
    found_complete = False
    for event in event_log.iter(f"{Q}event"):
        lc = _get_property_by_key(event, "lifecycle:transition")
        if lc is not None and _get_property_value(lc) == "complete":
            found_complete = True
            break
    if not found_complete:
        findings.append(Finding(
            "error", "EVT-02",
            '<data> に計測結果が記録されていますが、lifecycle:transition="complete" を持つ '
            "<event> が見つかりません [3.5.5 R-A / R-16]",
        ))


def _check_xes_namespaces(root, findings: List[Finding]) -> None:
    for el in root.iter(etree.Element):
        key = el.get("key")
        if not key or ":" not in key:
            continue
        prefix, _, _local_name = key.partition(":")
        if prefix not in XES_NS_EXPECTED:
            continue
        actual_uri = el.nsmap.get(prefix)
        expected_uri = XES_NS_EXPECTED[prefix]
        if actual_uri != expected_uri:
            findings.append(Finding(
                "error", "NS-01",
                f'key="{key}" のプレフィックス \'{prefix}:\' が XES 標準の名前空間 '
                f"({expected_uri}) に束縛されていません(現在: {actual_uri!r}) [3.5.3]",
                line=el.sourceline,
            ))


def _check_forbidden_encryption(root, findings: List[Finding]) -> None:
    for el in root.iter(etree.Element):
        name = _local(el.tag)
        if name not in FORBIDDEN_ENCRYPTED_TAGS:
            continue
        for child in el:
            if _local(child.tag) == "EncryptedData":
                findings.append(Finding(
                    "error", "ENCR-01",
                    f"<{name}> は秘匿禁止要素です。EncryptedData への置換は許可されていません [2.3]",
                    line=el.sourceline,
                ))


def _check_uuid_recommendations(root, findings: List[Finding]) -> None:
    for el in root.iter(etree.Element):
        name = _local(el.tag)
        uuid_child = next((c for c in el if _local(c.tag) == "uuid"), None)
        if uuid_child is None or not uuid_child.text:
            continue
        m = UUID_RE.match(uuid_child.text.strip())
        if not m:
            continue
        if name in ("creator", "vendor", "owner", "instrument") and m.group(1) == "4":
            findings.append(Finding(
                "info", "UUID-01",
                f"<{name}> の UUID がバージョン4(乱数)です。同一実体には常に同一UUIDを"
                "使うため、名前ベースのバージョン3/5を推奨します(必須ではありません) [3.1.1 S-01]",
                line=el.sourceline,
            ))


def _check_chain_parent(root, findings: List[Finding]) -> None:
    for tagname, code in (("chain", "CHN-01"), ("parent", "CHN-02")):
        for el in root.iter(f"{Q}{tagname}"):
            if el.find(f"{Q}uuid") is None or el.find(f"{Q}hash") is None:
                findings.append(Finding(
                    "error", code,
                    f"<{tagname}> には <uuid> と <hash> の両方が必須です [4.7/4.8 R-18/R-19]",
                    line=el.sourceline,
                ))


def _check_root_attributes(root, findings: List[Finding]) -> None:
    version = root.get("version")
    xsi_type = root.get(f"{QXSI}type")
    features = root.get("features")
    default_ns = root.nsmap.get(None)
    xsi_ns = root.nsmap.get("xsi")

    if default_ns != MAIML_NS:
        findings.append(Finding(
            "error", "ROOT-05",
            f'maiml のデフォルト名前空間(xmlns)は "{MAIML_NS}" 固定です(検出値: {default_ns!r}) [表12]',
        ))
    if xsi_ns != XSI_NS:
        findings.append(Finding(
            "error", "ROOT-06",
            f'maiml の xmlns:xsi は "{XSI_NS}" 固定です(検出値: {xsi_ns!r}) [表12]',
        ))
    if version != "1.0":
        findings.append(Finding("error", "ROOT-01", f'maiml/@version は "1.0" 固定です(検出値: {version!r})'))
    if features:
        unknown = [t for t in features.split() if t not in KNOWN_MAIML_FEATURES]
        if unknown:
            findings.append(Finding(
                "warning", "ROOT-07",
                f"maiml/@features に未知の値が含まれています: {unknown} "
                f"(現行仕様の既知値: {sorted(KNOWN_MAIML_FEATURES)}) [表12 注a)]",
            ))
    if not xsi_type:
        findings.append(Finding("error", "ROOT-02", "maiml 要素に xsi:type 属性がありません [R-01]"))
    elif xsi_type not in ("maimlRootType", "protocolFileRootType"):
        findings.append(Finding(
            "warning", "ROOT-03",
            f"maiml/@xsi:type が未知の値です: {xsi_type!r}(想定: maimlRootType / protocolFileRootType)",
        ))


def _run_supplementary_checks(tree, findings: List[Finding]) -> None:
    root = tree.getroot()
    if _local(root.tag) != "maiml":
        findings.append(Finding("error", "ROOT-04", f"ルート要素が <maiml> ではありません: <{_local(root.tag)}>"))
        return
    _check_root_attributes(root, findings)
    id_index = _build_id_index(root)
    _check_ref_target_types(root, id_index, findings)
    _check_event_completion(root, findings)
    _check_xes_namespaces(root, findings)
    _check_forbidden_encryption(root, findings)
    _check_uuid_recommendations(root, findings)
    _check_chain_parent(root, findings)


def validate(path: Union[str, Path], schema_dir: Optional[Union[str, Path]] = None) -> ValidationResult:
    """
    Validate a .maiml / .maiml.zip / .mai file.

    schema_dir defaults to the MaiML-Schema-1_0 bundled with pymaiml
    (pymaiml/schema/MaiML-Schema-1_0/). Pass a different directory to
    validate against another schema version.
    """
    path = Path(path)
    schema_dir = Path(schema_dir) if schema_dir is not None else _BUNDLED_SCHEMA_DIR
    findings: List[Finding] = []
    _check_file_extension(path, findings)

    try:
        xml_bytes, _display_name = _extract_xml_bytes(path)
    except Exception as e:
        findings.append(Finding("error", "IO-01", f"ファイルを読み込めません: {e}"))
        return ValidationResult(path=str(path), findings=findings)

    _check_encoding_declaration(xml_bytes, findings)
    schema = _load_schema(schema_dir)
    tree = _xsd_validate(xml_bytes, schema, findings)
    if tree is not None:
        _run_supplementary_checks(tree, findings)

    return ValidationResult(path=str(path), findings=findings)


def _main() -> None:  # pragma: no cover -- thin CLI wrapper
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Validate a MaiML file against MaiML-Schema-1_0.")
    ap.add_argument("file")
    ap.add_argument("--schema-dir", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.file):
        sys.stderr.write(f"File not found: {args.file}\n")
        sys.exit(2)

    result = validate(args.file, schema_dir=args.schema_dir)
    print(result.to_json() if args.json else str(result))
    sys.exit(0 if result.ok else 1)


if __name__ == "__main__":  # pragma: no cover
    _main()
