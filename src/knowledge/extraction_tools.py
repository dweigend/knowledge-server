"""Run heavyweight PDF tools in bounded systemd groups with private scratch files."""

import json
import os
import subprocess
import sys
from pathlib import Path
from time import monotonic
from uuid import uuid4

from knowledge.run_log import record_event

RASTER_DPI = 200
TOOL_TIMEOUT_SECONDS = 7200


def run_tool(arguments: list[str], directory: Path, runtime_root: Path) -> None:
    """Bound CPU, memory and child-process lifetime for one extraction tool."""
    unit = "knowledge-extraction-" + uuid4().hex
    command = [
        "systemd-run",
        "--user",
        "--quiet",
        "--wait",
        "--pipe",
        "--collect",
        f"--unit={unit}",
        "--property=KillMode=control-group",
        f"--property=RuntimeMaxSec={TOOL_TIMEOUT_SECONDS}",
        "--property=MemoryMax=12G",
        "--property=CPUQuota=400%",
        *tool_environment(runtime_root),
        *arguments,
    ]
    parent = os.environ.get("KNOWLEDGE_EXTRACTION_UNIT")
    if parent:
        command[1:1] = [f"--property=BindsTo={parent}", f"--property=After={parent}"]
    started = monotonic()
    record_event(directory, "tool_started", tool=arguments[0], unit=unit)
    try:
        with (directory / "tool.log").open("a") as output:
            subprocess.run(
                command, stdout=output, stderr=output, check=True, timeout=TOOL_TIMEOUT_SECONDS + 30
            )
    finally:
        subprocess.run(["systemctl", "--user", "stop", unit], capture_output=True, check=False)
        record_event(directory, "tool_finished", tool=arguments[0], seconds=monotonic() - started)


def tool_environment(runtime_root: Path) -> list[str]:
    """Keep downloadable models and local inference settings under extraction ownership."""
    cache = runtime_root / "extraction-cache"
    binaries = runtime_root / "extraction-tools" / "llama-b10976"
    settings = {
        "XDG_CACHE_HOME": str(cache),
        "HF_HOME": str(cache / "huggingface"),
        "TORCH_HOME": str(cache / "torch"),
        "TORCH_DEVICE": "cpu",
        "OMP_NUM_THREADS": "4",
        "SURYA_INFERENCE_BACKEND": "llamacpp",
        "SURYA_INFERENCE_KEEP_ALIVE": "false",
        "PATH": f"{binaries}:{Path(sys.executable).parent}:/usr/bin:/bin",
    }
    return [f"--setenv={name}={value}" for name, value in settings.items()]


def docling_document(pdf: Path, directory: Path, runtime_root: Path) -> dict:
    """Export complete Docling JSON without creating an independent Markdown store."""
    directory.mkdir(parents=True, exist_ok=True)
    run_tool(
        [
            str(Path(sys.executable).with_name("docling")),
            "--to",
            "json",
            "--output",
            str(directory),
            "--device",
            "cpu",
            "--num-threads",
            "4",
            "--table-mode",
            "accurate",
            str(pdf),
        ],
        directory,
        runtime_root,
    )
    return json.loads((directory / f"{pdf.stem}.json").read_text())


def marker_document(pdf: Path, page: int, directory: Path, runtime_root: Path) -> dict:
    """Read an original PDF page visually from a 200-DPI raster with Marker."""
    directory.mkdir(parents=True, exist_ok=True)
    image = directory / "page"
    subprocess.run(
        [
            "pdftoppm",
            "-f",
            str(page),
            "-l",
            str(page),
            "-singlefile",
            "-r",
            str(RASTER_DPI),
            "-png",
            str(pdf),
            str(image),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    run_tool(
        [
            str(Path(sys.executable).with_name("marker_single")),
            str(image.with_suffix(".png")),
            "--mode",
            "fast",
            "--output_format",
            "json",
            "--output_dir",
            str(directory),
            "--keep_pageheader_in_output",
            "--keep_pagefooter_in_output",
        ],
        directory,
        runtime_root,
    )
    return json.loads((directory / "page" / "page.json").read_text())
