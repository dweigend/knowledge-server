"""Find an open-access location for an already identified DOI."""

import os
from collections.abc import Callable
from urllib.parse import quote, urlencode, urlsplit

from pydantic import BaseModel

from knowledge.literature.crossref_client import normalize_doi
from knowledge.literature.provider_http import request_model

API_URL = "https://api.unpaywall.org/v2"


class OpenAccessLocation(BaseModel):
    """Describe a provider-reported access location without asserting work identity."""

    url: str
    url_for_pdf: str | None = None
    license: str | None = None
    version: str | None = None


class _Response(BaseModel):
    doi: str
    best_oa_location: OpenAccessLocation | None = None


def lookup_unpaywall(
    doi: str, timeout_seconds: float, cancelled: Callable[[], bool]
) -> OpenAccessLocation | None:
    """Retrieve an OA link for an exact DOI when a contact email is configured."""
    normalized = normalize_doi(doi)
    email = os.environ.get("KNOWLEDGE_UNPAYWALL_EMAIL")
    if not normalized or not email:
        return None
    url = API_URL + "/" + quote(normalized, safe="") + "?" + urlencode({"email": email})
    response = request_model(url, _Response, timeout_seconds, cancelled)
    if response is None:
        return None
    if normalize_doi(response.doi) != normalized:
        raise ValueError("Unpaywall returned a different DOI")
    location = response.best_oa_location
    if location and any(
        urlsplit(link).scheme not in {"http", "https"}
        for link in (location.url, location.url_for_pdf)
        if link
    ):
        raise ValueError("Unpaywall returned an invalid access URL")
    return location
