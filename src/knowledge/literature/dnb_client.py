"""Retrieve edition-level DNB catalog records through SRU and MARC21 XML."""

import re
from collections.abc import Callable
from typing import Final
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

from knowledge.literature.bibliographic_identifiers import extracted_isbn
from knowledge.literature.crossref_client import normalize_doi
from knowledge.literature.literature_models import Candidate, LiteratureMetadata
from knowledge.literature.literature_resolution import author_surname
from knowledge.literature.provider_http import MAX_CANDIDATES, request_bytes
from knowledge.literature.structured_paper_models import PaperMetadata

API_URL: Final[str] = "https://services.dnb.de/sru/dnb"
MARC: Final[str] = "{http://www.loc.gov/MARC21/slim}"


def lookup_dnb(
    reference: PaperMetadata, timeout_seconds: float, cancelled: Callable[[], bool]
) -> list[Candidate]:
    """Look up a literal ISBN or search title, first author and year."""
    isbn = extracted_isbn(reference)
    if not reference.title and not isbn:
        return []
    query = urlencode(
        {
            "version": "1.1",
            "operation": "searchRetrieve",
            "query": "num=" + isbn if isbn else _bibliographic_query(reference),
            "recordSchema": "MARC21-xml",
            "maximumRecords": MAX_CANDIDATES,
        }
    )
    response = request_bytes(
        API_URL + "?" + query, timeout_seconds, cancelled, accept="application/xml"
    )
    candidates = parse_candidates(response) if response else []
    for candidate in candidates:
        if isbn:
            candidate.method = "isbn"
    return candidates


def _bibliographic_query(reference: PaperMetadata) -> str:
    clauses = ["tit=" + _cql_phrase(reference.title or "")]
    if reference.authors and reference.authors[0].strip():
        author = reference.authors[0]
        surname = author_surname(author)
        clauses.append("per=" + _cql_phrase(surname))
    if reference.year and re.fullmatch(r"\d{4}", reference.year):
        clauses.append("jhr=" + reference.year)
    return " and ".join(clauses)


def parse_candidates(response: bytes) -> list[Candidate]:
    """Parse MARC records and surface SRU diagnostics instead of hiding failures."""
    if b"<!DOCTYPE" in response.upper() or b"<!ENTITY" in response.upper():
        raise ValueError("DNB returned XML containing forbidden declarations")
    try:
        root = ET.fromstring(response)
    except ET.ParseError:
        raise ValueError("DNB returned invalid XML") from None
    if root.find(".//{http://www.loc.gov/zing/srw/diagnostic/}diagnostic") is not None:
        raise ValueError("DNB returned an SRU diagnostic; check the search query")
    if root.tag != "{http://www.loc.gov/zing/srw/}searchRetrieveResponse":
        raise ValueError("DNB returned an unexpected XML document")
    return [_candidate(record) for record in root.findall(f".//{MARC}record")[:MAX_CANDIDATES]]


def _candidate(record: ET.Element) -> Candidate:
    identifier = record.findtext(f"{MARC}controlfield[@tag='001']")
    if not identifier:
        raise ValueError("DNB record is missing its catalog identifier")
    publication = _subfields(record, "264", "c") or _subfields(record, "260", "c")
    years = re.findall(r"\b[12]\d{3}\b", " ".join(publication))
    authors = _authors(record)
    title = " : ".join(_subfields(record, "245", "a") + _subfields(record, "245", "b"))
    return Candidate(
        provider="dnb",
        provider_id=identifier,
        method="bibliographic",
        metadata=LiteratureMetadata(
            title=title or None,
            authors=authors,
            year=years[0] if len(set(years)) == 1 else None,
            publisher=next(
                iter(_subfields(record, "264", "b") or _subfields(record, "260", "b")), None
            ),
            isbn=_subfields(record, "020", "a"),
            doi=_doi(record),
            venue=next(iter(_subfields(record, "773", "t")), None),
            work_type="book-chapter"
            if record.find(f"{MARC}datafield[@tag='773']") is not None
            else _record_type(record),
            url="https://d-nb.info/" + identifier,
        ),
    )


def _authors(record: ET.Element) -> list[str]:
    authors = []
    for field in record.findall(f"{MARC}datafield"):
        if field.get("tag") not in {"100", "700"}:
            continue
        roles = {entry.text for entry in field.findall(f"{MARC}subfield[@code='4']")}
        if roles and "aut" not in roles:
            continue
        relationship = field.findtext(f"{MARC}subfield[@code='e']", "").casefold()
        if not roles and relationship in {"herausgeber", "editor", "hrsg."}:
            continue
        name = field.findtext(f"{MARC}subfield[@code='a']")
        if name:
            surname, separator, given = name.partition(",")
            authors.append(f"{given.strip()} {surname.strip()}" if separator else name.strip())
    return authors


def _record_type(record: ET.Element) -> str | None:
    leader = record.findtext(f"{MARC}leader", "")
    return "book" if len(leader) > 7 and leader[7] == "m" else None


def _doi(record: ET.Element) -> str | None:
    for field in record.findall(f"{MARC}datafield[@tag='024']"):
        if field.findtext(f"{MARC}subfield[@code='2']", "").lower() == "doi":
            return normalize_doi(field.findtext(f"{MARC}subfield[@code='a']"))
    return None


def _subfields(record: ET.Element, tag: str, code: str) -> list[str]:
    path = f"{MARC}datafield[@tag='{tag}']/{MARC}subfield[@code='{code}']"
    return [entry.text.strip(" /:;") for entry in record.findall(path) if entry.text]


def _cql_phrase(text: str) -> str:
    return '"' + text[:500].replace("\\", "\\\\").replace('"', '\\"') + '"'
