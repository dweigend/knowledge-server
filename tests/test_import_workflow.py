"""Metadata reconciliation preserves known fields while filling later imprint details."""

import json
from pathlib import Path

from knowledge.knowledge_domain.knowledge_record_models import Bibliography
from knowledge.source_workflows.article_claim_extraction import (
    ArticleExtraction,
    merge_extracted_metadata,
)


def extraction(bibliography: Bibliography) -> ArticleExtraction:
    return ArticleExtraction(
        bibliography=bibliography, claims=[], study_group="Report", overlap="Unknown", warnings=[]
    )


def test_metadata_fills_gaps_logs_conflicts_and_drops_model_zotero_keys(tmp_path: Path) -> None:
    first = Bibliography(
        title="Report",
        authors=[],
        year="",
        doi="",
        url="",
        zotero_key="UNTRUSTED",
        zotero_library="other",
        zotero_version=9,
    )
    imprint = Bibliography(
        title="Report", authors=["Frauke Bilger", "Eva Koubek"], year="2024", doi="", url=""
    )
    conflict = imprint.model_copy(update={"title": "Another title", "year": "2025"})
    merged = merge_extracted_metadata(
        [extraction(first), extraction(imprint), extraction(imprint), extraction(conflict)],
        tmp_path,
    )
    assert merged.title == "Report"
    assert merged.authors == ["Frauke Bilger", "Eva Koubek"]
    assert merged.year == "2024"
    assert (merged.zotero_key, merged.zotero_library, merged.zotero_version) == ("", "", 0)
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    assert [event["field"] for event in events] == ["title", "year"]
    assert events[1]["distinct_values"] == ["2024", "2025"]
    assert events[1]["retained"] == "2024"
