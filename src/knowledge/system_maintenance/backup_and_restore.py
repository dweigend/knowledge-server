"""Create operational snapshots and verify PostgreSQL restores.

Backups include database and Zotero state, integrity manifests, and an isolated
restore smoke test with an inspectable report.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

from psycopg.conninfo import make_conninfo
from pydantic import TypeAdapter

from knowledge.document_processing import document_models
from knowledge.revision_store import postgresql_revision_store
from knowledge.runtime_support import environment_settings
from knowledge.system_maintenance.maintenance_models import (
    DatabaseInspection,
    RestoreReport,
    RevisionCount,
)

_BATCH_ID: Final[TypeAdapter[str]] = TypeAdapter(str)
_MANIFEST: Final[TypeAdapter[dict[str, str]]] = TypeAdapter(dict[str, str])


def run_postgres(command: str, *arguments: str) -> None:
    """Run PostgreSQL utilities from PATH or an explicitly configured directory."""
    binary_directory = os.environ.get("KNOWLEDGE_POSTGRES_BIN")
    executable = str(Path(binary_directory) / command) if binary_directory else command
    subprocess.run([executable, *arguments], check=True)


def copy_zotero_library(library: Path, destination: Path) -> None:
    """Copy the stopped Zotero library database and attachment storage."""
    destination.mkdir()
    with (
        sqlite3.connect(f"file:{library / 'zotero.sqlite'}?mode=ro", uri=True) as source,
        sqlite3.connect(destination / "zotero.sqlite") as target,
    ):
        source.backup(target)
    shutil.copytree(library / "storage", destination / "storage")


def snapshot_zotero(library: Path, destination: Path) -> None:
    """Pause Zotero's exclusive SQLite lock and restore its prior running state."""
    if not library.is_dir():
        raise ValueError("Configured Zotero library does not exist")
    was_running = (
        subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", "knowledge-zotero"],
            check=False,
        ).returncode
        == 0
    )
    if was_running:
        subprocess.run(["systemctl", "--user", "stop", "knowledge-zotero"], check=True)
    try:
        copy_zotero_library(library, destination)
    finally:
        if was_running:
            subprocess.run(["systemctl", "--user", "start", "knowledge-zotero"], check=True)


def write_manifest(directory: Path) -> None:
    """Record SHA-256 checksums for every file in the completed snapshot."""
    hashes = {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*")
        if path.is_file()
    }
    (directory / "sha256.json").write_text(json.dumps(hashes, indent=2))


def snapshot(settings: environment_settings.Settings, output_root: Path) -> Path:
    """Snapshot an idle pilot; never delete originals or the live database."""
    library = Path(os.environ["KNOWLEDGE_ZOTERO_LIBRARY"]).expanduser()
    if not library.is_dir():
        raise ValueError("Configured Zotero library does not exist")
    directory = output_root / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    directory.mkdir(parents=True, mode=0o700)
    run_postgres(
        "pg_dump",
        "--format=custom",
        "--file",
        str(directory / "database.dump"),
        "--dbname",
        settings.database_url,
    )
    shutil.copytree(settings.archive_root, directory / "archive")
    run_directory = settings.archive_root.parent / "runs"
    if run_directory.exists():
        shutil.copytree(run_directory, directory / "runs")
    snapshot_zotero(library, directory / "zotero")
    write_manifest(directory)
    return directory


def verify_manifest(directory: Path) -> int:
    """Verify all recorded files and return their count."""
    manifest = _MANIFEST.validate_json((directory / "sha256.json").read_bytes())
    for name, expected_hash in manifest.items():
        actual_hash = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(f"Snapshot checksum mismatch: {name}")
    return len(manifest)


def inspect_restored_database(database_url: str) -> DatabaseInspection:
    """Decode restored records as well as counting their stored revisions."""
    with postgresql_revision_store.Database(database_url).transaction() as ledger:
        counts = ledger.connection.execute(
            "SELECT kind, count(*) AS count FROM revisions GROUP BY kind ORDER BY kind",
        ).fetchall()
        batches = ledger.connection.execute("SELECT batch_id FROM batches").fetchall()
        decoded = sum(
            len(ledger.list(_BATCH_ID.validate_python(row["batch_id"]))) for row in batches
        )
        snapshots = inspect_document_snapshots(ledger)
    return DatabaseInspection(
        current_records_decoded=decoded,
        revision_counts=TypeAdapter(list[RevisionCount]).validate_python(counts),
        document_snapshots_decoded=snapshots,
    )


def inspect_document_snapshots(ledger: postgresql_revision_store.Ledger) -> int:
    """Decode document snapshots when present, including backups preceding their introduction."""
    exists = ledger.connection.execute(
        "SELECT to_regclass('document_snapshots') AS name"
    ).fetchone()
    if exists is None or exists["name"] is None:
        return 0
    snapshots = ledger.connection.execute("SELECT payload FROM document_snapshots").fetchall()
    for snapshot in snapshots:
        document_models.DocumentSnapshot.model_validate(snapshot["payload"])
    return len(snapshots)


def write_restore_report(
    snapshot_directory: Path,
    restored_url: str,
    restored_name: str,
    files_verified: int,
) -> RestoreReport:
    """Persist file verification and decoded database counts together."""
    inspection = inspect_restored_database(restored_url)
    report = RestoreReport(
        **inspection.model_dump(),
        files_verified=files_verified,
        restored_database=restored_name,
    )
    (snapshot_directory / "restore-report.json").write_text(report.model_dump_json(indent=2))
    return report


def verify_restore(snapshot_directory: Path, database_url: str) -> RestoreReport:
    """Restore into a random temporary database; always remove that isolated target."""
    restored_name = "knowledge_restore_" + uuid4().hex
    restored_url = make_conninfo(database_url, dbname=restored_name)
    files_verified = verify_manifest(snapshot_directory)
    maintenance_url = make_conninfo(database_url, dbname="postgres")
    run_postgres("createdb", "--maintenance-db", maintenance_url, restored_name)
    try:
        run_postgres(
            "pg_restore",
            "--exit-on-error",
            "--no-owner",
            "--dbname",
            restored_url,
            str(snapshot_directory / "database.dump"),
        )
        return write_restore_report(
            snapshot_directory,
            restored_url,
            restored_name,
            files_verified,
        )
    finally:
        run_postgres("dropdb", "--maintenance-db", maintenance_url, restored_name)
