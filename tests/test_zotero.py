"""Zotero owns PDF bytes while source revisions preserve exact citation text."""

import hashlib

import pytest
from pydantic import ValidationError

import knowledge.knowledge_base.source_records as sources
import knowledge.literature.zotero_client as zotero
from knowledge.knowledge_domain.knowledge_record_models import LegacySource, Source, ZoteroReference
from knowledge.revision_store.postgresql_revision_store import decode_payload


def zotero_reference(pdf_hash):
    return ZoteroReference(
        server_id="test-instance",
        item_key="LITERAT1",
        original_attachment_key="ORIGINAL",
        original_sha256=pdf_hash,
        clean_attachment_key="CLEANPDF",
        clean_sha256=pdf_hash,
    )


def test_new_source_rejects_literature_metadata(article):
    legacy = article.source
    reference = zotero_reference(legacy.sha256)
    payload = legacy.model_dump(exclude={"bibliography", "original_path", "archive_path", "zotero"})
    source = Source(**payload, zotero=reference)
    assert "bibliography" not in source.model_dump()
    with pytest.raises(ValidationError):
        Source.model_validate({**payload, "zotero": reference, "bibliography": legacy.bibliography})
    assert isinstance(decode_payload("source", legacy.model_dump()), LegacySource)
    assert isinstance(decode_payload("source", source.model_dump()), Source)


def test_legacy_registration_rejected_without_records_or_receipt(application, article):
    with pytest.raises(ValueError, match="Legacy sources are read-only"):
        application.database.command(
            "legacy-source",
            "pilot",
            "register_source",
            article.source,
            "hermes:fixture",
            lambda ledger: [sources.register(ledger, "pilot", article.source, "hermes:fixture")],
        )
    with application.database.transaction() as ledger:
        assert ledger.list("pilot") == []
        assert ledger.get_receipt("legacy-source") is None


def test_verified_zotero_source_can_be_registered(application, article):
    source = Source(
        **article.source.model_dump(
            exclude={"bibliography", "original_path", "archive_path", "zotero"}
        ),
        zotero=zotero_reference(article.source.sha256),
    )
    with application.database.transaction() as ledger:
        reference = sources.register(ledger, "pilot", source, "hermes:fixture")
        assert ledger.get(reference.entity_id).payload == source


def test_attachment_replacement_invalidates_pdf_delivery(tmp_path, monkeypatch):
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"original PDF bytes")
    reference = zotero_reference(hashlib.sha256(pdf.read_bytes()).hexdigest())
    monkeypatch.setattr(zotero, "attachment_path", lambda *arguments: pdf)
    assert zotero.verified_pdf(reference, "original") == pdf
    pdf.write_bytes(b"replacement PDF bytes")
    with pytest.raises(ValueError, match="earlier version"):
        zotero.verified_pdf(reference, "original")


def test_bibliography_reads_current_zotero_metadata(monkeypatch):
    metadata = {"key": "LITERAT1", "title": "First title", "creators": []}
    monkeypatch.setattr(zotero, "item_data", lambda reference: metadata)
    reference = zotero_reference("a" * 64)
    assert zotero.get_bibliography(reference).title == "First title"
    metadata["title"] = "Corrected in Zotero"
    assert zotero.get_bibliography(reference).title == "Corrected in Zotero"


def test_old_citation_resolves_retained_attachment_after_new_pdf(article):
    from unittest.mock import Mock
    from uuid import uuid4

    from knowledge.knowledge_base.source_records import zotero_reference as resolve_reference

    legacy = article.source
    old_reference = zotero_reference(legacy.sha256)
    payload = legacy.model_dump(exclude={"bibliography", "original_path", "archive_path", "zotero"})
    migrated = Source(**payload, zotero=old_reference)
    replacement = migrated.model_copy(update={"sha256": "b" * 64})
    entity_id = uuid4()
    versions = {
        1: Mock(entity_id=entity_id, revision=1, payload=legacy),
        2: Mock(entity_id=entity_id, revision=2, payload=migrated),
        3: Mock(entity_id=entity_id, revision=3, payload=replacement),
    }
    ledger = Mock(get=lambda entity, revision=None: versions[revision or 3])
    assert resolve_reference(ledger, versions[1]) == old_reference


def test_storage_migration_preserves_review_but_source_changes_do_not(article):
    from unittest.mock import Mock

    from knowledge.knowledge_base.review_records import revision_is_current

    legacy = article.source
    reference = zotero_reference(legacy.sha256)
    payload = legacy.model_dump(exclude={"bibliography", "original_path", "archive_path", "zotero"})
    migrated = Source(**payload, zotero=reference)
    previous = Mock(revision=1, payload=legacy)
    current = Mock(revision=2, actor="migration:zotero-ownership-v1", payload=migrated)
    assert revision_is_current(previous, current)
    current.actor = "human:editor"
    assert not revision_is_current(previous, current)
    current.actor = "migration:zotero-ownership-v1"
    current.payload = migrated.model_copy(update={"pages": ["Changed evidence"]})
    assert not revision_is_current(previous, current)
    current.payload = migrated.model_copy(update={"study_group": "Different study"})
    assert not revision_is_current(previous, current)
    current.payload = migrated
    current.revision = 3
    assert not revision_is_current(previous, current)


def test_metadata_outage_is_visible_without_hiding_snapshot(article, monkeypatch):
    from unittest.mock import MagicMock, Mock
    from urllib.error import URLError

    from knowledge.web_interface.fastapi_app import source_description

    database = MagicMock()
    record = Mock(payload=article.source)
    monkeypatch.setattr(
        "knowledge.knowledge_base.source_records.zotero_reference",
        lambda ledger, record: object(),
    )
    monkeypatch.setattr(zotero, "get_bibliography", Mock(side_effect=URLError("offline")))
    description = source_description(record, database)
    assert description["title"] == "Zotero-Daten nicht verfügbar"
    assert "offline" in description["error"]
    assert "authors" not in description
