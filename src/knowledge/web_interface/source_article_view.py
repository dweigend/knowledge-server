"""Compose source articles from Zotero, extraction snapshots, and knowledge records.

Presentation helpers derive citations, relationships, processing state, and safe
links without changing their underlying sources.
"""

import re
import subprocess
import tempfile
from html import escape, unescape
from pathlib import Path
from typing import Final
from urllib.error import URLError
from urllib.parse import quote, urlparse
from uuid import UUID

from markupsafe import Markup

from knowledge.document_processing import document_models
from knowledge.document_processing import extraction_store as document_extraction
from knowledge.knowledge_base import review_records as review
from knowledge.knowledge_base import source_records as sources
from knowledge.knowledge_domain import application_errors
from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.literature import zotero_client as zotero
from knowledge.literature import zotero_models
from knowledge.revision_store import postgresql_revision_store
from knowledge.web_interface import article_view_models as views

PREVIEW_DPI: Final[int] = 100
LABEL_CHARACTER_LIMIT: Final[int] = 160
RELATION_LABELS: Final[dict[str, str]] = {
    "supports": "stützt",
    "contradicts": "widerspricht",
    "qualifies": "schränkt ein",
    "unclear": "unklar",
}


def compose_article(
    database: postgresql_revision_store.Database,
    record: models.Record,
    extraction_revision: int | None = None,
) -> views.ArticleView:
    """Read an article without generating content or changing stored records."""
    with database.transaction() as ledger:
        snapshot = document_extraction.get_snapshot(ledger, record.reference(), extraction_revision)
        knowledge = related_knowledge(ledger, record)
        history = ledger.get(record.entity_id).revision
        processing = processing_state(ledger, record)
    if extraction_revision is not None and snapshot is None:
        raise application_errors.Missing("Requested extraction revision is unavailable")
    citation = read_source_citation(database, record)
    return {
        "record": record,
        "citation": citation,
        "snapshot": snapshot,
        "processing": processing,
        "blocks": present_blocks(record, snapshot),
        "relationships": present_relationships(snapshot),
        "outline": outline_entries(snapshot),
        "knowledge": knowledge,
        "history": range(1, history + 1),
        "zotero_url": citation.get("zotero_url", ""),
    }


def read_citation(reference: models.ZoteroReference) -> views.CitationView:
    """Distinguish unavailable Zotero service from absent metadata fields."""
    try:
        exported = zotero.article_citation(reference)
    except (URLError, OSError, ValueError) as error:
        return {"title": "Zotero-Daten nicht verfügbar", "error": str(error)}
    metadata = exported.data
    return {
        "title": metadata.title or "Titel in Zotero nicht angegeben",
        "authors": author_names(metadata.creators),
        "year": metadata.date,
        "venue": metadata.publicationTitle or metadata.bookTitle,
        "version": metadata.versionNumber or metadata.type,
        "doi_url": safe_web_url("https://doi.org/" + metadata.DOI) if metadata.DOI else "",
        "publisher_url": safe_web_url(metadata.url),
        "text": unescape(re.sub(r"<[^>]*>", "", exported.bib)).strip(),
        "bibtex": exported.bibtex,
        "metadata_revision": metadata.version if "version" in metadata.model_fields_set else None,
    }


def author_names(creators: list[zotero_models.Creator]) -> list[str]:
    """Use Zotero's author roles while preserving names and listed order."""
    return [
        creator.name or " ".join(filter(None, [creator.firstName, creator.lastName]))
        for creator in creators
        if creator.creatorType == "author"
    ]


def safe_web_url(address: str) -> str:
    """Allow document links only to explicit HTTP or HTTPS destinations."""
    parsed = urlparse(address)
    return address if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def zotero_item_url(library: str, item_key: str) -> str:
    """Link to the pinned library item without guessing author or publisher identities."""
    if library.startswith("groups/"):
        return f"zotero://select/groups/{quote(library.split('/')[1])}/items/{quote(item_key)}"
    return f"zotero://select/library/items/{quote(item_key)}"


def related_knowledge(
    ledger: postgresql_revision_store.Ledger,
    source_record: models.Record,
) -> list[views.KnowledgeEntry]:
    """Find knowledge linked to any retained revision of this source."""
    records = ledger.list(source_record.batch_id)
    direct_evidence = [
        record
        for record in records
        if isinstance(record.payload, models.Evidence)
        and record.payload.source.entity_id == source_record.entity_id
    ]
    claims = source_claims(ledger, direct_evidence, source_record)
    claim_references = [entry["record"].reference() for entry in claims]
    selected = list(direct_evidence)
    for record in records:
        payload = record.payload
        if isinstance(payload, models.Assessment) and payload.claim in claim_references:
            selected.append(record)
        if isinstance(payload, models.Note) and any(
            reference.entity_id == source_record.entity_id
            for reference in review.dependencies(ledger, record)
        ):
            selected.append(record)
    return [*claims, *[knowledge_entry(ledger, record, source_record) for record in selected]]


def knowledge_entry(
    ledger: postgresql_revision_store.Ledger,
    record: models.Record,
    source: models.Record,
) -> views.KnowledgeEntry:
    """Create a compact link while leaving full analysis on its existing record page."""
    title = record_title(record)
    if isinstance(record.payload, models.Assessment):
        claim = ledger.require(record.payload.claim, record.batch_id, "claim")
        title = "Bewertung: " + record_title(claim)
    return {"record": record, "title": title, "overview": eligible_overview(ledger, record, source)}


def source_claims(
    ledger: postgresql_revision_store.Ledger,
    records: list[models.Record],
    source_record: models.Record,
) -> list[views.KnowledgeEntry]:
    """Resolve claims through their evidence, preserving the claim revision actually cited."""
    claims = {}
    for record in records:
        evidence = record.payload
        if (
            not isinstance(evidence, models.Evidence)
            or evidence.source.entity_id != source_record.entity_id
        ):
            continue
        reference = evidence.claim
        key = (reference.entity_id, reference.revision)
        claims[key] = ledger.require(reference, source_record.batch_id, "claim")
    return [
        {"record": record, "title": record_title(record), "overview": False}
        for record in claims.values()
    ]


def record_title(record: models.Record) -> str:
    """Label existing knowledge with its domain content instead of internal identifiers."""
    payload = record.payload
    if isinstance(payload, models.Evidence):
        return f"Beleg auf Originalseite {payload.page} ({RELATION_LABELS[payload.relation]})"
    if isinstance(payload, models.Note):
        return payload.title
    if isinstance(payload, models.Claim):
        proposition = payload.proposition
        return (
            proposition
            if len(proposition) <= LABEL_CHARACTER_LIMIT
            else proposition[:LABEL_CHARACTER_LIMIT] + "…"
        )
    return "Bewertung"


def eligible_overview(
    ledger: postgresql_revision_store.Ledger,
    record: models.Record,
    source_record: models.Record,
) -> bool:
    """Require human review and source-specific evidence citations in every summary paragraph."""
    note = record.payload
    if not isinstance(note, models.Note) or note.kind != "source":
        return False
    if review.status(ledger, record) != "reviewed":
        return False
    evidence_tokens = set()
    for reference in note.references:
        payload = ledger.require(reference, record.batch_id).payload
        if isinstance(payload, models.Evidence) and payload.source == source_record.reference():
            evidence_tokens.add(f"[{reference.entity_id}@{reference.revision}]")
    paragraphs = [
        part for part in note.body.split("\n\n") if part.strip() and not part.startswith("#")
    ]
    return bool(paragraphs) and all(
        any(token in paragraph for token in evidence_tokens) for paragraph in paragraphs
    )


def present_blocks(
    record: models.Record,
    snapshot: document_models.DocumentSnapshot | None,
) -> list[views.BlockView]:
    """Derive presentation fields from the single stored block structure."""
    if snapshot is None:
        return []
    return [
        {
            "block": block,
            "heading_level": min(6, max(2, block.heading_level + 1)),
            "pdf_url": pdf_location(record, block.page, extraction_revision=snapshot.revision)
            if block.page
            else "",
            "html_text": linked_text(block, snapshot),
            "locations": [
                {
                    "page": location.page,
                    "url": pdf_location(
                        record, location.page, extraction_revision=snapshot.revision
                    ),
                }
                for location in block.locations
            ],
            "clean_url": pdf_location(
                record, snapshot.clean_pages[block.page], "clean", snapshot.revision
            )
            if block.page in snapshot.clean_pages
            else "",
            "table_rows": table_rows(block),
        }
        for block in snapshot.blocks
    ]


def table_rows(block: document_models.DocumentBlock) -> list[list[document_models.TableCell]]:
    """Keep merged cells in their original starting row and column order."""
    return [
        sorted([cell for cell in block.cells if cell.row == row], key=lambda cell: cell.column)
        for row in range(block.rows)
    ]


def pdf_location(
    record: models.Record,
    page: int,
    variant: str = "original",
    extraction_revision: int | None = None,
) -> str:
    """Link to a physical PDF page through the existing revision-pinned reader."""
    path = f"/sources/{record.entity_id}/{variant}/view?revision={record.revision}&page={page}"
    return path + (f"&extraction_revision={extraction_revision}" if extraction_revision else "")


def present_relationships(
    snapshot: document_models.DocumentSnapshot | None,
) -> list[views.RelationshipView]:
    """Resolve document relationships only against the same snapshot's block identities."""
    if snapshot is None:
        return []
    blocks = {block.id: block for block in snapshot.blocks}
    return [
        {
            "relationship": relationship,
            "origin": blocks.get(relationship.from_id),
            "target": blocks.get(relationship.to_id),
        }
        for relationship in snapshot.relationships
    ]


def preview_image(
    database: postgresql_revision_store.Database,
    entity_id: UUID,
    source_revision: int,
    block_id: str,
    extraction_revision: int,
) -> bytes:
    """Render an original PDF region on demand and remove all temporary image files."""
    with database.transaction() as ledger:
        record = ledger.get(entity_id, source_revision)
        snapshot = document_extraction.get_snapshot(ledger, record.reference(), extraction_revision)
    if snapshot is None:
        raise application_errors.Missing("Source has no structured extraction")
    block = next((block for block in snapshot.blocks if block.id == block_id), None)
    if block is None or block.page is None or block.kind not in {"figure", "picture", "table"}:
        raise application_errors.Missing("Unknown figure or table")
    pdf = zotero.verified_pdf(snapshot.zotero, "original")
    return render_region(pdf, block)


def render_region(pdf: Path, block: document_models.DocumentBlock) -> bytes:
    """Convert one pinned page or region with Poppler using top-left PDF-point coordinates."""
    arguments = ["pdftoppm", "-f", str(block.page), "-l", str(block.page), "-r", str(PREVIEW_DPI)]
    if block.region is not None:
        left, top, right, bottom = block.region
        pixels = [
            round(number * PREVIEW_DPI / 72) for number in (left, top, right - left, bottom - top)
        ]
        arguments.extend(
            flag
            for pair in zip(["-x", "-y", "-W", "-H"], map(str, pixels), strict=True)
            for flag in pair
        )
    with tempfile.TemporaryDirectory(prefix="knowledge-preview-") as directory:
        output = Path(directory) / "preview"
        subprocess.run(
            [*arguments, "-singlefile", "-png", str(pdf), str(output)],
            check=True,
            timeout=60,
            capture_output=True,
        )
        return output.with_suffix(".png").read_bytes()


def linked_text(
    block: document_models.DocumentBlock,
    snapshot: document_models.DocumentSnapshot,
) -> Markup:
    """Escape source prose and link only verified document citation relationships."""
    reference_ids = {candidate.id for candidate in snapshot.blocks if candidate.kind == "reference"}
    links = {
        link.text: link.to_id
        for link in snapshot.relationships
        if link.kind == "citation"
        and link.verified
        and link.from_id == block.id
        and link.to_id in reference_ids
        and link.text
    }
    if not links:
        return Markup(escape(block.text))
    pattern = (
        "(" + "|".join(re.escape(marker) for marker in sorted(links, key=len, reverse=True)) + ")"
    )
    parts = re.split(pattern, block.text)
    rendered = [citation_part(part, links) for part in parts]
    return Markup("".join(rendered))


def citation_part(text: str, links: dict[str, str]) -> str:
    """Render an exact marker once so document text cannot modify generated links."""
    if text not in links:
        return escape(text)
    target = escape(quote(links[text], safe=""), quote=True)
    return f'<a href="#block-{target}">{escape(text)}</a>'


def outline_entries(snapshot: document_models.DocumentSnapshot | None) -> list[views.OutlineEntry]:
    """Preserve the document's heading hierarchy using transient navigation entries."""
    outline: list[views.OutlineEntry] = []
    stack: list[tuple[int, list[views.OutlineEntry]]] = [(-1, outline)]
    if snapshot is None:
        return outline
    for block in snapshot.blocks:
        if block.kind not in {"heading", "section_header"}:
            continue
        while len(stack) > 1 and stack[-1][0] >= block.heading_level:
            stack.pop()
        entry: views.OutlineEntry = {"block": block, "children": []}
        stack[-1][1].append(entry)
        stack.append((block.heading_level, entry["children"]))
    return outline


def processing_state(
    ledger: postgresql_revision_store.Ledger,
    record: models.Record,
) -> views.ProcessingState | None:
    """Read the latest extraction job outcome for this exact source version."""
    row = ledger.connection.execute(
        "SELECT state,error FROM extraction_jobs WHERE source_id=%s AND source_revision=%s "
        "ORDER BY updated_at DESC LIMIT 1",
        (record.entity_id, record.revision),
    ).fetchone()
    return views.ProcessingState.model_validate(row) if row is not None else None


def read_source_citation(
    database: postgresql_revision_store.Database,
    record: models.Record,
) -> views.CitationView:
    """Keep historical text readable when its original Zotero identity cannot be resolved."""
    try:
        with database.transaction() as ledger:
            reference = sources.zotero_reference(ledger, record)
    except ValueError as error:
        return {"title": "Zotero-Zuordnung nicht verfügbar", "error": str(error)}
    citation = read_citation(reference)
    citation["zotero_url"] = zotero_item_url(reference.library, reference.item_key)
    return citation
