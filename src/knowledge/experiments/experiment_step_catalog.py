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
from knowledge.knowledge_domain import knowledge_record_models
from knowledge.source_workflows import (
    information_block_extraction,
    knowledge_candidate_selection,
    source_grounded_writing,
)


def _definition(
    name: str,
    label: str,
    dashboard_label: str,
    dependencies: tuple[str, ...],
    output_schema: str,
    allowed_parameters: tuple[str, ...],
    output_contract: type[knowledge_record_models.Contract],
    executor: pipeline_specification.StepExecutor,
    parameter_validator: pipeline_specification.ParameterValidator | None = None,
) -> pipeline_specification.StepDefinition:
    return pipeline_specification.StepDefinition(
        name=name,
        label=label,
        dashboard_label=dashboard_label,
        dependencies=dependencies,
        output_schema=output_schema,
        allowed_parameters=frozenset(allowed_parameters),
        output_contract=output_contract,
        executor=executor,
        **({"parameter_validator": parameter_validator} if parameter_validator else {}),
    )


STEP_DEFINITIONS = {
    definition.name: definition
    for definition in (
        _definition(
            "extract_text",
            "Extract PDF text",
            "PDF text",
            (),
            "extraction.v3",
            ("document_provider", "service_url", "literature_provider"),
            information_block_extraction.TextExtraction,
            document_steps.extract_text,
            document_steps.validate_extraction_parameters,
        ),
        _definition(
            "segment_blocks",
            "Segment information blocks",
            "Information blocks",
            ("extract_text",),
            "blocks.v1",
            ("mode", "max_characters"),
            information_block_extraction.InformationBlocks,
            document_steps.segment_blocks,
            document_steps.validate_segmentation_parameters,
        ),
        _definition(
            "formulate_claims",
            "Formulate claims",
            "Claims & evidence",
            ("extract_text", "segment_blocks"),
            "claims.v1",
            (),
            step_contracts.ClaimFormulation,
            document_steps.formulate_claims_from_blocks,
        ),
        _definition(
            "find_knowledge",
            "Find existing knowledge",
            "Find knowledge",
            ("formulate_claims",),
            "retrieval.v1",
            ("query", "limit"),
            knowledge_candidate_selection.KnowledgeRetrieval,
            knowledge_steps.find_knowledge,
            knowledge_steps.validate_retrieval_parameters,
        ),
        _definition(
            "select_entries",
            "Select relevant entries",
            "Select entries",
            ("formulate_claims", "find_knowledge"),
            "selection.v1",
            ("query",),
            knowledge_candidate_selection.KnowledgeSelection,
            knowledge_steps.select_entries,
            knowledge_steps.validate_selection_parameters,
        ),
        _definition(
            "propose_changes",
            "Propose evidenced changes",
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
        _definition(
            "prepare_writing",
            "Prepare cited writing points",
            "Cited points",
            ("extract_text", "segment_blocks", "formulate_claims", "propose_changes"),
            "writing_points.v1",
            ("goal",),
            source_grounded_writing.WritingPoints,
            writing_steps.prepare_writing,
            writing_steps.validate_writing_parameters,
        ),
        _definition(
            "draft_text",
            "Draft prose",
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


def execute_step(
    name: str, execution: pipeline_specification.StepExecution
) -> knowledge_record_models.Contract:
    """Execute one step through its canonical definition."""
    return get_step_definition(name).execute(execution)
