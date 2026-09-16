"""Retrieve knowledge and produce unaccepted claim and note proposals.

These executors consume only a pinned in-memory snapshot and pure proposal
operations, so experiments never import production persistence workflows.
"""

import difflib
from collections.abc import Mapping
from typing import cast

from knowledge.experiments import pipeline_specification
from knowledge.experiments.experiment_steps import document_steps, step_contracts
from knowledge.knowledge_domain import knowledge_record_models
from knowledge.model_integration import prompt_registry, structured_generation
from knowledge.source_workflows import (
    claim_matching,
    knowledge_candidate_selection,
    note_revision_proposals,
)


def validate_retrieval_parameters(parameters: Mapping[str, object]) -> None:
    """Validate an optional query and bounded retrieval limit."""
    validate_selection_parameters(parameters)
    limit = parameters.get("limit", 20)
    if type(limit) is not int or not 1 <= limit <= 40:
        raise ValueError("limit must be an integer between 1 and 40")


def validate_selection_parameters(parameters: Mapping[str, object]) -> None:
    """Validate an optional selection query."""
    query = parameters.get("query")
    if query is not None and not isinstance(query, str):
        raise ValueError("query must be text")


def _knowledge_query(execution: pipeline_specification.StepExecution) -> str:
    formulation = execution.inputs["formulate_claims"]
    return str(
        execution.recipe.parameters.get("query")
        or " ".join(
            f"{claim.proposal.proposition} {claim.proposal.scope}" for claim in formulation.claims
        )
        or " ".join(article.bibliography.title for article in formulation.extractions)
    )


def find_knowledge(
    execution: pipeline_specification.StepExecution,
) -> knowledge_candidate_selection.KnowledgeRetrieval:
    """Search the pinned knowledge snapshot deterministically."""
    limit = cast(int, execution.recipe.parameters.get("limit", 20))
    return knowledge_candidate_selection.retrieve_knowledge(
        _knowledge_query(execution), execution.knowledge, limit
    )


def select_entries(
    execution: pipeline_specification.StepExecution,
) -> knowledge_candidate_selection.KnowledgeSelection:
    """Select relevant entries only from the pinned retrieval output."""
    retrieval = execution.inputs["find_knowledge"]
    return knowledge_candidate_selection.select_knowledge(
        retrieval,
        _knowledge_query(execution),
        execution.prompt_text,
        execution.output_directory,
        execution.recipe.model,
        execution.cancelled,
    )


def selected_records(
    execution: pipeline_specification.StepExecution,
) -> list[knowledge_record_models.Record]:
    """Verify selected candidates against retrieval and pinned knowledge revisions."""
    retrieval = execution.inputs["find_knowledge"]
    selection = execution.inputs["select_entries"]
    knowledge_candidate_selection.validate_selection(selection, retrieval)
    if any(hit.record not in execution.knowledge for hit in retrieval.hits):
        raise ValueError("Retrieved record differs from pinned input knowledge")
    selected = [entry.reference for entry in selection.entries if entry.selected]
    return [record for record in execution.knowledge if record.reference() in selected]


def propose_changes(
    execution: pipeline_specification.StepExecution,
) -> step_contracts.KnowledgeChanges:
    """Generate claim and note proposals without accepting domain changes."""
    records = selected_records(execution)
    formulation = execution.inputs["formulate_claims"]
    changes = _propose_claim_changes(execution, formulation, records)
    return step_contracts.KnowledgeChanges(
        claims=changes,
        notes=_propose_note_changes(execution, records),
        warnings=[
            "Proposals only; grounding and human review are required before acceptance.",
            "Note proposals use selected knowledge; new evidence is not yet accepted into notes.",
            "Claim scope uses the text contract; structured scope migration remains pending.",
        ],
    )


def _propose_claim_changes(
    execution: pipeline_specification.StepExecution,
    formulation: step_contracts.ClaimFormulation,
    records: list[knowledge_record_models.Record],
) -> list[step_contracts.ClaimChange]:
    extraction = execution.inputs["extract_text"]
    blocks = execution.inputs["segment_blocks"]
    candidates = [record for record in records if record.kind == "claim"]
    changes = []
    for claim in formulation.claims:
        structured_generation.check_cancelled(execution.cancelled)
        if document_steps.claim_source_pins(claim.proposal, blocks, extraction) != claim:
            raise ValueError("Claim provenance differs from its pinned source blocks")
        decision = claim_matching.propose_matching(
            claim.proposal,
            candidates,
            execution.output_directory,
            instructions=execution.prompt_text,
            configuration=execution.recipe.model,
            cancelled=execution.cancelled,
        )
        changes.append(step_contracts.ClaimChange(claim=claim, decision=decision))
    return changes


def _propose_note_changes(
    execution: pipeline_specification.StepExecution,
    records: list[knowledge_record_models.Record],
) -> list[step_contracts.NoteChange]:
    name = execution.recipe.parameters.get("note_prompt_name")
    revision = execution.recipe.parameters.get("note_prompt_revision")
    notes = [
        record for record in records if isinstance(record.payload, knowledge_record_models.Note)
    ]
    if not notes:
        return []
    if not isinstance(name, str) or not isinstance(revision, int):
        raise ValueError("Note proposals require a pinned note_prompt_name and revision")
    prompt = prompt_registry.Prompt.model_validate(
        prompt_registry.get_revision("prompt", name, revision).payload
    ).text
    return [_propose_note_change(execution, record, records, prompt) for record in notes]


def _propose_note_change(
    execution: pipeline_specification.StepExecution,
    record: knowledge_record_models.Record,
    records: list[knowledge_record_models.Record],
    prompt: str,
) -> step_contracts.NoteChange:
    structured_generation.check_cancelled(execution.cancelled)
    note = cast(knowledge_record_models.Note, record.payload)
    command = note_revision_proposals.propose_note_revision(
        record,
        records,
        execution.output_directory,
        instructions=prompt,
        configuration=execution.recipe.model,
        cancelled=execution.cancelled,
    )
    body = command.proposal.note.body if command.proposal.note else note.body
    diff = "\n".join(
        difflib.unified_diff(
            note.body.splitlines(),
            body.splitlines(),
            fromfile="before",
            tofile="proposal",
        )
    )
    return step_contracts.NoteChange(command=command, diff=diff)
