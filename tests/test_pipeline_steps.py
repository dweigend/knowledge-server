import hashlib
import json
import sys
from uuid import UUID

import pytest

from knowledge.contracts import Bibliography, Claim, ExtractedClaim, Record
from knowledge.import_workflow import ArticleExtraction, extract_document
from knowledge.information_blocks import TextExtraction, segment_verbatim, text_revision
from knowledge.ingestion import cancellable_pdf_text
from knowledge.knowledge_selection import (
    EntrySelection,
    KnowledgeSelection,
    retrieve_knowledge,
    validate_selection,
)
from knowledge.pipeline_steps import (
    claim_source_pins,
    execute_step,
    formulate_claims,
    validate_step_parameters,
)
from knowledge.prompt_registry import resolve_recipe, save_revision, seed_defaults
from knowledge.writing import (
    WritingPoint,
    WritingPoints,
    validate_block_citations,
    validate_writing_points,
)


@pytest.fixture
def document():
    digest = hashlib.sha256(b"Independent observation fixture").hexdigest()
    pages = ("Group A scored higher.\n\nNo retention was measured.",)
    return TextExtraction(
        pdf_sha256=digest,
        revision=text_revision(digest, pages, "reviewed-fixture"),
        pages=pages,
        method="reviewed-fixture",
    )


@pytest.fixture
def proposal():
    return ExtractedClaim(
        proposition="The intervention improved immediate scores",
        scope="Group A in the tested population",
        qualifications="No retention was measured",
        page=1,
        quote="Group A scored higher.",
        relation="supports",
        rationale="An observed group comparison",
        directness="direct",
        methodology="Group comparison",
        limitations="No retention measurement",
    )


def claim_record(number, text):
    return Record(
        entity_id=UUID(int=number),
        revision=2,
        batch_id="fixture",
        kind="claim",
        actor="human:fixture",
        created_at="2026-09-15T00:00:00Z",
        payload=Claim(proposition=text, scope="Fixture", qualifications="Limited"),
    )


def test_claim_source_pin_has_independently_known_offsets(document, proposal):
    result = claim_source_pins(proposal, segment_verbatim(document), document)
    assert result.block_indexes == [1]
    assert [(span.page, span.start, span.end, span.quote) for span in result.sources] == [
        (1, 0, 22, "Group A scored higher.")
    ]
    assert result.sources[0].extraction_revision == document.revision


def test_claim_cannot_cite_text_outside_selected_blocks(document, proposal):
    blocks = segment_verbatim(document)
    blocks.blocks = blocks.blocks[1:]
    with pytest.raises(ValueError, match="inside a supplied"):
        claim_source_pins(proposal, blocks, document)


def test_retrieval_is_bounded_deterministic_and_preserves_seed_revisions():
    records = [claim_record(2, "Immediate scores"), claim_record(1, "Delayed scores")]
    result = retrieve_knowledge("scores", records, limit=1)
    assert result.corpus_size == 2
    assert result.hits[0].record.reference() == records[1].reference()
    assert result.hits[0].matched_terms == ["scores"]
    assert result.hits[0].score == 1
    assert records[0].revision == 2


def test_selection_requires_explicit_choice_for_each_exact_retrieved_revision():
    result = retrieve_knowledge("scores", [claim_record(1, "Immediate scores")])
    entry = EntrySelection(
        reference=result.hits[0].record.reference(),
        selected=False,
        rationale="Different measurement period",
    )
    validate_selection(KnowledgeSelection(entries=[entry]), result)
    for entries in (
        [],
        [entry, entry],
        [
            entry.model_copy(
                update={"reference": entry.reference.model_copy(update={"revision": 3})}
            )
        ],
    ):
        with pytest.raises(ValueError, match="exactly once"):
            validate_selection(KnowledgeSelection(entries=entries), result)


def test_writing_rejects_invented_sources_and_changed_goal(document):
    blocks = segment_verbatim(document)
    points = WritingPoints(
        goal="Explain limits",
        points=[WritingPoint(text="Retention remains unknown [block:2].", block_indexes=[2])],
    )
    validate_writing_points(points, blocks, "Explain limits")
    with pytest.raises(ValueError, match="changed"):
        validate_writing_points(points, blocks, "A different goal")
    for text, indexes in [
        ("No source", [2]),
        ("Unknown [block:3]", [3]),
        ("Mismatch [block:1]", [2]),
    ]:
        with pytest.raises(ValueError, match="supplied"):
            validate_block_citations(text, indexes, {1, 2})


def test_shared_import_and_workbench_use_same_adapter_contract(
    document, proposal, tmp_path, monkeypatch
):
    seed_defaults()
    _, recipe, _, _ = resolve_recipe("formulate_claims")
    bibliography = Bibliography(title="Fixture", authors=[], year="2026", doi="", url="")
    response = ArticleExtraction(
        bibliography=bibliography,
        claims=[proposal],
        study_group="A",
        overlap="Unknown",
        warnings=[],
    )
    requests = []

    def respond(request_path, response_path, log_path, **kwargs):
        request = json.loads(request_path.read_text())
        requests.append(request)
        response_path.write_text(
            json.dumps({"response": response.model_dump_json(), "execution": "simulated"})
        )

    monkeypatch.setattr("knowledge.generation.run_hermes", respond)
    production = extract_document(list(document.pages), tmp_path / "production")
    experiment = formulate_claims(
        document, segment_verbatim(document), recipe, tmp_path / "experiment", lambda: False
    )
    assert production == experiment.extractions
    assert len(requests) == 2
    assert requests[0]["instructions"] == requests[1]["instructions"]
    assert "ArticleExtraction" in requests[0]["input"]
    assert "information_blocks" in requests[1]["input"]
    assert document.revision in requests[1]["input"]


def test_missing_step_dependency_and_cancellation_stop_before_model(tmp_path):
    seed_defaults()
    _, recipe, _, _ = resolve_recipe("segment_blocks")
    with pytest.raises(ValueError, match="missing required"):
        execute_step(
            "segment_blocks", tmp_path / "unused.pdf", {}, [], recipe, tmp_path, lambda: False
        )
    _, recipe, _, _ = resolve_recipe("extract_text")
    with pytest.raises(InterruptedError):
        execute_step(
            "extract_text", tmp_path / "unused.pdf", {}, [], recipe, tmp_path, lambda: True
        )


@pytest.mark.parametrize(
    "step,parameters",
    [
        ("extract_text", {"invented": True}),
        ("segment_blocks", {"max_characters": True}),
        ("segment_blocks", {"mode": {"invented": 1}}),
        ("find_knowledge", {"limit": 41}),
        ("find_knowledge", {"query": ["ignored"]}),
        ("prepare_writing", {"goal": 123}),
        ("draft_text", {"temperature": 0.2}),
    ],
)
def test_unsupported_or_mistyped_parameters_reject_before_execution(step, parameters):
    seed_defaults()
    _, recipe, _, _ = resolve_recipe(step)
    recipe.parameters = parameters
    with pytest.raises(ValueError):
        validate_step_parameters(recipe)


def test_extraction_subprocess_has_real_timeout_and_cancellation():
    command = [sys.executable, "-c", "import time; time.sleep(5)"]
    with pytest.raises(TimeoutError, match="time limit"):
        cancellable_pdf_text(command, 0.03, lambda: False)
    with pytest.raises(InterruptedError, match="cancelled"):
        cancellable_pdf_text(command, 1, lambda: True)


def write_reviewed_pdf(path):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 160 Td (Group A scored higher.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)


def test_eight_manual_steps_keep_original_evidence_with_simulated_model_boundary(
    proposal, tmp_path, monkeypatch
):
    seed_defaults()
    pdf = tmp_path / "reviewed-fixture.pdf"
    write_reviewed_pdf(pdf)
    rules = save_revision(
        "author_rules",
        "fixture-style",
        {
            "text": "Use short sentences; retain uncertainty.",
            "examples": ["A small gain, cautiously."],
        },
        0,
    )
    seed = claim_record(1, "The intervention improved immediate scores")
    article = ArticleExtraction(
        bibliography=Bibliography(title="Fixture", authors=[], year="2026", doi="", url=""),
        claims=[proposal],
        study_group="A",
        overlap="Unknown",
        warnings=[],
    )
    responses = {
        "ArticleExtraction": article.model_dump(mode="json"),
        "KnowledgeSelection": {
            "entries": [
                {
                    "reference": seed.reference().model_dump(mode="json"),
                    "selected": True,
                    "rationale": "Same immediate outcome",
                }
            ]
        },
        "ClaimDecision": {
            "action": "reuse",
            "target": seed.reference().model_dump(mode="json"),
            "rationale": "Observed comparison",
            "relation": "supports",
            "directness": "direct",
        },
        "WritingPoints": {
            "goal": "Explain the observation",
            "points": [{"text": "Group A scored higher [block:1].", "block_indexes": [1]}],
        },
        "WritingDraft": {"text": "Group A scored higher [block:1].", "block_indexes": [1]},
    }
    called = []

    def respond(request_path, response_path, log_path, **kwargs):
        request = json.loads(request_path.read_text())
        schema = json.loads(request["input"].split("\n\nINPUT:", 1)[0].removeprefix("SCHEMA:\n"))
        called.append(schema["title"])
        response_path.write_text(
            json.dumps(
                {"response": json.dumps(responses[schema["title"]]), "execution": "simulated"}
            )
        )

    monkeypatch.setattr("knowledge.generation.run_hermes", respond)
    results = {}
    for step in (
        "extract_text",
        "segment_blocks",
        "formulate_claims",
        "find_knowledge",
        "select_entries",
        "propose_changes",
        "prepare_writing",
        "draft_text",
    ):
        _, recipe, _, _ = resolve_recipe(step)
        if step == "segment_blocks":
            recipe.parameters["mode"] = "paragraphs"
        if step == "prepare_writing":
            recipe.parameters["goal"] = "Explain the observation"
        if step == "draft_text":
            recipe.author_rules_name, recipe.author_rules_revision = rules.name, rules.revision
        result = execute_step(step, pdf, results, [seed], recipe, tmp_path / step, lambda: False)
        results[step] = result.model_dump(mode="json")
    assert called == list(responses)
    assert (
        results["formulate_claims"]["claims"][0]["sources"][0]["extraction_revision"]
        == (results["extract_text"]["revision"])
    )
    assert results["propose_changes"]["claims"][0]["decision"]["target"]["revision"] == 2
    assert results["draft_text"]["block_indexes"] == [1]
    assert "[block:1]" in results["draft_text"]["text"]
    assert seed.revision == 2
