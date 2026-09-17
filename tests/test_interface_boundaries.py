import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from knowledge.command_interfaces.knowledge_cli import export_batch
from knowledge.knowledge_base.knowledge_service import Knowledge
from knowledge.knowledge_domain.knowledge_record_models import Claim, Note
from knowledge.runtime_support.environment_settings import Settings
from knowledge.web_interface.fastapi_app import create_app


def test_note_edit_and_export_preserve_revision_history(
    application: Knowledge, tmp_path: Path
) -> None:
    with application.database.transaction() as ledger:
        claim = ledger.append(
            "pilot",
            "claim",
            Claim(proposition="Observation", scope="Local", qualifications="None"),
            "human:local",
        )
    note = Note(kind="inbox", title="Überblick", body="Original", references=[claim])
    reference = application.propose_note("create", "pilot", note, "human:local")[0]
    client = TestClient(
        create_app(Settings(database_url=application.database.database_url, archive_root=tmp_path))
    )
    path = f"/records/{reference.entity_id}"
    page = client.get(path)
    token = re.search(r'name="csrf" value="([^"]+)"', page.text)
    assert token is not None
    form = {"csrf": token[1], "revision": "1", "request_id": "edit"}
    for invalid in ("{", '{"title":"Incomplete"}'):
        assert client.post(f"{path}/edit", data={**form, "content": invalid}).status_code == 422
    assert len(application.history(reference.entity_id)) == 1
    note.body = "Überarbeitet"
    response = client.post(f"{path}/edit", data={**form, "content": note.model_dump_json()})
    assert response.status_code == 200
    assert "Überarbeitet" in response.text
    assert "Revision 1" in response.text and "Revision 2" in response.text
    output = tmp_path / "export"
    export_batch(application, "pilot", output)
    history = json.loads((output / f"note-{reference.entity_id}.json").read_text())
    assert [record["revision"] for record in history] == [1, 2]
    assert [record["payload"]["body"] for record in history] == ["Original", "Überarbeitet"]
    assert (
        output / f"note-{reference.entity_id}.md"
    ).read_text() == "# Überblick\n\nÜberarbeitet\n"
