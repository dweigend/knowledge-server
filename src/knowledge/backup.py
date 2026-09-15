"""Private pilot snapshots and an isolated PostgreSQL restore smoke test."""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from psycopg.conninfo import make_conninfo

from knowledge.config import Settings
from knowledge.document_contracts import DocumentSnapshot
from knowledge.storage import Database, Ledger


def run_postgres(command: str, *arguments: str) -> None:
    """Run PostgreSQL utilities from PATH or an explicitly configured directory."""
    binary_directory = os.environ.get("KNOWLEDGE_POSTGRES_BIN")
    executable = str(Path(binary_directory) / command) if binary_directory else command
    subprocess.run([executable, *arguments], check=True)


def dump_database(database_url: str, destination: Path) -> None:
    """Write a PostgreSQL custom-format dump for later isolated restoration."""
    run_postgres(
        "pg_dump",
        "--format=custom",
        "--file",
        str(destination),
        "--dbname",
        database_url,
    )


def copy_zotero_library(library: Path, destination: Path) -> None:
    """Copy the stopped Zotero library database and attachment storage."""
    destination.mkdir()
    with (
        sqlite3.connect(f"file:{library / 'zotero.sqlite'}?mode=ro", uri=True) as source,
        sqlite3.connect(destination / "zotero.sqlite") as target,
    ):
        source.backup(target)
    shutil.copytree(library / "storage", destination / "storage")


def restart_zotero(was_running: bool) -> None:
    """Restore Zotero only when it was running before the snapshot."""
    if not was_running:
        return
    subprocess.run(["systemctl", "--user", "start", "knowledge-zotero"], check=True)


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
        restart_zotero(was_running)


def write_manifest(directory: Path) -> None:
    """Record SHA-256 checksums for every file in the completed snapshot."""
    hashes = {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*")
        if path.is_file()
    }
    (directory / "sha256.json").write_text(json.dumps(hashes, indent=2))


def snapshot(settings: Settings, output_root: Path) -> Path:
    """Snapshot an idle pilot; never delete originals or the live database."""
    library = Path(os.environ["KNOWLEDGE_ZOTERO_LIBRARY"]).expanduser()
    if not library.is_dir():
        raise ValueError("Configured Zotero library does not exist")
    directory = output_root / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    directory.mkdir(parents=True, mode=0o700)
    dump_database(settings.database_url, directory / "database.dump")
    shutil.copytree(settings.archive_root, directory / "archive")
    run_directory = settings.archive_root.parent / "runs"
    if run_directory.exists():
        shutil.copytree(run_directory, directory / "runs")
    snapshot_zotero(library, directory / "zotero")
    write_manifest(directory)
    return directory


def verify_file(directory: Path, name: str, expected_hash: str) -> None:
    """Reject a snapshot file whose bytes differ from its recorded checksum."""
    actual_hash = hashlib.sha256((directory / name).read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError(f"Snapshot checksum mismatch: {name}")


def verify_manifest(directory: Path) -> int:
    """Verify all recorded files and return their count."""
    manifest = json.loads((directory / "sha256.json").read_text())
    for name, expected_hash in manifest.items():
        verify_file(directory, name, expected_hash)
    return len(manifest)


def restore_database(snapshot_directory: Path, database_url: str) -> None:
    """Load the snapshot dump into the supplied isolated database."""
    run_postgres(
        "pg_restore",
        "--exit-on-error",
        "--no-owner",
        "--dbname",
        database_url,
        str(snapshot_directory / "database.dump"),
    )


def inspect_restored_database(database_url: str) -> dict:
    """Decode restored records as well as counting their stored revisions."""
    with Database(database_url).transaction() as ledger:
        counts = ledger.connection.execute(
            "SELECT kind, count(*) AS count FROM revisions GROUP BY kind ORDER BY kind",
        ).fetchall()
        batches = ledger.connection.execute("SELECT batch_id FROM batches").fetchall()
        decoded = sum(len(ledger.list(row["batch_id"])) for row in batches)
        snapshots = inspect_document_snapshots(ledger)
    return {
        "current_records_decoded": decoded,
        "revision_counts": counts,
        "document_snapshots_decoded": snapshots,
    }


def inspect_document_snapshots(ledger: Ledger) -> int:
    """Decode document snapshots when present, including backups preceding their introduction."""
    exists = ledger.connection.execute(
        "SELECT to_regclass('document_snapshots') AS name"
    ).fetchone()
    if exists is None or exists["name"] is None:
        return 0
    snapshots = ledger.connection.execute("SELECT payload FROM document_snapshots").fetchall()
    for snapshot in snapshots:
        DocumentSnapshot.model_validate(snapshot["payload"])
    return len(snapshots)


def write_restore_report(
    snapshot_directory: Path,
    restored_url: str,
    restored_name: str,
    files_verified: int,
) -> dict:
    """Persist file verification and decoded database counts together."""
    report = {
        "files_verified": files_verified,
        **inspect_restored_database(restored_url),
        "restored_database": restored_name,
    }
    (snapshot_directory / "restore-report.json").write_text(json.dumps(report, indent=2))
    return report


def verify_restore(snapshot_directory: Path, database_url: str) -> dict:
    """Restore into a random temporary database; always remove that isolated target."""
    restored_name = "knowledge_restore_" + uuid4().hex
    restored_url = make_conninfo(database_url, dbname=restored_name)
    files_verified = verify_manifest(snapshot_directory)
    maintenance_url = make_conninfo(database_url, dbname="postgres")
    run_postgres("createdb", "--maintenance-db", maintenance_url, restored_name)
    try:
        restore_database(snapshot_directory, restored_url)
        return write_restore_report(
            snapshot_directory,
            restored_url,
            restored_name,
            files_verified,
        )
    finally:
        run_postgres("dropdb", "--maintenance-db", maintenance_url, restored_name)
