"""Translate GROBID TEI into provider-neutral paper records.

The parser preserves bibliography, citation context, sections, tables, and source
limitations without fabricating missing spans.
"""

import re
from collections import Counter
from typing import Final
from xml.etree import ElementTree as ET

from knowledge.literature import structured_paper_models as papers

NS: Final[dict[str, str]] = {"tei": "http://www.tei-c.org/ns/1.0"}
XML_ID: Final[str] = "{http://www.w3.org/XML/1998/namespace}id"
MAX_TEI_BYTES: Final[int] = 32 * 1024 * 1024


def element_text(element: ET.Element | None) -> str:
    """Read all mixed XML content with ordinary word spacing."""
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def bibliography_metadata(element: ET.Element) -> papers.PaperMetadata:
    """Read a TEI bibliographic description with article and book fallbacks."""
    analytic = element.find("tei:analytic", NS)
    primary = analytic if analytic is not None else element.find("tei:monogr", NS)
    if primary is None:
        primary = element
    authors = [
        " ".join(part.strip() for part in author.itertext() if part.strip())
        for author in primary.findall("tei:author/tei:persName", NS)
    ]
    date = element.find(".//tei:date", NS)
    date_text = date.get("when", element_text(date)) if date is not None else ""
    year = re.search(r"\b\d{4}\b", date_text)
    doi = next(
        (
            element_text(node)
            for node in element.findall(".//tei:idno", NS)
            if node.get("type", "").lower() == "doi"
        ),
        None,
    )
    venue = element_text(element.find("tei:monogr/tei:title", NS)) if analytic is not None else ""
    return papers.PaperMetadata(
        title=element_text(primary.find("tei:title", NS)) or None,
        authors=authors,
        year=year.group() if year else None,
        venue=venue or None,
        doi=doi,
    )


def paper_metadata(root: ET.Element) -> papers.PaperMetadata:
    """Read paper metadata from its source description and title statement."""
    source = root.find("tei:teiHeader/tei:fileDesc/tei:sourceDesc/tei:biblStruct", NS)
    metadata = bibliography_metadata(source) if source is not None else papers.PaperMetadata()
    if not metadata.title:
        metadata.title = (
            element_text(root.find("tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", NS))
            or None
        )
    return metadata


def paper_references(root: ET.Element) -> list[papers.PaperReference]:
    """Read each bibliography record, keeping raw citations when supplied."""
    references = []
    entries = [
        entry
        for bibliography in root.findall(".//tei:listBibl", NS)
        for entry in bibliography
        if entry.tag.rsplit("}", 1)[-1] in {"biblStruct", "bibl"}
    ]
    for index, entry in enumerate(entries):
        references.append(
            papers.PaperReference(
                **bibliography_metadata(entry).model_dump(),
                id=entry.get(XML_ID) or f"unidentified-reference-{index + 1}",
                raw=(
                    element_text(entry.find("tei:note[@type='raw_reference']", NS))
                    or (element_text(entry) if entry.tag.endswith("}bibl") else None)
                ),
            )
        )
    return references


def paper_citations(
    root: ET.Element, references: list[papers.PaperReference]
) -> list[papers.PaperCitation]:
    """Resolve local bibliography targets while preserving unresolved markers."""
    reference_counts = Counter(reference.id for reference in references)
    known_ids = {reference_id for reference_id, count in reference_counts.items() if count == 1}
    citations = []
    parents = {child: parent for parent in root.iter() for child in parent}
    for marker in root.findall(".//tei:text//tei:ref[@type='bibr']", NS):
        targets = marker.get("target", "").split()
        target_ids = [target.removeprefix("#") for target in targets]
        citations.append(
            papers.PaperCitation(
                marker=element_text(marker),
                context=citation_context(marker, parents),
                section=citation_section(marker, parents),
                target_ids=target_ids,
                resolved=bool(targets)
                and all(target.startswith("#") and target[1:] in known_ids for target in targets),
                coordinates=marker.get("coords"),
            )
        )
    return citations


def citation_context(marker: ET.Element, parents: dict[ET.Element, ET.Element]) -> str:
    """Retain the surrounding paragraph excerpt for the specific citation occurrence."""
    container = marker
    while container in parents:
        container = parents[container]
        if container.tag.rsplit("}", 1)[-1] in {"p", "note", "item", "cell", "figDesc"}:
            break
        if container.tag.endswith("}div"):
            break
    text = element_text(container)
    before, _ = text_before_marker(container, marker)
    position = len(" ".join(before.split()))
    start = max(0, position - 400)
    end = min(len(text), position + len(element_text(marker)) + 400)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def text_before_marker(container: ET.Element, marker: ET.Element) -> tuple[str, bool]:
    """Collect mixed text before an exact XML element, including repeated markers."""
    if container is marker:
        return "", True
    text = container.text or ""
    for child in container:
        prefix, found = text_before_marker(child, marker)
        text += prefix
        if found:
            return text, True
        text += child.tail or ""
    return text, False


def citation_section(marker: ET.Element, parents: dict[ET.Element, ET.Element]) -> str | None:
    """Find the nearest containing section heading without inventing a page number."""
    container = marker
    while container in parents:
        container = parents[container]
        head = container.find("tei:head", NS)
        if head is not None:
            return element_text(head) or None
    return None


def table_markdown(element: ET.Element) -> str:
    """Represent available table cells without assuming a detected header row."""
    rows = [
        [element_text(cell).replace("|", "\\|") for cell in row.findall("tei:cell", NS)]
        for row in element.findall("tei:row", NS)
    ]
    if not rows:
        return element_text(element)
    width = max(map(len, rows))
    header = "| " + " | ".join([""] * width) + " |"
    separator = "| " + " | ".join(["---"] * width) + " |"
    body = ["| " + " | ".join(row + [""] * (width - len(row))) + " |" for row in rows]
    return "\n".join([header, separator, *body])


def block_markdown(element: ET.Element, level: int = 2) -> str:
    """Render TEI blocks recursively and retain text from unsupported elements."""
    tag = element.tag.rsplit("}", 1)[-1]
    content = element_text(element)
    if tag == "head":
        number = element.get("n", "")
        return f"{'#' * min(level, 6)} {number + ' ' if number else ''}{content}"
    if tag == "table":
        return table_markdown(element)
    if tag == "list":
        return "\n".join(f"- {element_text(item)}" for item in element.findall("tei:item", NS))
    if tag in {"p", "formula", "figDesc", "note", "item"} or not len(element):
        return content
    pieces = [element.text.strip()] if element.text and element.text.strip() else []
    for child in element:
        child_level = level + 1 if tag == "div" and child.tag.endswith("}div") else level
        pieces.append(block_markdown(child, child_level))
        if child.tail and child.tail.strip():
            pieces.append(child.tail.strip())
    return "\n\n".join(piece for piece in pieces if piece)


def document_markdown(
    root: ET.Element,
    metadata: papers.PaperMetadata,
    references: list[papers.PaperReference],
) -> str:
    """Assemble the paper body, abstract, back matter and bibliography once."""
    pieces = [f"# {metadata.title}"] if metadata.title else []
    abstract = root.find("tei:teiHeader/tei:profileDesc/tei:abstract", NS)
    if abstract is not None:
        pieces.extend(["## Abstract", block_markdown(abstract)])
    text = root.find("tei:text", NS)
    assert text is not None
    for region in text:
        if region.tag == f"{{{NS['tei']}}}back":
            # Bibliography is rendered from its structured records below.
            for parent in region.iter():
                for child in list(parent):
                    if child.tag == f"{{{NS['tei']}}}listBibl":
                        parent.remove(child)
        pieces.append(block_markdown(region))
    if references:
        pieces.append("## References")
        for reference in references:
            description = reference.raw or ". ".join(
                filter(
                    None,
                    [
                        ", ".join(reference.authors),
                        reference.title,
                        reference.venue,
                        reference.year,
                        f"doi:{reference.doi}" if reference.doi else None,
                    ],
                )
            )
            pieces.append(f"- [{reference.id}] {description or 'Unparsed reference'}")
    return "\n\n".join(piece for piece in pieces if piece).strip() + "\n"


def parse_paper_tei(raw_tei: str) -> papers.PaperDocument:
    """Validate TEI and extract normalized document structure and bibliography."""
    if len(raw_tei.encode("utf-8")) > MAX_TEI_BYTES:
        raise ValueError("GROBID response exceeds the 32 MiB TEI limit")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", raw_tei, re.IGNORECASE):
        raise ValueError("GROBID TEI must not contain DTD or entity declarations")
    try:
        root = ET.fromstring(raw_tei)
    except ET.ParseError as error:
        raise ValueError("GROBID returned malformed TEI XML") from error
    body = root.find("tei:text/tei:body", NS)
    if root.tag != f"{{{NS['tei']}}}TEI" or body is None or not element_text(body):
        raise ValueError("GROBID response must contain a non-empty TEI document body")
    metadata = paper_metadata(root)
    references = paper_references(root)
    citations = paper_citations(root, references)
    sections = [
        papers.PaperSection(title=element_text(head), coordinates=head.get("coords"))
        for head in body.findall(".//tei:head", NS)
    ]
    application = root.find("tei:teiHeader/tei:encodingDesc/tei:appInfo/tei:application", NS)
    warnings = extraction_warnings(metadata, references, citations)
    return papers.PaperDocument(
        markdown=document_markdown(root, metadata, references),
        metadata=metadata,
        references=references,
        citations=citations,
        sections=sections,
        warnings=warnings,
        provider="grobid",
        provider_version=application.get("version") if application is not None else None,
        raw_document=raw_tei,
    )


def extraction_warnings(
    metadata: papers.PaperMetadata,
    references: list[papers.PaperReference],
    citations: list[papers.PaperCitation],
) -> list[str]:
    """Report missing metadata and unresolved extraction without asserting completeness."""
    missing = [
        name for name in ("title", "authors", "year", "venue", "doi") if not getattr(metadata, name)
    ]
    warnings = [f"Missing document metadata: {', '.join(missing)}."] if missing else []
    if len({reference.id for reference in references}) != len(references):
        warnings.append(
            "Duplicate bibliography identifiers; affected citation targets are unresolved."
        )
    if not references:
        warnings.append("No bibliography entries extracted; check the original PDF.")
    unresolved = sum(not citation.resolved for citation in citations)
    if unresolved:
        warnings.append(f"{unresolved} citation marker(s) have unresolved bibliography targets.")
    warnings.append(
        "Structured text is normalized; PDF page text remains the exact quotation source."
    )
    return warnings
