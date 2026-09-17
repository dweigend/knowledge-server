from collections.abc import Iterator
from pathlib import Path
from typing import Never, cast
from urllib.error import URLError
from uuid import uuid4

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

import knowledge.literature.zotero_client as zotero
import knowledge.web_interface.source_article_view as source_view
from knowledge.document_processing.document_models import (
    DocumentBlock,
    DocumentRelationship,
    DocumentSnapshot,
    TableCell,
)
from knowledge.knowledge_domain.knowledge_record_models import Record, Source, ZoteroReference
from knowledge.literature.zotero_models import Item
from knowledge.revision_store.postgresql_revision_store import Database, Ledger
from knowledge.web_interface.fastapi_app import citation_links


@pytest.fixture
def source_record() -> Record:
    zotero_reference = ZoteroReference(
        server_id="test-instance",
        item_key="LITERAT1",
        original_attachment_key="ORIGINAL",
        original_sha256="a" * 64,
        clean_attachment_key="CLEANPDF",
        clean_sha256="b" * 64,
    )
    return Record(
        entity_id=uuid4(),
        revision=2,
        batch_id="pilot",
        kind="source",
        actor="test",
        created_at="2026-09-15",
        payload=Source(
            zotero=zotero_reference,
            sha256="a" * 64,
            pages=["Historical quote"],
            extraction_method="historical",
            extraction_warnings=[],
            study_group="test",
            overlap="unknown",
        ),
    )


@pytest.fixture
def snapshot(source_record: Record) -> DocumentSnapshot:
    assert isinstance(source_record.payload, Source)
    return DocumentSnapshot(
        source=source_record.reference(),
        zotero=source_record.payload.zotero,
        pdf_sha256="a" * 64,
        revision=3,
        method="fixture",
        page_sizes={2: (600, 800)},
        clean_pages={2: 1},
        blocks=[
            DocumentBlock(id="section", kind="heading", text="Results", heading_level=1, page=2),
            DocumentBlock(
                id="table",
                kind="table",
                page=2,
                rows=2,
                columns=2,
                region=(10, 20, 100, 200),
                label="Table 1",
                caption="Measured values",
                footnote_ids=["footnote"],
                cells=[
                    TableCell(row=0, column=0, column_span=2, text="Group", header=True),
                    TableCell(row=1, column=0, text="71"),
                    TableCell(row=1, column=1, text="29"),
                ],
                issues=["Unit comparison unresolved"],
            ),
            DocumentBlock(id="footnote", kind="footnote", page=2, text="1 Percent, not counts."),
            DocumentBlock(id="prose", kind="text", page=2, text="<script>bad()</script> [1]"),
            DocumentBlock(id="ref-1", kind="reference", page=2, text="Original reference"),
        ],
        relationships=[
            DocumentRelationship(
                kind="citation",
                from_id="prose",
                to_id="ref-1",
                text="[1]",
                verified=True,
            )
        ],
    )


def test_structured_table_keeps_spans_footnotes_and_pinned_locations(
    source_record: Record, snapshot: DocumentSnapshot
) -> None:
    blocks = source_view.present_blocks(source_record, snapshot)
    table = blocks[1]
    assert table.table_rows[0][0].column_span == 2
    assert [cell.text for cell in table.table_rows[1]] == ["71", "29"]
    assert "revision=2&page=2" in table.pdf_url
    assert "/clean/view?revision=2&page=1" in table.clean_url
    assert table.block.footnote_ids == ["footnote"]


def test_document_content_is_escaped_and_only_verified_markers_link(
    snapshot: DocumentSnapshot,
) -> None:
    rendered = str(source_view.linked_text(snapshot.blocks[3], snapshot))
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert '<a href="#block-ref-1">[1]</a>' in rendered
    snapshot.relationships[0].verified = False
    assert "<a " not in source_view.linked_text(snapshot.blocks[3], snapshot)


def test_citation_uses_zotero_exports_and_rejects_unsafe_publisher_links(
    monkeypatch: pytest.MonkeyPatch, source_record: Record
) -> None:
    monkeypatch.setattr(
        zotero,
        "article_citation",
        lambda reference: Item.model_validate(
            {
                "data": {
                    "title": "Working paper",
                    "url": "javascript:alert(1)",
                    "creators": [
                        {"creatorType": "author", "firstName": "A", "lastName": "Writer"},
                        {"creatorType": "editor", "name": "Editor"},
                    ],
                },
                "bib": "<div>A Writer. <i>Working paper.</i></div>",
                "bibtex": "@misc{working}",
            }
        ),
    )
    assert isinstance(source_record.payload, Source)
    citation = source_view.read_citation(source_record.payload.zotero)
    assert citation.text == "A Writer. Working paper."
    assert citation.authors == ["A Writer"]
    assert citation.publisher_url == ""
    assert citation.bibtex == "@misc{working}"
    assert citation.year == ""
    assert "error" not in citation


def test_citation_reports_service_failure_without_substituting_metadata(
    monkeypatch: pytest.MonkeyPatch, source_record: Record
) -> None:
    def unavailable(reference: ZoteroReference) -> Never:
        raise URLError("offline")

    monkeypatch.setattr(zotero, "article_citation", unavailable)
    assert isinstance(source_record.payload, Source)
    citation = source_view.read_citation(source_record.payload.zotero)
    assert "offline" in citation.error
    assert "bibtex" not in citation


def test_article_template_preserves_structure_and_unresolved_quality(
    source_record: Record, snapshot: DocumentSnapshot
) -> None:
    environment = Environment(
        loader=FileSystemLoader(Path(source_view.__file__).with_name("templates")),
        autoescape=select_autoescape(["html"]),
    )
    environment.filters["citation_links"] = citation_links
    document = environment.get_template("article.html").render(
        record=source_record,
        citation={"title": "<unsafe>", "text": "Citation", "bibtex": "@misc{test}"},
        snapshot=snapshot,
        blocks=source_view.present_blocks(source_record, snapshot),
        relationships=source_view.present_relationships(snapshot),
        knowledge=[],
        history=[1, 2],
        zotero_url="zotero://select/library/items/LITERAT1",
    )
    assert "<h1>&lt;unsafe&gt;</h1>" in document
    assert 'colspan="2"' in document
    assert 'href="#block-footnote"' in document
    assert "Unit comparison unresolved" in document
    assert "extraction_revision=3" in document
    assert "Keine" not in document.split('<h2 id="references-heading">')[1].split("</ol>")[0]
    assert "Originalabstract" in document
    assert "KI-Kurzfassung" in document
    assert "Historischer Zitattext" in document
    assert "<script>bad()" not in document


def test_unknown_page_mapping_does_not_guess_clean_pdf_page(
    source_record: Record, snapshot: DocumentSnapshot
) -> None:
    snapshot.clean_pages = {}
    assert not source_view.present_blocks(source_record, snapshot)[1].clean_url


def test_preview_uses_original_hash_checked_pdf_and_discards_temporary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "original.pdf"
    seen = []

    def render(arguments: list[str], **options: object) -> None:
        seen.append(arguments)
        Path(arguments[-1] + ".png").write_bytes(b"PNG-preview")

    monkeypatch.setattr(source_view.subprocess, "run", render)
    block = DocumentBlock(id="figure", kind="figure", page=2, region=(72, 144, 216, 288))
    assert source_view.render_region(pdf, block) == b"PNG-preview"
    arguments = seen[0]
    assert arguments[arguments.index("-x") + 1] == "100"
    assert arguments[arguments.index("-y") + 1] == "200"
    assert arguments[arguments.index("-W") + 1] == "200"
    assert not Path(arguments[-1]).parent.exists()


def test_source_route_reads_without_models_or_knowledge_writes(
    monkeypatch: pytest.MonkeyPatch,
    source_record: Record,
    snapshot: DocumentSnapshot,
    tmp_path: Path,
) -> None:
    from contextlib import contextmanager
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    import knowledge.document_processing.extraction_store as document_extraction
    import knowledge.model_integration.structured_generation as generation
    from knowledge.revision_store.postgresql_revision_store import Database
    from knowledge.runtime_support.environment_settings import Settings
    from knowledge.web_interface.fastapi_app import create_app

    queries = []

    def execute(query: str, parameters: object) -> SimpleNamespace:
        queries.append(query)
        assert query.startswith("SELECT ")
        return SimpleNamespace(fetchone=lambda: None)

    ledger = SimpleNamespace(
        get=lambda entity_id, revision=None: source_record,
        list=lambda batch: [],
        connection=SimpleNamespace(execute=execute),
    )

    @contextmanager
    def transaction(self: Database) -> Iterator[SimpleNamespace]:
        yield ledger

    def model_forbidden(*args: object, **kwargs: object) -> Never:
        raise AssertionError("Reading must not call a model")

    monkeypatch.setattr(Database, "transaction", transaction)
    monkeypatch.setattr(generation, "generate", model_forbidden)
    monkeypatch.setattr(document_extraction, "get_snapshot", lambda *args: snapshot)
    monkeypatch.setattr(
        zotero,
        "article_citation",
        lambda reference: Item.model_validate(
            {
                "data": {"title": "Article title"},
                "bib": "Source citation",
                "bibtex": "@misc{source}",
            }
        ),
    )
    client = TestClient(create_app(Settings(database_url="unused", archive_root=tmp_path)))
    response = client.get(f"/records/{source_record.entity_id}?revision=2&extraction_revision=3")
    assert response.status_code == 200
    assert "Article title" in response.text
    assert "source ·" not in response.text
    assert queries


def test_outline_keeps_nested_headings(snapshot: DocumentSnapshot) -> None:
    snapshot.blocks = [
        DocumentBlock(id="a", kind="heading", text="A", heading_level=1),
        DocumentBlock(id="a1", kind="heading", text="A.1", heading_level=2),
        DocumentBlock(id="b", kind="heading", text="B", heading_level=1),
    ]
    outline = source_view.outline_entries(snapshot)
    assert [entry.block.id for entry in outline] == ["a", "b"]
    assert outline[0].children[0].block.id == "a1"


def test_claim_links_use_the_evidence_claim_revision(
    source_record: Record, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from knowledge.knowledge_domain.knowledge_record_models import Claim, Evidence

    claim = source_record.model_copy(
        update={
            "entity_id": uuid4(),
            "revision": 1,
            "kind": "claim",
            "payload": Claim(
                proposition="Measured result", scope="Study", qualifications="Limited"
            ),
        }
    )
    relation = source_record.model_copy(
        update={
            "entity_id": uuid4(),
            "kind": "evidence",
            "payload": Evidence(
                claim=claim.reference(),
                source=source_record.reference(),
                page=1,
                quote="Historical quote",
                relation="supports",
                rationale="Measured result",
                directness="direct",
                methodology="Study",
                limitations="Limited",
            ),
        }
    )
    ledger = SimpleNamespace(require=lambda reference, batch, kind: claim)
    links = source_view.source_claims(cast(Ledger, ledger), [relation], source_record)
    assert links[0].record.reference() == claim.reference()
    assert links[0].title == "Measured result"


def test_unresolved_historical_zotero_identity_keeps_readable_error(
    monkeypatch: pytest.MonkeyPatch, source_record: Record
) -> None:
    from contextlib import contextmanager
    from types import SimpleNamespace

    import knowledge.knowledge_base.source_records as sources

    @contextmanager
    def transaction() -> Iterator[object]:
        yield object()

    def unresolved(ledger: Ledger, record: Record) -> None:
        raise ValueError("Historical PDF version has no verified Zotero reference")

    monkeypatch.setattr(sources, "zotero_reference", unresolved)
    citation = source_view.read_source_citation(
        cast(Database, SimpleNamespace(transaction=transaction)), source_record
    )
    assert "Historical PDF" in citation.error
    assert "zotero_url" not in citation


def test_related_knowledge_excludes_other_sources_evidence_and_keeps_labels_compact(
    source_record: Record,
) -> None:
    from types import SimpleNamespace

    from knowledge.knowledge_domain.knowledge_record_models import Assessment, Claim, Evidence

    claim = source_record.model_copy(
        update={
            "entity_id": uuid4(),
            "kind": "claim",
            "payload": Claim(
                proposition="A long proposition " * 20, scope="Study", qualifications="Limited"
            ),
        }
    )
    evidence = source_record.model_copy(
        update={
            "entity_id": uuid4(),
            "kind": "evidence",
            "payload": Evidence(
                claim=claim.reference(),
                source=source_record.reference(),
                page=2,
                quote="Historical quote",
                relation="supports",
                rationale="Long rationale " * 100,
                directness="direct",
                methodology="Study",
                limitations="Limited",
            ),
        }
    )
    foreign_evidence = evidence.model_copy(
        update={
            "entity_id": uuid4(),
            "payload": evidence.payload.model_copy(
                update={
                    "source": source_record.reference().model_copy(update={"entity_id": uuid4()}),
                }
            ),
        }
    )
    assessment = source_record.model_copy(
        update={
            "entity_id": uuid4(),
            "kind": "assessment",
            "payload": Assessment(
                claim=claim.reference(),
                evidence=[evidence.reference(), foreign_evidence.reference()],
                balance="mostly_supported",
                confidence="low",
                rationale="Long rationale " * 100,
                coverage="Two sources",
                limitations="Limited",
            ),
        }
    )
    records = [claim, evidence, foreign_evidence, assessment]
    ledger = cast(Ledger, SimpleNamespace(list=lambda batch: records, require=lambda *args: claim))
    related = source_view.related_knowledge(ledger, source_record)
    assert {entry.record.entity_id for entry in related} == {
        claim.entity_id,
        evidence.entity_id,
        assessment.entity_id,
    }
    labels = {entry.record.kind: entry.title for entry in related}
    assert labels["evidence"] == "Beleg auf Originalseite 2 (stützt)"
    assert labels["assessment"].startswith("Bewertung: ")
    assert max(map(len, labels.values())) <= 172
    assert all("Long rationale" not in title for title in labels.values())
