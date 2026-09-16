"""Run the original bounded document pilot through the standard import workflow.

The pilot selects its fixed manifest and delegates source and knowledge handling
to the shared production operations.
"""

import os
from pathlib import Path

from knowledge.knowledge_base import knowledge_service
from knowledge.revision_store import postgresql_revision_store
from knowledge.runtime_support import environment_settings
from knowledge.source_workflows import source_import

FILENAMES = [
    "01_noy_zhang_productivity_2023.pdf",
    "02_hepi_student_ai_survey_2026.pdf",
    "04_soderstrom_bjork_learning_vs_performance_2015.pdf",
    "05_bjork_dunlosky_kornell_learning_illusions_2013.pdf",
    "06_bastani_guardrails_learning_2025.pdf",
    "07_kestin_ai_tutoring_2025.pdf",
    "09_chapter_cognitive_tutors_2005.pdf",
    "10_chapter_self_explaining_2019.pdf",
    "11_chapter_technology_enhanced_feedback_2018.pdf",
    "12_chapter_interest_development_2019.pdf",
]


def run_pilot(settings: environment_settings.Settings, batch_id: str, limit: int = 10) -> None:
    """Import the selected PDFs; consolidation remains an explicit separate command."""
    source_directory = Path(os.environ["KNOWLEDGE_PILOT_SOURCE_DIRECTORY"]).expanduser()
    application = knowledge_service.Knowledge(
        postgresql_revision_store.Database(settings.database_url)
    )
    application.create_batch(batch_id, "KI, Lernen und Leistung — zehn Fachtexte")
    run_directory = settings.archive_root / batch_id / "pilot-import"
    for filename in FILENAMES[:limit]:
        document = source_import.ImportDocument(
            path=str(source_directory / filename), remove_cover=True
        )
        source_import.import_document(application, batch_id, document, run_directory)
