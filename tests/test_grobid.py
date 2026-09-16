import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import monotonic, sleep

import pytest

from knowledge.literature.grobid_client import extract_paper, service_endpoint
from knowledge.literature.grobid_parser import parse_paper_tei

TEI = """<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader>
<fileDesc>
<titleStmt>
<title>A paper</title>
</titleStmt>
<sourceDesc>
<biblStruct>
<analytic>
<title>A paper</title>
<author>
<persName>
<forename>Ada</forename>
<surname>Lovelace</surname>
</persName>
</author>
</analytic>
<monogr>
<title>Journal</title>
<imprint>
<date when="2024-02-01"/>
</imprint>
</monogr>
<idno type="DOI">10.1/example</idno>
</biblStruct>
</sourceDesc>
</fileDesc>
<profileDesc>
<abstract>
<p>Abstract text.</p>
</abstract>
</profileDesc>
<encodingDesc>
<appInfo>
<application ident="GROBID" version="0.8.2"/>
</appInfo>
</encodingDesc>
</teiHeader>
<text>
<body>
<div>
<head n="1" coords="1,20,40,60,10">Introduction</head>
<p>Text before <ref type="bibr" target="#b0" coords="1,2,3,4,5">[1]</ref> after.</p>
<div>
<head>Details</head>
<p>Another paragraph <ref type="bibr" target="#missing">[2]</ref>.</p>
<list>
<item>First item</item>
<item>Second item</item>
</list>
</div>
<figure>
<head>Table one</head>
<figDesc>Caption.</figDesc>
<table>
<row>
<cell>A</cell>
<cell>B</cell>
</row>
<row>
<cell>1</cell>
<cell>2</cell>
</row>
</table>
</figure>
<formula>x = y</formula>
<unexpected>Unrecognized content remains.</unexpected>
</div>
</body>
<back>
<div>
<head>Acknowledgments</head>
<p>Thanks!</p>
</div>
<div type="references">
<listBibl>
<biblStruct xml:id="b0">
<analytic>
<title>Cited work</title>
<author>
<persName>
<forename>Ann</forename>
<surname>Author</surname>
</persName>
</author>
</analytic>
<monogr>
<title>Venue</title>
<imprint>
<date when="2020"/>
</imprint>
</monogr>
<note type="raw_reference">Ann Author. Cited work (2020).</note>
</biblStruct>
</listBibl>
</div>
</back>
</text>
</TEI>"""


def test_tei_preserves_structure_bibliography_and_unresolved_citations():
    paper = parse_paper_tei(TEI)
    assert paper.metadata.title == "A paper"
    assert paper.metadata.authors == ["Ada Lovelace"]
    assert paper.metadata.year == "2024"
    assert paper.metadata.doi == "10.1/example"
    assert paper.provider_version == "0.8.2"
    assert paper.references[0].raw == "Ann Author. Cited work (2020)."
    assert paper.citations[0].resolved
    assert paper.citations[0].coordinates == "1,2,3,4,5"
    assert not paper.citations[1].resolved
    assert paper.sections[0].coordinates == "1,20,40,60,10"
    for expected in [
        "## Abstract",
        "## 1 Introduction",
        "### Details",
        "Text before [1] after.",
        "- First item",
        "| A | B |",
        "Caption.",
        "x = y",
        "Unrecognized content remains.",
        "Thanks!",
        "## References",
    ]:
        assert expected in paper.markdown
    assert paper.markdown.count("Ann Author. Cited work (2020).") == 1
    assert any("unresolved" in warning for warning in paper.warnings)
    assert paper.raw_document == TEI


def test_missing_metadata_stays_missing_and_is_reported():
    paper = parse_paper_tei(
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><p>Hello</p></body></text></TEI>'
    )
    assert paper.metadata.title is None
    assert paper.metadata.authors == []
    assert paper.metadata.year is None
    assert paper.references == []
    assert any("Missing document metadata" in warning for warning in paper.warnings)
    assert any("No bibliography" in warning for warning in paper.warnings)


@pytest.mark.parametrize(
    "xml",
    [
        "<TEI>",
        "<html>no</html>",
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><text/></TEI>',
        '<!DOCTYPE TEI [<!ENTITY secret SYSTEM "file:///etc/passwd">]><TEI/>',
    ],
)
def test_invalid_or_entity_bearing_response_is_rejected(xml):
    with pytest.raises(ValueError):
        parse_paper_tei(xml)


@pytest.fixture
def grobid_server():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, self.rfile.read(int(self.headers["Content-Length"]))))
            if self.path.startswith("/slow/"):
                sleep(0.5)
            status = 503 if self.path.startswith("/busy/") else 200
            self.send_response(status)
            self.end_headers()
            try:
                self.wfile.write(TEI.encode())
            except BrokenPipeError:
                pass

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", received
    server.shutdown()
    server.server_close()
    thread.join()


def test_http_request_includes_complete_pdf_and_disables_consolidation(tmp_path, grobid_server):
    url, received = grobid_server
    pdf = tmp_path / 'paper;filename="oops.pdf'
    pdf.write_bytes(b"%PDF-test")
    paper = extract_paper(pdf, base_url=url, timeout_seconds=5)
    assert paper.metadata.title == "A paper"
    path, request = received[0]
    assert path == "/api/processFulltextDocument"
    assert b"%PDF-test" in request
    assert b'name="includeRawCitations"\r\n\r\n1' in request
    assert b'name="consolidateCitations"\r\n\r\n0' in request


@pytest.mark.parametrize("route, exception", [("busy", ValueError), ("slow", TimeoutError)])
def test_service_failure_and_total_timeout_are_explicit(tmp_path, grobid_server, route, exception):
    url, _ = grobid_server
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-test")
    with pytest.raises(exception):
        extract_paper(pdf, base_url=f"{url}/{route}", timeout_seconds=0.1)


def test_cancel_stops_inflight_http_request(tmp_path, grobid_server):
    url, _ = grobid_server
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-test")
    start = monotonic()
    with pytest.raises(InterruptedError):
        extract_paper(
            pdf,
            base_url=f"{url}/slow",
            timeout_seconds=5,
            cancelled=lambda: monotonic() - start > 0.1,
        )
    assert monotonic() - start < 0.45


def test_cancel_before_request_does_not_read_pdf_or_contact_service():
    with pytest.raises(InterruptedError):
        extract_paper(
            Path("missing.pdf"),
            base_url="http://localhost:8070",
            timeout_seconds=5,
            cancelled=lambda: True,
        )


@pytest.mark.parametrize(
    "url",
    ["file:///tmp/paper", "http://user:secret@localhost:8070", "http://localhost:8070?key=secret"],
)
def test_service_url_rejects_non_http_and_credentials(url):
    with pytest.raises(ValueError):
        service_endpoint(url)


def test_duplicate_bibliography_identifiers_do_not_resolve_citations():
    duplicate = '<biblStruct xml:id="b0"><monogr><title>Other work</title></monogr></biblStruct>'
    paper = parse_paper_tei(TEI.replace("</listBibl>", duplicate + "</listBibl>"))
    assert not paper.citations[0].resolved
    assert any("Duplicate bibliography" in warning for warning in paper.warnings)


def test_unstructured_bibliography_is_retained_in_markdown():
    entry = '<bibl xml:id="b9">An unparsed reference string.</bibl>'
    paper = parse_paper_tei(TEI.replace("</listBibl>", entry + "</listBibl>"))
    assert paper.references[-1].id == "b9"
    assert paper.references[-1].raw == "An unparsed reference string."
    assert "An unparsed reference string." in paper.markdown


def test_citation_context_and_nearest_section_are_retained():
    paper = parse_paper_tei(TEI)
    assert paper.citations[0].context == "Text before [1] after."
    assert paper.citations[0].section == "Introduction"
    assert paper.citations[1].context == "Another paragraph [2]."
    assert paper.citations[1].section == "Details"


def test_repeated_marker_context_tracks_its_actual_occurrence():
    repeated = '<p>First context <ref type="bibr" target="#b0">[1]</ref>'
    repeated += " filler " * 200
    repeated += ' second context <ref type="bibr" target="#b0">[1]</ref> ending.</p>'
    start = TEI.index("<p>Text before")
    end = TEI.index("</p>", start) + len("</p>")
    paper = parse_paper_tei(TEI[:start] + repeated + TEI[end:])
    assert "First context" in paper.citations[0].context
    assert "second context" not in paper.citations[0].context
    assert "second context" in paper.citations[1].context
    assert "First context" not in paper.citations[1].context
