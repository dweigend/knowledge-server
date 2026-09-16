"""Declare the canonical catalog of independently runnable experiment steps.

Each entry owns its label, dependencies, parameters, output schema, contract,
and executor so callers cannot observe inconsistent parallel registries.
"""

from knowledge.experiments import pipeline_specification
from knowledge.experiments.experiment_steps import (
    document_steps,
    knowledge_steps,
    step_contracts,
    writing_steps,
)
from knowledge.source_workflows import (
    information_block_extraction,
    knowledge_candidate_selection,
    source_grounded_writing,
    structured_paper_extraction,
)

STEP_DEFINITIONS = {
    definition.name: definition
    for definition in (
        pipeline_specification.StepDefinition(
            "extract_text",
            "PDF text",
            (),
            "extraction.v4",
            ("document_provider", "service_url", "literature_provider", "discovery"),
            information_block_extraction.TextExtraction,
            document_steps.extract_text,
            structured_paper_extraction.validate_paper_parameters,
        ),
        pipeline_specification.StepDefinition(
            "segment_blocks",
            "Information blocks",
            ("extract_text",),
            "blocks.v1",
            ("mode", "max_characters"),
            information_block_extraction.InformationBlocks,
            document_steps.segment_blocks,
            document_steps.validate_segmentation_parameters,
        ),
        pipeline_specification.StepDefinition(
            "formulate_claims",
            "Claims & evidence",
            ("extract_text", "segment_blocks"),
            "claims.v1",
            (),
            step_contracts.ClaimFormulation,
            document_steps.formulate_claims_from_blocks,
        ),
        pipeline_specification.StepDefinition(
            "find_knowledge",
            "Find knowledge",
            ("formulate_claims",),
            "retrieval.v1",
            ("query", "limit"),
            knowledge_candidate_selection.KnowledgeRetrieval,
            knowledge_steps.find_knowledge,
            knowledge_steps.validate_retrieval_parameters,
        ),
        pipeline_specification.StepDefinition(
            "select_entries",
            "Select entries",
            ("formulate_claims", "find_knowledge"),
            "selection.v1",
            ("query",),
            knowledge_candidate_selection.KnowledgeSelection,
            knowledge_steps.select_entries,
            knowledge_steps.validate_selection_parameters,
        ),
        pipeline_specification.StepDefinition(
            "propose_changes",
            "Propose changes",
            (
                "extract_text",
                "segment_blocks",
                "formulate_claims",
                "find_knowledge",
                "select_entries",
            ),
            "proposals.v1",
            ("note_prompt_name", "note_prompt_revision"),
            step_contracts.KnowledgeChanges,
            knowledge_steps.propose_changes,
        ),
        pipeline_specification.StepDefinition(
            "prepare_writing",
            "Cited points",
            ("extract_text", "segment_blocks", "formulate_claims", "propose_changes"),
            "writing_points.v1",
            ("goal",),
            source_grounded_writing.WritingPoints,
            writing_steps.prepare_writing,
            writing_steps.validate_writing_parameters,
        ),
        pipeline_specification.StepDefinition(
            "draft_text",
            "Write prose",
            ("extract_text", "segment_blocks", "prepare_writing"),
            "draft.v1",
            (),
            source_grounded_writing.WritingDraft,
            writing_steps.draft_text,
        ),
    )
}


def get_step_definition(name: str) -> pipeline_specification.StepDefinition:
    """Return one canonical definition or reject an unknown step."""
    try:
        return STEP_DEFINITIONS[name]
    except KeyError as error:
        raise ValueError("Unknown experiment step") from error
