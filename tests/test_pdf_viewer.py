"""Keep PDF viewing separate from the revision-pinned Zotero byte endpoint."""

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from knowledge import zotero
from knowledge.config import Settings
from knowledge.contracts import Source, ZoteroReference
from knowledge.web import create_app


@pytest.mark.parametrize("variant", ["original", "clean"])
def test_pdf_viewer_pins_revision_and_preserves_raw_endpoint(
    application, article, tmp_path, monkeypatch, variant
):
    reference = ZoteroReference(
        server_id="test-instance",
        item_key="LITERAT1",
        original_attachment_key="ORIGINAL",
        original_sha256=article.source.sha256,
        clean_attachment_key="CLEANPDF",
        clean_sha256=article.source.sha256,
    )
    source = Source(
        **article.source.model_dump(
            exclude={"bibliography", "original_path", "archive_path", "zotero"}
        ),
        zotero=reference,
    )
    with application.database.transaction() as ledger:
        first = ledger.append("pilot", "source", source, "test")
        ledger.append("pilot", "source", source, "test", first)
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"%PDF-test")
    monkeypatch.setattr(zotero, "verified_pdf", lambda source, variant: pdf)
    client = TestClient(create_app(Settings(application.database.database_url, tmp_path)))
    path = f"/sources/{first.entity_id}/{variant}"

    page = client.get(f"{path}/view?revision=1")
    assert page.status_code == 200
    assert f"file={quote(path + '?revision=1', safe='')}" in page.text
    assert f"/records/{first.entity_id}?revision=1" in page.text
    assert client.get(f"{path}?revision=1").content == b"%PDF-test"
    assert client.get(f"/sources/{first.entity_id}/invalid/view").status_code == 422

    viewer = client.get("/pdf-viewer/web/viewer.html")
    assert viewer.status_code == 200
    assert "viewer.mjs" in viewer.text
    assert client.get("/pdf-viewer/build/pdf.worker.mjs").status_code == 200
