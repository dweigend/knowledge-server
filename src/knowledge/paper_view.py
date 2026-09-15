"""Render extracted paper Markdown without executing document-supplied HTML."""

from markdown_it import MarkdownIt
from markupsafe import Markup

_MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table").disable("image")


def render_paper_markdown(markdown: str) -> Markup:
    """Render readable paper structure with HTML and remote images disabled."""
    return Markup(_MARKDOWN.render(markdown))
