"""Retrieve bounded Crossref candidates without coupling identity rules to HTTP."""

import json
import re
import subprocess
from collections.abc import Callable
from time import monotonic
from urllib.parse import quote, urlencode

from knowledge.literature_contracts import Candidate, LiteratureMetadata
from knowledge.paper_contracts import PaperMetadata, PaperReference

API_URL = "https://api.crossref.org/works"
MAX_RESPONSE_BYTES = 2_000_000
USER_AGENT = "knowledge-server/0.1 (https://github.com/dweigend/knowledge-server)"


def normalize_doi(doi: str | None) -> str | None:
    """Normalize DOI wrappers while retaining the identifier's actual suffix."""
    cleaned = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi or "", flags=re.I)
    cleaned = cleaned.strip().lower()
    return cleaned if re.fullmatch(r"10\.\d{4,9}/\S+", cleaned) else None


def lookup_crossref(
    reference: PaperMetadata, timeout_seconds: float, cancelled: Callable[[], bool]
) -> list[Candidate]:
    """Look up an exact DOI or retrieve at most three bibliographic candidates."""
    doi = normalize_doi(reference.doi)
    if doi:
        url = API_URL + "/" + quote(doi, safe="")
        method = "doi"
    else:
        raw = reference.raw if isinstance(reference, PaperReference) else None
        query = raw or " ".join(filter(None, [reference.title, *reference.authors, reference.year]))
        if not query:
            return []
        url = API_URL + "?" + urlencode({"query.bibliographic": query[:2000], "rows": 3})
        method = "bibliographic"
    response = request_json(url, timeout_seconds, cancelled)
    if response is None:
        return []
    message = response["message"]
    entries = [message] if method == "doi" else message["items"]
    return [
        Candidate(
            metadata=parse_metadata(entry),
            provider="crossref",
            provider_id=entry["DOI"],
            method=method,
        )
        for entry in entries[:3]
    ]


def request_json(url: str, timeout_seconds: float, cancelled: Callable[[], bool]) -> dict | None:
    """Bound HTTP time and size while checking cancellation during transfer."""
    deadline = monotonic() + timeout_seconds
    arguments = [
        "curl",
        "--disable",
        "--silent",
        "--show-error",
        "--proto",
        "=https",
        "--max-time",
        str(timeout_seconds),
        "--max-filesize",
        str(MAX_RESPONSE_BYTES),
        "--user-agent",
        USER_AGENT,
        "--header",
        "Accept: application/json",
        "--write-out",
        "\n%{http_code}",
        url,
    ]
    with subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        try:
            output = read_response(process, deadline, cancelled)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        if process.returncode:
            raise ValueError("Crossref request failed or exceeded its response limits")
    body, _, status = output.rpartition(b"\n")
    if status == b"404":
        return None
    if status != b"200":
        raise ValueError(f"Crossref returned HTTP {status.decode(errors='replace')}")
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("Crossref response exceeded its size limit")
    return json.loads(body)


def read_response(
    process: subprocess.Popen[bytes], deadline: float, cancelled: Callable[[], bool]
) -> bytes:
    """Collect a response while preserving prompt cancellation and a total deadline."""
    while True:
        if cancelled():
            raise InterruptedError("Literature lookup cancelled")
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("Crossref lookup exceeded its time limit")
        try:
            output, _ = process.communicate(timeout=min(0.2, remaining))
            return output
        except subprocess.TimeoutExpired:
            continue


def parse_metadata(entry: dict) -> LiteratureMetadata:
    """Normalize deposited Crossref metadata without filling absent fields."""
    year = publication_year(entry)
    return LiteratureMetadata(
        title=next(iter(entry.get("title", [])), None),
        authors=[
            " ".join(filter(None, [author.get("given"), author.get("family")]))
            or author.get("name", "")
            for author in entry.get("author", [])
        ],
        year=year,
        venue=next(iter(entry.get("container-title", [])), None),
        doi=normalize_doi(entry.get("DOI")),
        publisher=entry.get("publisher"),
        volume=entry.get("volume"),
        issue=entry.get("issue"),
        pages=entry.get("page"),
        work_type=entry.get("type"),
        url=entry.get("URL"),
        isbn=entry.get("ISBN", []),
        issn=entry.get("ISSN", []),
    )


def publication_year(entry: dict) -> str | None:
    """Select a supplied publication year, excluding metadata deposit timestamps."""
    for field in ("published", "published-print", "published-online", "issued"):
        dates = entry.get(field, {}).get("date-parts", [])
        if dates and dates[0] and type(dates[0][0]) is int and 1000 <= dates[0][0] <= 9999:
            return str(dates[0][0])
    return None
