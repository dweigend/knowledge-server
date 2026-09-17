"""Retrieve bounded provider responses without exposing request credentials."""

import json
import math
import subprocess
from collections.abc import Callable, Mapping
from tempfile import TemporaryFile
from time import monotonic, sleep
from typing import BinaryIO, Final
from urllib.parse import urlsplit

from pydantic import JsonValue, TypeAdapter, ValidationError

MAX_RESPONSE_BYTES: Final[int] = 2_000_000
MAX_CANDIDATES: Final[int] = 3
USER_AGENT: Final[str] = "knowledge-server/0.1 (https://github.com/dweigend/knowledge-server)"


def request_bytes(
    url: str,
    timeout_seconds: float,
    cancelled: Callable[[], bool],
    *,
    accept: str = "application/json",
    headers: Mapping[str, str] | None = None,
) -> bytes | None:
    """Fetch HTTPS content with bounded transfer size, duration and cancellation."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("Provider timeout must be positive and finite")
    if urlsplit(url).scheme != "https":
        raise ValueError("Provider requests require HTTPS")
    if cancelled():
        raise InterruptedError("Literature lookup cancelled")
    config = _curl_config(url, accept, headers or {})
    arguments = [
        "curl",
        "--disable",
        "--silent",
        "--proto",
        "=https",
        "--max-time",
        str(timeout_seconds),
        "--max-filesize",
        str(MAX_RESPONSE_BYTES),
        "--user-agent",
        USER_AGENT,
        "--write-out",
        "\n%{http_code}",
        "--config",
        "-",
    ]
    with TemporaryFile() as output, TemporaryFile() as configuration:
        configuration.write(config)
        configuration.seek(0)
        with subprocess.Popen(
            arguments, stdin=configuration, stdout=output, stderr=subprocess.DEVNULL
        ) as process:
            try:
                _wait_response(process, output, monotonic() + timeout_seconds, cancelled)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            if process.returncode:
                raise ValueError("Provider request failed or exceeded response limits")
        output.seek(0)
        return _response_body(output.read(MAX_RESPONSE_BYTES + 5))


def request_model[Response](
    url: str,
    response_type: type[Response] | TypeAdapter[Response],
    timeout_seconds: float,
    cancelled: Callable[[], bool],
    *,
    headers: Mapping[str, str] | None = None,
    collection_key: str | None = None,
    allow_missing_collection: bool = False,
) -> Response | None:
    """Validate a JSON response once and redact untrusted input from errors."""
    body = request_bytes(url, timeout_seconds, cancelled, headers=headers)
    if body is None:
        return None
    try:
        adapter = (
            response_type if isinstance(response_type, TypeAdapter) else TypeAdapter(response_type)
        )
        if collection_key is None:
            return adapter.validate_json(body)
        envelope = TypeAdapter(dict[str, JsonValue]).validate_json(body)
        entries = (
            envelope.get(collection_key, [])
            if allow_missing_collection
            else envelope[collection_key]
        )
        return adapter.validate_python(entries)
    except (KeyError, ValidationError):
        raise ValueError("Provider returned invalid bibliographic JSON") from None


def _curl_config(url: str, accept: str, headers: Mapping[str, str]) -> bytes:
    settings = [("url", url), ("header", f"Accept: {accept}")]
    settings.extend(("header", f"{name}: {value}") for name, value in headers.items())
    if any(any(character in value for character in "\r\n\x00") for _, value in settings):
        raise ValueError("Provider request contains invalid control characters")
    return "\n".join(f"{name} = {json.dumps(value)}" for name, value in settings).encode()


def _wait_response(
    process: subprocess.Popen[bytes],
    output: BinaryIO,
    deadline: float,
    cancelled: Callable[[], bool],
) -> None:
    while True:
        if cancelled():
            raise InterruptedError("Literature lookup cancelled")
        if output.tell() > MAX_RESPONSE_BYTES + 4:
            raise ValueError("Provider response exceeded its size limit")
        if process.poll() is not None:
            return
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("Provider lookup exceeded its time limit")
        sleep(min(0.05, remaining))


def _response_body(response: bytes) -> bytes | None:
    body, _, status = response.rpartition(b"\n")
    if status == b"404":
        return None
    if len(status) != 3 or not status.isdigit():
        raise ValueError("Provider returned an invalid HTTP status")
    if status != b"200":
        raise ValueError(f"Provider returned HTTP {status.decode('ascii')}")
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("Provider response exceeded its size limit")
    return body
