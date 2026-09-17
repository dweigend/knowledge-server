"""Define the small execution contract shared by experiment steps.

The runner consumes immutable step definitions instead of knowing individual
workflow implementations or maintaining parallel metadata tables.
"""

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue

from knowledge.experiments.experiment_steps import step_contracts
from knowledge.knowledge_domain import knowledge_record_models
from knowledge.model_integration import prompt_registry, structured_generation
from knowledge.source_workflows import (
    information_block_extraction,
    knowledge_candidate_selection,
    source_grounded_writing,
)


class StepInputs(BaseModel):
    """Keep loaded dependency outputs typed throughout one execution."""

    model_config = ConfigDict(extra="forbid")

    extract_text: information_block_extraction.TextExtraction | None = None
    segment_blocks: information_block_extraction.InformationBlocks | None = None
    formulate_claims: step_contracts.ClaimFormulation | None = None
    find_knowledge: knowledge_candidate_selection.KnowledgeRetrieval | None = None
    select_entries: knowledge_candidate_selection.KnowledgeSelection | None = None
    propose_changes: step_contracts.KnowledgeChanges | None = None
    prepare_writing: source_grounded_writing.WritingPoints | None = None


class StepExecution(BaseModel):
    """Supply one step with its pinned inputs and isolated output location."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True, frozen=True)

    pdf: Path
    inputs: StepInputs
    knowledge: list[knowledge_record_models.Record]
    recipe: prompt_registry.Recipe
    prompt_text: str
    author_rules: prompt_registry.AuthorRules | None
    output_directory: Path
    cancelled: Callable[[], bool]


StepExecutor = Callable[[StepExecution], knowledge_record_models.Contract]
ParameterValidator = Callable[[dict[str, JsonValue]], None]


class StepDefinition(BaseModel):
    """Describe and execute one independently runnable experiment step."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True, frozen=True)

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
        if any(getattr(execution.inputs, name, None) is None for name in self.dependencies):
            raise ValueError("Step is missing required input revisions")
        structured_generation.check_cancelled(execution.cancelled)
        return self.executor(execution)
