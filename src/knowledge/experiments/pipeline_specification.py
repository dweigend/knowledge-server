"""Define the small execution contract shared by experiment steps.

The runner consumes immutable step definitions instead of knowing individual
workflow implementations or maintaining parallel metadata tables.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from pydantic import JsonValue

from knowledge.experiments.experiment_steps import step_contracts
from knowledge.knowledge_domain import knowledge_record_models
from knowledge.model_integration import prompt_registry, structured_generation
from knowledge.source_workflows import (
    information_block_extraction,
    knowledge_candidate_selection,
    source_grounded_writing,
)


class StepInputs(TypedDict, total=False):
    """Keep loaded dependency outputs typed throughout one execution."""

    extract_text: information_block_extraction.TextExtraction
    segment_blocks: information_block_extraction.InformationBlocks
    formulate_claims: step_contracts.ClaimFormulation
    find_knowledge: knowledge_candidate_selection.KnowledgeRetrieval
    select_entries: knowledge_candidate_selection.KnowledgeSelection
    propose_changes: step_contracts.KnowledgeChanges
    prepare_writing: source_grounded_writing.WritingPoints


@dataclass(frozen=True)
class StepExecution:
    """Supply one step with its pinned inputs and isolated output location."""

    pdf: Path
    inputs: StepInputs
    knowledge: list[knowledge_record_models.Record]
    recipe: prompt_registry.Recipe
    prompt_text: str
    author_rules: dict[str, JsonValue] | None
    output_directory: Path
    cancelled: Callable[[], bool]


StepExecutor = Callable[[StepExecution], knowledge_record_models.Contract]
ParameterValidator = Callable[[dict[str, JsonValue]], None]


@dataclass(frozen=True)
class StepDefinition:
    """Describe and execute one independently runnable experiment step."""

    name: str
    dashboard_label: str
    dependencies: tuple[str, ...]
    output_schema: str
    allowed_parameters: tuple[str, ...]
    output_contract: type[knowledge_record_models.Contract]
    executor: StepExecutor
    parameter_validator: ParameterValidator | None = None

    def validate_recipe(self, recipe: prompt_registry.Recipe) -> None:
        """Reject recipes that do not exactly match this step's contract."""
        if recipe.step != self.name:
            raise ValueError("Recipe does not match a supported step")
        if recipe.output_schema != self.output_schema:
            raise ValueError("Recipe output schema does not match the step's supported format")
        unknown = set(recipe.parameters).difference(self.allowed_parameters)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"Unsupported parameters for {self.name}: {names}")
        if self.parameter_validator is not None:
            self.parameter_validator(recipe.parameters)

    def execute(self, execution: StepExecution) -> knowledge_record_models.Contract:
        """Validate pins and delegate one step to its focused executor."""
        self.validate_recipe(execution.recipe)
        if any(name not in execution.inputs for name in self.dependencies):
            raise ValueError("Step is missing required input revisions")
        structured_generation.check_cancelled(execution.cancelled)
        return self.executor(execution)
