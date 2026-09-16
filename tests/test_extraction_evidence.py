from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

import knowledge.knowledge_base.claim_evidence_records as evidence
import knowledge.knowledge_base.source_records as sources
from knowledge.document_processing.document_models import DocumentBlock, DocumentLocation
from knowledge.knowledge_domain.knowledge_record_models import Evidence, Reference


@pytest.fixture
def relation(article):
    payload = article.claim.model_dump(exclude={"proposition", "scope", "qualifications"})
    return Evidence(
        claim=Reference(entity_id=uuid4(), revision=1),
        source=Reference(entity_id=uuid4(), revision=1),
        **payload,
    )


@pytest.fixture
def ledger(article):
    ledger = Mock()
    ledger.require.return_value = SimpleNamespace(payload=article.source)
    ledger.list.return_value = []
    ledger.append.return_value = Reference(entity_id=uuid4(), revision=1)
    return ledger


def test_legacy_evidence_serialization_has_no_added_null_fields(relation):
    encoded = relation.model_dump(mode="json")
    assert "extraction_revision" not in encoded
    assert "block_id" not in encoded
    assert Evidence.model_validate_json(relation.model_dump_json()) == relation


@pytest.mark.parametrize("pin", [{"extraction_revision": 1}, {"block_id": "text"}])
def test_extraction_pins_must_be_supplied_together(relation, pin):
    with pytest.raises(ValidationError, match="both extraction_revision and block_id"):
        Evidence.model_validate({**relation.model_dump(), **pin})


def test_sources_without_snapshot_keep_legacy_quote_validation(ledger, relation, monkeypatch):
    monkeypatch.setattr(sources, "get_snapshot", lambda *args: None)
    evidence.link(ledger, "pilot", relation, "test")
    ledger.append.assert_called_once()


def test_unpinned_legacy_commands_keep_page_text_contract(ledger, relation, monkeypatch):
    monkeypatch.setattr(sources, "get_snapshot", lambda *args: SimpleNamespace(blocks=[]))
    evidence.link(ledger, "pilot", relation, "test")
    ledger.append.assert_called_once()


def test_pinned_quote_uses_exact_historical_snapshot(ledger, relation, monkeypatch):
    block = DocumentBlock(id="text", kind="text", page=1, text="Different extracted wording.")
    snapshot_reader = Mock(return_value=SimpleNamespace(blocks=[block]))
    monkeypatch.setattr(sources, "get_snapshot", snapshot_reader)
    pinned = relation.model_copy(
        update={
            "extraction_revision": 2,
            "block_id": "text",
            "quote": block.text,
        }
    )
    evidence.link(ledger, "pilot", pinned, "test")
    snapshot_reader.assert_called_once_with(ledger, relation.source, 2)
    ledger.append.assert_called_once()


@pytest.mark.parametrize(
    "change",
    [
        {"issues": ["OCR disagreement"]},
        {"kind": "table"},
        {"kind": "page_footer"},
        {"locations": [DocumentLocation(page=1), DocumentLocation(page=2)]},
        {"page": 2},
        {"text": "The claimed quote is missing."},
        {"id": "another-block"},
    ],
)
def test_unusable_or_mismatched_block_cannot_supply_evidence(
    ledger,
    relation,
    monkeypatch,
    change,
):
    block = DocumentBlock(id="text", kind="text", page=1, text=relation.quote)
    monkeypatch.setattr(
        sources,
        "get_snapshot",
        lambda *args: SimpleNamespace(
            blocks=[block.model_copy(update=change)],
        ),
    )
    pinned = relation.model_copy(update={"extraction_revision": 1, "block_id": "text"})
    with pytest.raises(ValueError):
        evidence.link(ledger, "pilot", pinned, "test")
    ledger.append.assert_not_called()


def test_deduplication_does_not_erase_extraction_revision(ledger, relation, monkeypatch):
    block = DocumentBlock(id="text", kind="text", page=1, text=relation.quote)
    monkeypatch.setattr(sources, "get_snapshot", lambda *args: SimpleNamespace(blocks=[block]))
    previous = relation.model_copy(update={"extraction_revision": 1, "block_id": "text"})
    previous_record = Mock(payload=previous)
    ledger.list.return_value = [previous_record]
    updated = relation.model_copy(update={"extraction_revision": 2, "block_id": "text"})
    evidence.link(ledger, "pilot", updated, "test")
    ledger.append.assert_called_once()
    ledger.append.reset_mock()
    evidence.link(ledger, "pilot", previous, "test")
    ledger.append.assert_not_called()
    previous_record.reference.assert_called_once()
