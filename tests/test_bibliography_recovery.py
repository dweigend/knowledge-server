import json
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest
from pydantic import BaseModel

from knowledge.literature.structured_paper_models import (
    PaperCitation,
    PaperDocument,
    PaperMetadata,
    PaperReference,
)
from knowledge.model_integration.structured_generation import ModelConfiguration
from knowledge.source_workflows import bibliography_recovery as recovery
from knowledge.source_workflows.bibliography_recovery_models import (
    BibliographyParsing,
    ReferenceParsing,
)


def paper_with(
    references: list[PaperReference], citations: Iterable[PaperCitation] = ()
) -> PaperDocument:
    return PaperDocument(
        provider="fixture",
        metadata=PaperMetadata(title="Synthetic research chapter"),
        markdown="Unmodified original structure",
        references=references,
        citations=list(citations),
    )


def recover(
    paper: PaperDocument,
    pages: list[str],
    directory: Path,
    *,
    allow_model: bool = True,
) -> recovery.BibliographyRecoveryResult:
    files_before = set(directory.rglob("*"))
    result = recovery.recover_bibliography(
        paper,
        pages,
        configuration=ModelConfiguration(),
        cancelled=lambda: False,
        allow_model=allow_model,
    )
    assert set(directory.rglob("*")) == files_before
    return result


def complete_reference(identifier: str = "b0") -> PaperReference:
    return PaperReference(
        id=identifier,
        raw="Smith J (2001) A research title. Publisher, Berlin",
        title="A research title",
        authors=["J Smith"],
        year="2001",
    )


def test_consistent_complete_bibliography_does_not_call_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recovery.structured_generation, "generate", lambda *a, **k: pytest.fail())
    reference = complete_reference()
    paper = paper_with([reference])
    result = recover(paper, ["References\n" + (reference.raw or "")], tmp_path)
    assert result.paper == paper
    assert result.report.status == "consistent"
    assert result.report.model_status == "not_needed"
    span = result.report.entries[0].spans[0]
    assert span.page == 1
    assert span.start == len("References\n")
    assert span.text == reference.raw


def test_golden_nineteen_entries_recover_five_missing_and_two_merged_pairs(tmp_path: Path) -> None:
    surnames = [
        "Adams",
        "Baker",
        "Clark",
        "Davis",
        "Evans",
        "Frank",
        "Green",
        "Hill",
        "Irwin",
        "Jones",
        "King",
        "Lane",
        "Mills",
        "Nash",
        "Owens",
        "Parks",
        "Quinn",
        "Reed",
        "Stone",
    ]
    raw = [f"{name} J (2001) Research on {name}. Publisher, Berlin" for name in surnames]
    raw[17] = (
        "Reed J (2001) Research on Reed. In: Editor A; Second B\n"
        "Third C (Hrsg) (2001) Collected papers. Berlin"
    )
    pages = [
        "Discussion of a study (2001).\nLiteraturverzeichnis\n" + "\n".join(raw[:5]),
        "Synthetic research chapter\n35\n" + "\n".join(raw[5:]),
    ]
    references = []
    for index in range(5, 19):
        if index in {8, 16}:
            continue
        combined = raw[index] + " " + raw[index + 1] if index in {7, 15} else raw[index]
        references.append(PaperReference(id=f"b{index}", raw=combined))
    citation = PaperCitation(marker="(Hill 2001)", target_ids=["b7", "b5"], resolved=True)
    paper = paper_with(references, [citation])
    result = recover(paper, pages, tmp_path, allow_model=False)
    assert result.report.original_count == 12
    assert result.report.detected_count == result.report.resulting_count == 19
    assert len(result.report.missing_entry_ids) == 5
    assert {ref.id for ref in result.report.merged_originals} == {"b7", "b15"}
    assert len({ref.id for ref in result.paper.references}) == 19
    assert result.paper.citations[0].target_ids == ["b5"]
    assert result.paper.citations[0].resolved is False
    assert result.report.invalidated_citation_indexes == [0]
    assert paper.citations[0].resolved is True
    assert result.paper.markdown == paper.markdown
    for entry in result.report.entries:
        for span in entry.spans:
            assert pages[span.page - 1][span.start : span.end] == span.text
    assert result.report.entries[4].raw == raw[4]
    assert result.report.entries[17].raw == raw[17]


def test_model_only_receives_incomplete_entries_and_source_fields_are_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    complete = complete_reference()
    pages = ["References\n" + (complete.raw or "") + "\nBrown B (2002) Missing source title. Press"]
    calls = []

    def generate(
        instructions: str,
        packet: str,
        contract: type[BaseModel],
        validate: Callable[[BibliographyParsing], None],
        *,
        configuration: ModelConfiguration,
        **options: object,
    ) -> BibliographyParsing:
        entries = json.loads(packet)
        calls.append(entries)
        assert len(entries) == 1
        assert "Brown B" in entries[0]["raw"]
        proposal = BibliographyParsing(
            entries=[
                ReferenceParsing(
                    entry_id=entries[0]["id"],
                    metadata=PaperMetadata(
                        title="Missing source title", authors=["B Brown"], year="2002"
                    ),
                )
            ]
        )
        validate(proposal)
        return proposal

    monkeypatch.setattr(recovery.structured_generation, "generate", generate)
    result = recover(paper_with([complete]), pages, tmp_path)
    assert len(calls) == 1
    assert result.report.status == "recovered"
    assert result.paper.references[1].title == "Missing source title"
    assert result.paper.references[1].authors == ["B Brown"]
    assert result.paper.references[0] == complete


@pytest.mark.parametrize(
    "metadata",
    [
        PaperMetadata(title="Invented book"),
        PaperMetadata(authors=["Invented Person"]),
        PaperMetadata(doi="10.1234/fabricated"),
    ],
)
def test_model_cannot_invent_bibliographic_fields(metadata: PaperMetadata) -> None:
    entries = recovery.detect_entries(paper_with([]), ["References\nSmith J (2001) Source title"])
    proposal = BibliographyParsing(
        entries=[ReferenceParsing(entry_id=entries[0].id, metadata=metadata)]
    )
    with pytest.raises(ValueError, match="absent"):
        recovery.validate_parsing(proposal, entries)


def test_model_cannot_change_entry_ids_or_duplicate_them() -> None:
    entries = recovery.detect_entries(paper_with([]), ["References\nSmith J (2001) Source title"])
    invented = ReferenceParsing(entry_id="invented", metadata=PaperMetadata())
    duplicate = ReferenceParsing(entry_id=entries[0].id, metadata=PaperMetadata())
    for proposals in ([invented], [duplicate, duplicate]):
        with pytest.raises(ValueError, match="unknown or duplicate"):
            recovery.validate_parsing(BibliographyParsing(entries=proposals), entries)


@pytest.mark.parametrize("failure", [False, True])
def test_negative_and_failed_model_attempts_run_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: bool
) -> None:
    calls = []

    def generate(*args: object, **kwargs: object) -> BibliographyParsing:
        calls.append(True)
        if failure:
            raise ValueError("No usable model response")
        return BibliographyParsing()

    monkeypatch.setattr(recovery.structured_generation, "generate", generate)
    paper = paper_with([])
    pages = ["References\nSmith J (2001) Source title"]
    first = recover(paper, pages, tmp_path)
    second = recover(paper, pages, tmp_path)
    assert len(calls) == 2
    assert first.report.status == second.report.status == "needs_review"
    assert first.report.model_status == ("failed" if failure else "completed")


def test_unmatched_original_reference_is_retained(tmp_path: Path) -> None:
    original = complete_reference()
    result = recover(
        paper_with([original]),
        ["References\nBrown B (2002) Other book"],
        tmp_path,
        allow_model=False,
    )
    assert original in result.paper.references
    assert any("b0" in issue for issue in result.report.unresolved_issues)
    assert len(result.paper.references) == 2


def test_missing_heading_is_unverified_without_unbounded_model_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recovery.structured_generation, "generate", lambda *a, **k: pytest.fail())
    paper = paper_with([complete_reference()])
    result = recover(paper, ["No explicit bibliography boundary"], tmp_path)
    assert result.paper.references == paper.references
    assert result.report.status == "needs_review"
    assert "unverified" in result.report.unresolved_issues[0]


def test_cancellation_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def generate(*args: object, **kwargs: object) -> BibliographyParsing:
        raise InterruptedError("Cancelled")

    monkeypatch.setattr(recovery.structured_generation, "generate", generate)
    with pytest.raises(InterruptedError):
        recover(paper_with([]), ["References\nSmith J (2001) Source title"], tmp_path)


def test_unique_author_year_markers_relink_without_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(recovery.structured_generation, "generate", lambda *a, **k: pytest.fail())
    citations = [
        PaperCitation(marker="(Smith 2001, Kap. 3.3.3)"),
        PaperCitation(marker="(Brown/Green 2002)"),
        PaperCitation(marker="Brown et al. 2002)"),
    ]
    pages = [
        "References\nSmith J (2001) First title. Publisher\n"
        "Brown B, Green H-G (2002) Second title. Publisher"
    ]
    result = recover(paper_with([], citations), pages, tmp_path, allow_model=False)
    assert all(citation.resolved for citation in result.paper.citations)
    assert result.report.relinked_citation_indexes == [0, 1, 2]
    assert result.paper.citations[0].target_ids != result.paper.citations[1].target_ids
    assert result.paper.citations[1].target_ids == result.paper.citations[2].target_ids


def test_split_reference_citations_are_reassigned_only_to_unique_source_entries(
    tmp_path: Path,
) -> None:
    first = "Smith J (2001) First title. Publisher"
    second = "Brown B (2002) Second title. Publisher"
    paper = paper_with(
        [PaperReference(id="merged", raw=first + " " + second)],
        [PaperCitation(marker="(Brown 2002)", target_ids=["merged"], resolved=True)],
    )
    result = recover(paper, ["References\n" + first + "\n" + second], tmp_path, allow_model=False)
    assert result.paper.citations[0].resolved
    target = result.paper.citations[0].target_ids[0]
    assert next(ref.raw for ref in result.paper.references if ref.id == target) == second
    assert (
        result.report.invalidated_citation_indexes == result.report.relinked_citation_indexes == [0]
    )
    assert not any("reassignment" in issue for issue in result.report.unresolved_issues)


@pytest.mark.parametrize(
    "marker",
    [
        "(Smith 2001; Brown 2002)",
        "Smith 2001, Brown 2002",
        "Smith 2001, Other Person in conversation",
        "[1]",
        "(Smith 2001a)",
    ],
)
def test_unclear_multicitation_or_year_suffix_is_not_partially_relinked(
    tmp_path: Path, marker: str
) -> None:
    paper = paper_with([complete_reference()], [PaperCitation(marker=marker)])
    result = recover(
        paper, ["References\n" + (complete_reference().raw or "")], tmp_path, allow_model=False
    )
    assert not result.paper.citations[0].resolved
    assert result.paper.citations[0].target_ids == []
    assert result.report.relinked_citation_indexes == []


def test_same_author_year_collision_and_existing_links_are_preserved(tmp_path: Path) -> None:
    references = [complete_reference("b0"), complete_reference("b1")]
    references[1].title = "Different research title"
    references[1].raw = "Smith J (2001) Different research title. Publisher"
    citations = [
        PaperCitation(marker="(Smith 2001)"),
        PaperCitation(marker="(Smith 2001)", target_ids=["b0"], resolved=True),
    ]
    paper = paper_with(references, citations)
    pages = ["References\n" + "\n".join(ref.raw or "" for ref in references)]
    result = recover(paper, pages, tmp_path, allow_model=False)
    assert result.paper.citations == citations
