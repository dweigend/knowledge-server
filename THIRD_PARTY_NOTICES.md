# Third-party notices

The root MIT license covers original project code, not dependencies or research
content supplied by users.

## PDF.js

The bundled Mozilla PDF.js 6.3.289 legacy distribution is Apache-2.0 licensed.
Its provenance and checksum are in
[src/knowledge/static/pdfjs/UPSTREAM.txt](src/knowledge/static/pdfjs/UPSTREAM.txt).
Preserve all bundled license files and copyright notices, including those for
fonts, character maps and WebAssembly components.

## Optional document extraction

Docling and Marker are installed only with the `extraction` dependency group.
They are separate tools; this repository does not include their model weights.

- [Docling](https://github.com/docling-project/docling) maintains its own code
  license and model dependencies.
- [Marker 2.0.0](https://github.com/datalab-to/marker/tree/v2.0.0) uses Apache-2.0
  for code and separate OpenRAIL-M terms for its model weights. Read the pinned
  release's license and model terms before redistributing models.
- [llama.cpp](https://github.com/ggml-org/llama.cpp) is a separately installed
  inference runtime for the current Marker configuration.

Other dependencies are listed in `pyproject.toml` and pinned in `uv.lock`.
The project license does not replace their licenses or authorize redistribution
of PDFs, extracted article text or other third-party literature.
