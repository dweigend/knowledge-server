"""Call the replaceable GROBID service with a bounded, cancellable HTTP request."""

import math
import subprocess
from collections.abc import Callable
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

from knowledge.grobid_parser import MAX_TEI_BYTES, parse_paper_tei
from knowledge.paper_contracts import PaperDocument


def extract_paper(
    pdf: Path,
    *,
    base_url: str,
    timeout_seconds: float,
    cancelled: Callable[[], bool] | None = None,
) -> PaperDocument:
    """Submit a complete PDF and normalize its TEI without external consolidation."""
    endpoint = service_endpoint(base_url)
    if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 240:
        raise ValueError("GROBID timeout must be between 0 and 240 seconds")
    if cancelled is not None and cancelled():
        raise InterruptedError("GROBID extraction cancelled")
    arguments = [
        "curl",
        "--disable",
        "--silent",
        "--show-error",
        "--proto",
        "=http,https",
        "--max-time",
        str(timeout_seconds),
        "--max-filesize",
        str(MAX_TEI_BYTES),
        "--header",
        "Accept: application/xml",
        "--write-out",
        "\n%{http_code}",
        "--form",
        "input=@-;filename=source.pdf;type=application/pdf",
        "--form-string",
        "consolidateHeader=0",
        "--form-string",
        "consolidateCitations=0",
        "--form-string",
        "consolidateFunders=0",
        "--form-string",
        "includeRawCitations=1",
        "--form-string",
        "teiCoordinates=ref",
        "--form-string",
        "teiCoordinates=head",
        "--form-string",
        "teiCoordinates=biblStruct",
        endpoint,
    ]
    response = request_tei(arguments, pdf.read_bytes(), timeout_seconds, cancelled)
    body, _, status = response.rpartition(b"\n")
    validate_http_status(status.decode("ascii", errors="replace"))
    try:
        return parse_paper_tei(body.decode("utf-8"))
    except UnicodeDecodeError as error:
        raise ValueError("GROBID returned non-UTF-8 TEI") from error


def service_endpoint(base_url: str) -> str:
    """Require an explicit HTTP service URL without embedded credentials."""
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("GROBID URL must be an HTTP(S) service URL without credentials or query")
    return base_url.rstrip("/") + "/api/processFulltextDocument"


def validate_http_status(status: str) -> None:
    """Explain service failures without exposing a provider error response body."""
    if status == "200":
        return
    if status == "204":
        raise ValueError("GROBID extracted no content; check the PDF text layer or OCR")
    if status == "503":
        raise ValueError("GROBID is busy or unavailable; retry the extraction later")
    raise ValueError(f"GROBID extraction failed with HTTP {status}")


def request_tei(
    arguments: list[str],
    pdf_bytes: bytes,
    timeout_seconds: float,
    cancelled: Callable[[], bool] | None,
) -> bytes:
    """Terminate the local HTTP client promptly on cancellation or total deadline."""
    deadline = monotonic() + timeout_seconds
    try:
        process = subprocess.Popen(
            arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except FileNotFoundError as error:
        raise ValueError("GROBID extraction requires the curl executable") from error
    with process:
        try:
            stdout = communicate_request(process, pdf_bytes, deadline, cancelled)
            if process.returncode == 28:
                raise TimeoutError("GROBID extraction exceeded its time limit")
            if process.returncode:
                raise ValueError("GROBID request failed; check its service URL and availability")
            return stdout
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


def communicate_request(
    process: subprocess.Popen[bytes],
    pdf_bytes: bytes,
    deadline: float,
    cancelled: Callable[[], bool] | None,
) -> bytes:
    """Drain HTTP output while checking the deadline and cancellation callback."""
    pending: bytes | None = pdf_bytes
    while True:
        if cancelled is not None and cancelled():
            raise InterruptedError("GROBID extraction cancelled")
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("GROBID extraction exceeded its time limit")
        try:
            stdout, _ = process.communicate(input=pending, timeout=min(0.2, remaining))
            return stdout
        except subprocess.TimeoutExpired:
            pending = None
