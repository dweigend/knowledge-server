"""Each integration test uses its own PostgreSQL schema on the server."""

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from support import SeedArticle

from knowledge.application import Knowledge
from knowledge.contracts import Bibliography, ExtractedClaim, LegacySource
from knowledge.storage import Database


@pytest.fixture
def application():
    database_url = os.environ["KNOWLEDGE_TEST_DATABASE_URL"]
    schema = "test_" + uuid4().hex
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    database = Database(database_url + f" options='-c search_path={schema}'")
    database.initialize()
    app = Knowledge(database)
    app.create_batch("pilot", "Test")
    try:
        yield app
    finally:
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def article():
    bibliography = Bibliography(title="Test source", authors=[], year="2026", doi="", url="")
    source = LegacySource(
        bibliography=bibliography,
        original_path="/archive/test.pdf",
        sha256="a" * 64,
        archive_path="/archive/clean.pdf",
        pages=["Group A scored higher. No retention was measured."],
        extraction_method="fixture",
        extraction_warnings=[],
        study_group="study-a",
        overlap="unknown",
    )
    claim = ExtractedClaim(
        proposition="Group A scored higher",
        scope="Immediate test",
        qualifications="No retention",
        page=1,
        quote="Group A scored higher.",
        relation="supports",
        rationale="Direct result",
        directness="direct",
        methodology="Randomized comparison",
        limitations="Small sample",
    )
    return SeedArticle(source=source, claim=claim)
