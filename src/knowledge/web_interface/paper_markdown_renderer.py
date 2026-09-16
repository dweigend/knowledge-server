"""Render extracted paper Markdown as safe HTML.

Document-supplied HTML remains inert so experiment views can display analysis
output without executing embedded markup.
"""

from markdown_it import MarkdownIt
from markupsafe import Markup

_MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table").disable("image")


def render_paper_markdown(markdown: str) -> Markup:
    """Render readable paper structure with HTML and remote images disabled."""
    return Markup(_MARKDOWN.render(markdown))
