"""Read literature metadata and manage PDF attachments through Zotero.

The adapter treats Zotero as the literature authority, verifies attachment hashes,
and isolates local API details from domain workflows.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Final
from urllib.error import HTTPError
from urllib.parse import unquote, urlencode, urlparse
from urllib.request import Request, urlopen

from pydantic import TypeAdapter

from knowledge.knowledge_domain import knowledge_record_models as models
from knowledge.literature import zotero_models as responses

BASE_URL: Final[str] = os.environ.get("KNOWLEDGE_ZOTERO_URL", "http://127.0.0.1:23119").rstrip("/")


def server_id() -> str:
    """Identify the library instance before trusting persisted Zotero keys."""
    with urlopen(BASE_URL + "/api/", timeout=30) as response:
        identity = response.headers.get("Zotero-Server-ID")
        if not isinstance(identity, str) or not identity:
            raise ValueError("Zotero response lacks its server identity")
        return identity


def fetch(path: str, instance: str | None = None) -> object:
    """Read JSON, optionally rejecting a different Zotero library instance."""
    headers = {"Zotero-Server-ID": instance} if instance else {}
    with urlopen(Request(BASE_URL + path, headers=headers), timeout=30) as response:
        return json.load(response)


def write(path: str, content: bytes, content_type: str, instance: str, **headers: str) -> object:
    """Make an authorized local API write without exposing the key in request URLs."""
    request = Request(
        BASE_URL + path,
        data=content,
        headers={
            "Content-Type": content_type,
            "Zotero-Server-ID": instance,
            "Zotero-API-Key": os.environ["KNOWLEDGE_ZOTERO_API_KEY"],
            **headers,
        },
    )
    with urlopen(request, timeout=60) as response:
        body = response.read()
    return json.loads(body) if body else {}


def item_data(reference: models.ZoteroReference) -> responses.ItemData:
    """Read current literature metadata directly from its pinned Zotero instance."""
    item = fetch(f"/api/{reference.library}/items/{reference.item_key}", reference.server_id)
    return responses.Item.model_validate(item).data


def get_bibliography(
    source: models.Source | models.LegacySource | models.ZoteroReference,
) -> models.Bibliography:
    """Resolve current Zotero metadata, including historical source references."""
    if isinstance(source, models.LegacySource):
        item = fetch(f"/api/users/0/items/{source.bibliography.zotero_key}")
        metadata = responses.Item.model_validate(item).data
    else:
        reference = source if isinstance(source, models.ZoteroReference) else source.zotero
        metadata = item_data(reference)
    if not {"key", "title"} <= metadata.model_fields_set:
        raise ValueError("Zotero bibliography requires key and title")
    return models.Bibliography(
        title=metadata.title,
        authors=[
            creator.name or " ".join(filter(None, [creator.firstName, creator.lastName]))
            for creator in metadata.creators
        ],
        year=metadata.date,
        doi=metadata.DOI,
        url=metadata.url,
        zotero_key=metadata.key,
        zotero_library="server-pilot:users/0",
        zotero_version=metadata.version,
    )


def attachment_path(library: str, key: str, instance: str) -> Path:
    """Resolve Zotero's stored attachment URL without copying the PDF."""
    request = Request(
        BASE_URL + f"/api/{library}/items/{key}/file/view/url",
        headers={"Zotero-Server-ID": instance},
    )
    with urlopen(request, timeout=30) as response:
        location = urlparse(response.read().decode().strip())
    if location.scheme != "file" or location.netloc not in {"", "localhost"}:
        raise ValueError("Zotero returned a nonlocal attachment URL")
    return Path(unquote(location.path))


def verified_pdf(reference: models.ZoteroReference, variant: str) -> Path:
    """Reject missing or replaced PDF bytes instead of silently changing a citation."""
    if variant not in {"original", "clean"}:
        raise ValueError("Unknown PDF variant")
    key = getattr(reference, f"{variant}_attachment_key")
    expected = getattr(reference, f"{variant}_sha256")
    try:
        path = attachment_path(reference.library, key, reference.server_id)
    except HTTPError as error:
        raise ValueError(
            "The cited Zotero attachment is unavailable; its text snapshot is preserved"
        ) from error
    if not path.is_file():
        raise ValueError("The cited PDF is missing from Zotero; its text snapshot is preserved")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("Zotero PDF changed; the stored citation refers to an earlier version")
    return path


def matching_attachment(item_key: str, pdf: Path, instance: str) -> str | None:
    """Reuse a stored attachment only when its bytes match the supplied PDF."""
    children = fetch(f"/api/users/0/items/{item_key}/children", instance)
    expected = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if not isinstance(children, list):
        raise ValueError("Zotero children response is not a list")
    attachments = TypeAdapter(list[responses.Item]).validate_python(children)
    if any(not attachment.key for attachment in attachments):
        raise ValueError("Zotero attachment requires a nonempty key")
    for child in attachments:
        metadata = child.data
        if metadata.contentType != "application/pdf":
            continue
        if metadata.linkMode not in {"imported_file", "imported_url"}:
            continue
        actual_hash = attachment_hash(child.key, instance)
        if actual_hash == expected:
            return child.key
        pending_tag = responses.Tag(tag=f"knowledge-pilot-sha256:{expected}")
        if actual_hash is None and pending_tag in metadata.tags:
            upload_attachment(child.key, pdf, instance)
            return child.key
    return None


def attachment_hash(key: str, instance: str) -> str | None:
    """Distinguish an unfinished upload from an unavailable Zotero service."""
    try:
        path = attachment_path("users/0", key, instance)
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def add_attachment(item_key: str, pdf: Path, instance: str) -> str:
    """Create a stored attachment beneath an existing literature item."""
    existing = matching_attachment(item_key, pdf, instance)
    if existing:
        return existing
    pdf_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    result = write(
        "/api/users/0/items",
        json.dumps(
            [
                {
                    "itemType": "attachment",
                    "parentItem": item_key,
                    "linkMode": "imported_file",
                    "title": pdf.name,
                    "contentType": "application/pdf",
                    "filename": pdf.name,
                    "tags": [{"tag": f"knowledge-pilot-sha256:{pdf_hash}"}],
                }
            ]
        ).encode(),
        "application/json",
        instance,
    )
    key = responses.WriteResult.model_validate(result).successful["0"].key
    upload_attachment(key, pdf, instance)
    return key


def upload_attachment(key: str, pdf: Path, instance: str) -> None:
    """Upload attachment bytes using Zotero's documented three-phase local upload."""
    content = pdf.read_bytes()
    endpoint = f"/api/users/0/items/{key}/file"
    parameters = {
        "md5": hashlib.md5(content).hexdigest(),
        "filename": pdf.name,
        "filesize": len(content),
        "mtime": int(pdf.stat().st_mtime * 1000),
    }
    upload = write(
        endpoint,
        urlencode(parameters).encode(),
        "application/x-www-form-urlencoded",
        instance,
        **{"If-None-Match": "*"},
    )
    authorization = responses.UploadAuthorization.model_validate(upload)
    if authorization.exists:
        return
    if not authorization.url.startswith(BASE_URL + "/api/local/uploads/"):
        raise ValueError("Zotero returned an unexpected upload destination")
    request = Request(
        authorization.url, data=content, headers={"Content-Type": authorization.contentType}
    )
    with urlopen(request, timeout=60) as response:
        response.read()
    write(
        endpoint,
        urlencode({"upload": authorization.uploadKey}).encode(),
        "application/x-www-form-urlencoded",
        instance,
        **{"If-None-Match": "*"},
    )


def import_sources(
    bibliography: models.Bibliography, original_pdf: Path, clean_pdf: Path, batch_id: str
) -> models.ZoteroReference:
    """Store literature once in Zotero and pin both PDF versions by content hash."""
    instance = server_id()
    original_hash = hashlib.sha256(original_pdf.read_bytes()).hexdigest()
    item_key = bibliography.zotero_key or find_or_import_item(
        bibliography, clean_pdf, original_hash, batch_id
    )
    original_key = add_attachment(item_key, original_pdf, instance)
    clean_key = add_attachment(item_key, clean_pdf, instance)
    reference = models.ZoteroReference(
        server_id=instance,
        item_key=item_key,
        original_attachment_key=original_key,
        original_sha256=original_hash,
        clean_attachment_key=clean_key,
        clean_sha256=hashlib.sha256(clean_pdf.read_bytes()).hexdigest(),
    )
    verified_pdf(reference, "original")
    verified_pdf(reference, "clean")
    return reference


def find_or_import_item(
    bibliography: models.Bibliography, clean_pdf: Path, source_hash: str, batch_id: str
) -> str:
    """Reconcile one tagged literature item before creating any additional attachments."""
    tag = f"knowledge-pilot:{batch_id}:{source_hash}"
    query = urlencode({"tag": tag, "itemType": "-attachment", "limit": 100})
    existing = fetch(f"/api/users/0/items?{query}")
    if not existing:
        import_ris(bibliography, clean_pdf, tag)
        existing = fetch(f"/api/users/0/items?{query}")
    if not isinstance(existing, list) or len(existing) != 1:
        raise ValueError("Zotero import not reconciled to exactly one tagged source")
    return responses.ItemKey.model_validate(existing[0]).key


def import_ris(bibliography: models.Bibliography, clean_pdf: Path, tag: str) -> None:
    """Import one tagged reference and its PDF with Zotero's existing RIS translator."""
    lines = ["TY  - GEN", f"TI  - {bibliography.title}"]
    lines.extend(f"AU  - {author}" for author in bibliography.authors)
    lines.extend(
        f"{key}  - {field}"
        for key, field in (
            ("PY", bibliography.year),
            ("DO", bibliography.doi),
            ("UR", bibliography.url),
        )
        if field
    )
    lines.extend([f"KW  - {tag}", f"L1  - {clean_pdf}", "ER  - ", ""])
    request = Request(
        BASE_URL + "/connector/import?" + urlencode({"session": tag}),
        data="\n".join(lines).encode(),
        headers={"Content-Type": "text/plain"},
    )
    with urlopen(request, timeout=60) as response:
        response.read()


def article_citation(reference: models.ZoteroReference) -> responses.Item:
    """Read current metadata and Zotero-rendered citation exports without persisting copies."""
    query = urlencode({"include": "data,bib,bibtex", "style": "apa", "linkwrap": 0})
    item = fetch(
        f"/api/{reference.library}/items/{reference.item_key}?{query}", reference.server_id
    )
    if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
        raise ValueError("Zotero item response lacks literature metadata")
    return responses.Item.model_validate(item)
