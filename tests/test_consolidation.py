import json
from uuid import uuid4

import pytest
from support import seed_article

from knowledge.application import EditNote, ReviewCommand
from knowledge.consolidation import (
    ConsolidateNote,
    NoteRevision,
    apply_note_revision,
    note_context,
    note_packet,
    propose_note_revision,
)
from knowledge.contracts import Note, Reference
from knowledge.import_workflow import PAGE_BUDGET, page_chunks
from knowledge.reconciliation import (
    ClaimDecision,
    ReconcileClaim,
    apply_claim_decision,
    validate_decision,
)


@pytest.fixture
def imported(application, article):
    references = seed_article(application, "seed", article)
    return dict(
        zip(("source", "claim", "evidence", "source_note", "zettel"), references, strict=True)
    )


def reconcile(application, source, proposal, decision, request_id):
    command = ReconcileClaim(source=source, proposal=proposal, decision=decision)
    return application.database.command(
        request_id,
        "pilot",
        "reconcile",
        command,
        "hermes:test",
        lambda ledger: apply_claim_decision(ledger, "pilot", command),
    )


def revision_command(application, target):
    with application.database.transaction() as ledger:
        record = ledger.get(target.entity_id)
        assert isinstance(record.payload, Note)
        replacement = record.payload.model_copy(update={"body": "Improved explanation."})
    return ConsolidateNote(
        target=target,
        context=record.payload.references,
        proposal=NoteRevision(action="revise", rationale="Clarify scope", note=replacement),
    )


def consolidate(application, command, request_id="consolidate"):
    return application.database.command(
        request_id,
        "pilot",
        "consolidate",
        command,
        "hermes:test",
        lambda ledger: apply_note_revision(ledger, "pilot", command),
    )


def test_reimported_passage_reuses_claim_and_evidence(application, article, imported):
    decision = ClaimDecision(
        action="reuse",
        target=imported["claim"],
        rationale="Same population and outcome",
        relation="supports",
    )
    expected = [imported["claim"], imported["evidence"]]
    for request_id in ("passage-first", "passage-first", "passage-again"):
        assert (
            reconcile(application, imported["source"], article.claim, decision, request_id)
            == expected
        )
    with application.database.transaction() as ledger:
        assert len(ledger.list("pilot", "claim")) == 1
        assert len(ledger.list("pilot", "evidence")) == 1


def test_reconciliation_rejects_invented_candidate_revision(application, imported):
    with application.database.transaction() as ledger:
        candidates = ledger.list("pilot", "claim")
    decision = ClaimDecision(
        action="reuse",
        target=Reference(entity_id=uuid4(), revision=1),
        rationale="Invented target",
        relation="supports",
    )
    with pytest.raises(ValueError, match="supplied claim"):
        validate_decision(decision, candidates)


@pytest.mark.parametrize("action", ["new", "skip"])
def test_reconciliation_rejects_target_on_non_reuse(action, application, imported):
    decision = ClaimDecision(
        action=action,
        target=imported["claim"],
        rationale="Invalid combination",
        relation="supports",
    )
    with pytest.raises(ValueError, match="Only reuse"):
        validate_decision(decision, [])


def test_invalid_new_claim_evidence_rolls_back_claim_and_receipt(application, article, imported):
    proposal = article.claim.model_copy(update={"quote": "Fabricated result"})
    decision = ClaimDecision(
        action="new", target=None, rationale="Distinct claim", relation="supports"
    )
    with pytest.raises(ValueError, match="exact substring"):
        reconcile(application, imported["source"], proposal, decision, "invalid-passage")
    with application.database.transaction() as ledger:
        assert len(ledger.list("pilot", "claim")) == 1
        assert ledger.get_receipt("invalid-passage") is None


def test_consolidation_preserves_human_edited_note(application, imported):
    command = revision_command(application, imported["zettel"])
    human_note = command.proposal.note.model_copy(update={"body": "My deliberate wording."})
    edited = application.edit_note(
        "human-edit",
        "pilot",
        EditNote(expected=command.target, note=human_note),
        "human:local",
    )[0]
    command = revision_command(application, edited)
    assert consolidate(application, command) == []
    with application.database.transaction() as ledger:
        current = ledger.get(edited.entity_id)
        assert current.revision == edited.revision
        assert current.payload.body == "My deliberate wording."


def test_consolidation_preserves_reviewed_model_note(application, imported):
    target = imported["zettel"]
    application.decide(
        "human-review",
        "pilot",
        ReviewCommand(target=target, verdict="reviewed", comment="Checked"),
        "human:local",
    )
    assert consolidate(application, revision_command(application, target)) == []
    with application.database.transaction() as ledger:
        assert ledger.get(target.entity_id).revision == target.revision


def test_stale_context_rejects_revision_without_receipt(application, imported):
    command = revision_command(application, imported["zettel"])
    dependency = imported["source_note"]
    command.context.append(dependency)
    with application.database.transaction() as ledger:
        note = ledger.get(dependency.entity_id).payload
    application.edit_note(
        "context-edit",
        "pilot",
        EditNote(expected=dependency, note=note),
        "human:local",
    )
    with pytest.raises(ValueError, match="context changed"):
        consolidate(application, command)
    with application.database.transaction() as ledger:
        assert ledger.get(command.target.entity_id).revision == command.target.revision
        assert ledger.get_receipt("consolidate") is None


def test_forged_inline_citation_cannot_be_consolidated(application, imported):
    command = revision_command(application, imported["zettel"])
    command.proposal.note.body = f"An unsupported statement [{uuid4()}@1]."
    with pytest.raises(ValueError, match="citation"):
        consolidate(application, command)
    with application.database.transaction() as ledger:
        assert ledger.get(command.target.entity_id).revision == command.target.revision
        assert ledger.get_receipt("consolidate") is None


def test_chunks_keep_first_page_and_every_page_once():
    pages = ["First-page result", "x" * PAGE_BUDGET, "Last-page limitation"]
    chunks = page_chunks(pages)
    assert [(number, text) for chunk in chunks for number, text in chunk.items()] == list(
        enumerate(pages, 1)
    )


def test_chunks_exclude_only_explicit_curator_cover():
    chunks = page_chunks(["[Curator cover excluded from evidence]", "Actual article"])
    assert chunks == [{2: "Actual article"}]


def test_consolidation_keeps_visible_citation_not_only_reference_list(application, imported):
    command = revision_command(application, imported["zettel"])
    claim = imported["claim"]
    cited = command.proposal.note.model_copy(
        update={"body": f"Immediate performance improved [{claim.entity_id}@{claim.revision}]."}
    )
    target = application.edit_note(
        "cited-note", "pilot", EditNote(expected=command.target, note=cited), "hermes:fixture"
    )[0]
    stripped = revision_command(application, target)
    with pytest.raises(ValueError, match="inline citations"):
        consolidate(application, stripped)
    with application.database.transaction() as ledger:
        assert ledger.get(target.entity_id).revision == target.revision
        assert ledger.get_receipt("consolidate") is None


def test_consolidation_advances_citation_and_preserves_old_history(application, imported):
    dependency = imported["source_note"]
    original = Note(
        kind="permanent",
        title="Source context",
        body=f"Reported result [{dependency.entity_id}@1].",
        references=[dependency],
    )
    target = application.propose_note("citing-note", "pilot", original, "hermes:fixture")[0]
    with application.database.transaction() as ledger:
        source_note = ledger.get(dependency.entity_id).payload
    updated = application.edit_note(
        "source-note-update",
        "pilot",
        EditNote(expected=dependency, note=source_note),
        "human:local",
    )[0]
    replacement = original.model_copy(
        update={
            "body": f"Qualified result [{updated.entity_id}@{updated.revision}].",
            "references": [updated],
        }
    )
    command = ConsolidateNote(
        target=target,
        context=[updated],
        proposal=NoteRevision(action="revise", rationale="Updated evidence", note=replacement),
    )
    revised = consolidate(application, command)[0]
    with application.database.transaction() as ledger:
        assert ledger.get(revised.entity_id).payload.references == [updated]
        assert ledger.get(target.entity_id, target.revision).payload == original


def test_consolidation_cannot_invent_a_newer_citation_revision(application, imported):
    command = revision_command(application, imported["zettel"])
    dependency = imported["claim"]
    forged = Reference(entity_id=dependency.entity_id, revision=dependency.revision + 1)
    command.proposal.note.references = [
        forged if reference == dependency else reference
        for reference in command.proposal.note.references
    ]
    command.proposal.note.body = f"New result [{forged.entity_id}@{forged.revision}]."
    with pytest.raises(ValueError, match="unseen record"):
        consolidate(application, command)
    with application.database.transaction() as ledger:
        assert ledger.get(command.target.entity_id).revision == command.target.revision


def test_context_keeps_linked_evidence_and_all_claims(application, article, imported):
    second = article.model_copy(deep=True)
    second.source.sha256 = "b" * 64
    other = seed_article(application, "other-source", second)
    with application.database.transaction() as ledger:
        qualifier = ledger.get(imported["evidence"].entity_id).payload.model_copy(
            update={"quote": "No retention was measured.", "relation": "qualifies"}
        )
    extra = application.link_evidence("qualification", "pilot", qualifier, "hermes:fixture")[0]
    with application.database.transaction() as ledger:
        records = ledger.list("pilot")
        target = ledger.get(imported["zettel"].entity_id)
    selected = {record.entity_id for record in note_context(target, records)}
    assert imported["evidence"].entity_id in selected
    assert extra.entity_id in selected
    assert other[2].entity_id not in selected
    assert {imported["claim"].entity_id, other[1].entity_id} <= selected


def test_wiki_context_uses_inline_evidence_and_reports_omissions(application, article, imported):
    second = article.model_copy(deep=True)
    second.source.sha256 = "b" * 64
    other = seed_article(application, "other-source", second)
    wiki = Note(
        kind="wiki",
        title="Synthesis",
        body=f"Result [{imported['evidence'].entity_id}@1].",
        references=[imported["evidence"], other[2]],
    )
    reference = application.propose_note("wiki", "pilot", wiki, "hermes:fixture")[0]
    with application.database.transaction() as ledger:
        records = ledger.list("pilot")
        target = ledger.get(reference.entity_id)
    supplied = note_context(target, records)
    packet = json.loads(note_packet(target, supplied, records))
    assert {record.entity_id for record in supplied if record.kind == "evidence"} == {
        imported["evidence"].entity_id
    }
    assert packet["coverage"]["evidence_supplied"] == 1
    assert packet["coverage"]["evidence_total"] == 2


def test_generation_cannot_cite_undelivered_evidence(
    application, article, imported, monkeypatch, tmp_path
):
    second = article.model_copy(deep=True)
    second.source.sha256 = "b" * 64
    other = seed_article(application, "other-source", second)
    with application.database.transaction() as ledger:
        records = ledger.list("pilot")
        target = ledger.get(imported["zettel"].entity_id)

    def generate(instructions, packet, contract, output_directory, validate, **kwargs):
        note = target.payload.model_copy(deep=True)
        note.references.append(other[2])
        note.body += f" Unsupported [{other[2].entity_id}@1]."
        with pytest.raises(ValueError, match="unseen record"):
            validate(NoteRevision(action="revise", rationale="Unseen evidence", note=note))
        return NoteRevision(action="keep", rationale="No supported addition", note=None)

    monkeypatch.setattr("knowledge.consolidation.generate", generate)
    command = propose_note_revision(target, records, tmp_path)
    assert other[2] not in command.context
    assert imported["evidence"] in command.context


@pytest.mark.parametrize("same_pdf", [True, False])
def test_evidence_identity_tracks_pdf_version_not_source_revision(application, imported, same_pdf):
    with application.database.transaction() as ledger:
        original_source = ledger.get(imported["source"].entity_id)
        original_evidence = ledger.get(imported["evidence"].entity_id)
        revised_source = original_source.payload.model_copy(
            update={"sha256": original_source.payload.sha256 if same_pdf else "c" * 64}
        )
        migrated = ledger.append(
            "pilot", "source", revised_source, "migration:fixture", imported["source"]
        )
    relation = original_evidence.payload.model_copy(update={"source": migrated})
    accepted = application.link_evidence("after-migration", "pilot", relation, "hermes:fixture")[0]
    with application.database.transaction() as ledger:
        preserved = ledger.get(imported["evidence"].entity_id)
        assert preserved.payload.source == imported["source"]
        assert preserved.revision == imported["evidence"].revision
        if same_pdf:
            assert accepted == imported["evidence"]
            assert len(ledger.list("pilot", "evidence")) == 1
        else:
            assert accepted.entity_id != imported["evidence"].entity_id
            assert ledger.get(accepted.entity_id).payload.source == migrated
            assert len(ledger.list("pilot", "evidence")) == 2


def test_new_claim_keeps_passage_rationale_separate_from_matching_reason(
    application, article, imported
):
    proposal = article.claim
    decision = ClaimDecision(
        action="new",
        target=None,
        rationale="Different from the candidate population",
        relation="unclear",
    )
    references = reconcile(application, imported["source"], proposal, decision, "new-claim")
    with application.database.transaction() as ledger:
        relation = ledger.get(references[1].entity_id).payload
    assert relation.rationale == proposal.rationale
    assert relation.relation == proposal.relation


def test_failed_passage_check_keeps_original_matching_decision_for_audit(
    application, article, imported, tmp_path, monkeypatch
):
    from knowledge.grounding import PassageCheck
    from knowledge.reconciliation import check_claim_grounding

    monkeypatch.setattr(
        "knowledge.reconciliation.check_passage",
        lambda *args: PassageCheck(grounded=False, reason="Unsupported time horizon"),
    )
    original = ClaimDecision(
        action="new", target=None, rationale="Distinct result", relation="supports"
    )
    checked = check_claim_grounding(
        application, imported["source"], article.claim, original, tmp_path
    )
    assert checked.action == "skip"
    assert "Unsupported time horizon" in checked.rationale
    assert original.action == "new"
    with application.database.transaction() as ledger:
        assert len(ledger.list("pilot", "claim")) == 1


def test_reuse_reclassifies_directness_for_the_selected_claim(application, article, imported):
    with application.database.transaction() as ledger:
        source = ledger.append(
            "pilot", "source", article.source.model_copy(update={"sha256": "b" * 64}), "fixture"
        )
    decision = ClaimDecision(
        action="reuse",
        target=imported["claim"],
        rationale="Indirect contribution to the selected claim",
        relation="supports",
        directness="indirect",
    )
    references = reconcile(application, source, article.claim, decision, "indirect")
    with application.database.transaction() as ledger:
        relation = ledger.get(references[1].entity_id).payload
    assert relation.directness == "indirect"
    assert relation.rationale == decision.rationale
