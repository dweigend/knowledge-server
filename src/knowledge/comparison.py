"""Bounded cross-source retrieval and evidence proposals, separate from assessment."""

import json
import re
from functools import partial
from pathlib import Path

from pydantic import Field

from knowledge.application import AssessmentCommand, CompareEvidence, Knowledge
from knowledge.contracts import Assessment, Contract, Evidence, Record, Reference, Source
from knowledge.evidence import records_for_claim
from knowledge.generation import generate
from knowledge.ingestion import locate_passage
from knowledge.zotero import get_bibliography


class Comparison(Contract):
    """Represent a bounded set of proposed cross-source relations."""

    relations: list[Evidence] = Field(max_length=3)
    search_summary: str = Field(min_length=1)


def candidate_packet(
    claim: Record,
    current_evidence: list[Record],
    source_records: list[Record],
) -> tuple[str, dict[str, list[int]]]:
    """Build a bounded packet from sources not already cited by the claim."""
    relations = [
        record.payload for record in current_evidence if isinstance(record.payload, Evidence)
    ]
    quoted_text = " ".join(relation.quote for relation in relations)
    keywords = set(re.findall(r"[a-z]{5,}", quoted_text.lower()))
    covered_sources = {str(relation.source.entity_id) for relation in relations}
    candidates = []
    selection = {}
    for source_record in source_records:
        source = source_record.payload
        assert isinstance(source, Source)
        if str(source_record.entity_id) in covered_sources:
            continue
        candidate = source_candidate(source_record, source, keywords)
        selection[str(source_record.entity_id)] = [page["number"] for page in candidate["pages"]]
        candidates.append(candidate)
    packet = {"claim": claim.model_dump(mode="json"), "candidates": candidates}
    return json.dumps(packet, ensure_ascii=False), selection


def source_candidate(record: Record, source: Source, keywords: set[str]) -> dict:
    """Select the first body page and the strongest lexical match from one source."""
    ranked_indexes = sorted(
        range(1, len(source.pages)),
        key=lambda index: sum(source.pages[index].lower().count(word) for word in keywords),
        reverse=True,
    )
    selected_indexes = sorted({1, *ranked_indexes[:1]})
    return {
        "source": record.reference().model_dump(mode="json"),
        "bibliography": get_bibliography(source).model_dump(mode="json"),
        "study_group": source.study_group,
        "overlap": source.overlap,
        "pages": [{"number": index + 1, "text": source.pages[index]} for index in selected_indexes],
    }


def validate_comparison(
    comparison: Comparison,
    *,
    application: Knowledge,
    batch_id: str,
    claim_reference: Reference,
    selection: dict[str, list[int]],
) -> None:
    """Require the target claim and exact quotes from pages supplied to the model."""
    for relation in comparison.relations:
        if relation.claim != claim_reference:
            raise ValueError("Comparison changed target claim")
        with application.database.transaction() as ledger:
            source = ledger.require(relation.source, batch_id, "source").payload
        assert isinstance(source, Source)
        try:
            relation.page, relation.quote = locate_passage(
                source.pages,
                relation.page,
                relation.quote,
            )
        except ValueError as error:
            raise ValueError(
                f"Invalid quote on source {relation.source.entity_id}: {relation.quote}"
            ) from error
        if relation.page not in selection.get(str(relation.source.entity_id), []):
            raise ValueError("Comparison cited an unseen page")


def enrich(application: Knowledge, batch_id: str, batch_root: Path, prompts: Path) -> None:
    """Compare each claim with the corpus and propose updated assessments."""
    with application.database.transaction() as ledger:
        claims = ledger.list(batch_id, "claim")
        source_records = ledger.list(batch_id, "source")
    for claim in claims:
        audit = compare_claim(application, batch_id, batch_root, prompts, claim, source_records)
        assess_compared_claim(application, batch_id, batch_root, prompts, claim, audit)


def compare_claim(
    application: Knowledge,
    batch_id: str,
    batch_root: Path,
    prompts: Path,
    claim: Record,
    source_records: list[Record],
) -> Path:
    """Resume a prepared comparison and save its audit after the atomic import."""
    with application.database.transaction() as ledger:
        current_evidence = records_for_claim(ledger.list(batch_id, "evidence"), claim.reference())
    audit = batch_root / "comparisons" / f"{claim.entity_id}.json"
    if audit.exists():
        return audit
    command = prepare_comparison(
        application, batch_id, batch_root, prompts, claim, current_evidence, source_records
    )
    application.import_comparison(
        f"{batch_id}:compare:{claim.entity_id}",
        batch_id,
        command,
        "hermes:gpt-5.6-luna:compare-v1",
    )
    temporary = audit.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {"selection": command.selected_pages, "summary": command.search_summary},
            ensure_ascii=False,
        )
    )
    temporary.replace(audit)
    return audit


def prepare_comparison(
    application: Knowledge,
    batch_id: str,
    batch_root: Path,
    prompts: Path,
    claim: Record,
    current_evidence: list[Record],
    source_records: list[Record],
) -> CompareEvidence:
    """Reuse or persist the complete comparison command before its database import."""
    prepared = batch_root / "comparisons" / f"{claim.entity_id}.prepared.json"
    if prepared.exists():
        return CompareEvidence.model_validate_json(prepared.read_text())
    packet, selection = candidate_packet(claim, current_evidence, source_records)
    comparison = generate(
        (prompts / "compare.md").read_text(),
        packet,
        Comparison,
        batch_root / "proposals",
        validate=partial(
            validate_comparison,
            application=application,
            batch_id=batch_id,
            claim_reference=claim.reference(),
            selection=selection,
        ),
    )
    command = CompareEvidence(
        relations=comparison.relations,
        search_summary=comparison.search_summary,
        selected_pages=selection,
    )
    prepared.parent.mkdir(parents=True, exist_ok=True)
    temporary = prepared.with_suffix(".tmp")
    temporary.write_text(command.model_dump_json(indent=2))
    temporary.replace(prepared)
    return command


def assess_compared_claim(
    application: Knowledge,
    batch_id: str,
    batch_root: Path,
    prompts: Path,
    claim: Record,
    audit: Path,
) -> None:
    """Propose an assessment of all current relations with explicit search coverage."""
    search = json.loads(audit.read_text())
    with application.database.transaction() as ledger:
        relations = records_for_claim(ledger.list(batch_id, "evidence"), claim.reference())
        assessments = [
            record
            for record in ledger.list(batch_id, "assessment")
            if isinstance(record.payload, Assessment) and record.payload.claim == claim.reference()
        ]
    packet = assessment_packet(claim, relations, search)
    assessment = generate(
        (prompts / "assess.md").read_text(), packet, Assessment, batch_root / "proposals"
    )
    existing = max(assessments, key=lambda record: record.created_at) if assessments else None
    receipt_id = f"{batch_id}:cross-assess:{claim.entity_id}"
    with application.database.transaction() as ledger:
        done = ledger.get_receipt(receipt_id)
    if not done:
        application.assess(
            receipt_id,
            batch_id,
            AssessmentCommand(
                assessment=assessment,
                expected=existing.reference() if existing else None,
            ),
            "hermes:gpt-5.6-luna:cross-assess-v1",
        )
    print(f"Cross-source assessment {claim.entity_id}: {len(relations)} relations", flush=True)


def assessment_packet(claim: Record, relations: list[Record], search: dict) -> str:
    """State the observed evidence and the limits of the cross-source search."""
    return json.dumps(
        {
            "claim": claim.model_dump(mode="json"),
            "evidence": [record.model_dump(mode="json") for record in relations],
            "coverage": {
                "method": "First body page plus one lexical candidate page per other "
                "source; ten convenience-selected sources, not systematic research.",
                **search,
            },
        },
        ensure_ascii=False,
    )
