"""Declare the canonical catalog of independently runnable experiment steps.

Each entry owns its label, dependencies, parameters, output schema, contract,
and executor so callers cannot observe inconsistent parallel registries.
"""

from typing import Final

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

STEP_DEFINITIONS: Final[dict[str, pipeline_specification.StepDefinition]] = {
    definition.name: definition
    for definition in (
        pipeline_specification.StepDefinition(
            name="extract_text",
            dashboard_label="PDF text",
            dependencies=(),
            output_schema="extraction.v4",
            allowed_parameters=(
                "document_provider",
                "service_url",
                "literature_provider",
                "discovery",
            ),
            output_contract=information_block_extraction.TextExtraction,
            executor=document_steps.extract_text,
            parameter_validator=structured_paper_extraction.validate_paper_parameters,
        ),
        pipeline_specification.StepDefinition(
            name="segment_blocks",
            dashboard_label="Information blocks",
            dependencies=("extract_text",),
            output_schema="blocks.v1",
            allowed_parameters=("mode", "max_characters"),
            output_contract=information_block_extraction.InformationBlocks,
            executor=document_steps.segment_blocks,
            parameter_validator=document_steps.validate_segmentation_parameters,
        ),
        pipeline_specification.StepDefinition(
            name="formulate_claims",
            dashboard_label="Claims & evidence",
            dependencies=("extract_text", "segment_blocks"),
            output_schema="claims.v1",
            allowed_parameters=(),
            output_contract=step_contracts.ClaimFormulation,
            executor=document_steps.formulate_claims_from_blocks,
        ),
        pipeline_specification.StepDefinition(
            name="find_knowledge",
            dashboard_label="Find knowledge",
            dependencies=("formulate_claims",),
            output_schema="retrieval.v1",
            allowed_parameters=("query", "limit"),
            output_contract=knowledge_candidate_selection.KnowledgeRetrieval,
            executor=knowledge_steps.find_knowledge,
            parameter_validator=knowledge_steps.validate_retrieval_parameters,
        ),
        pipeline_specification.StepDefinition(
            name="select_entries",
            dashboard_label="Select entries",
            dependencies=("formulate_claims", "find_knowledge"),
            output_schema="selection.v1",
            allowed_parameters=("query",),
            output_contract=knowledge_candidate_selection.KnowledgeSelection,
            executor=knowledge_steps.select_entries,
            parameter_validator=knowledge_steps.validate_selection_parameters,
        ),
        pipeline_specification.StepDefinition(
            name="propose_changes",
            dashboard_label="Propose changes",
            dependencies=(
                "extract_text",
                "segment_blocks",
                "formulate_claims",
                "find_knowledge",
                "select_entries",
            ),
            output_schema="proposals.v1",
            allowed_parameters=("note_prompt_name", "note_prompt_revision"),
            output_contract=step_contracts.KnowledgeChanges,
            executor=knowledge_steps.propose_changes,
        ),
        pipeline_specification.StepDefinition(
            name="prepare_writing",
            dashboard_label="Cited points",
            dependencies=(
                "extract_text",
                "segment_blocks",
                "formulate_claims",
                "propose_changes",
            ),
            output_schema="writing_points.v1",
            allowed_parameters=("goal",),
            output_contract=source_grounded_writing.WritingPoints,
            executor=writing_steps.prepare_writing,
            parameter_validator=writing_steps.validate_writing_parameters,
        ),
        pipeline_specification.StepDefinition(
            name="draft_text",
            dashboard_label="Write prose",
            dependencies=("extract_text", "segment_blocks", "prepare_writing"),
            output_schema="draft.v1",
            allowed_parameters=(),
            output_contract=source_grounded_writing.WritingDraft,
            executor=writing_steps.draft_text,
        ),
    )
}


def get_step_definition(name: str) -> pipeline_specification.StepDefinition:
    """Return one canonical definition or reject an unknown step."""
    try:
        return STEP_DEFINITIONS[name]
    except KeyError as error:
        raise ValueError("Unknown experiment step") from error
