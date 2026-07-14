from __future__ import annotations

from kindle_display.runtime.models import PageSpec


RECORD_SEPARATOR = "\x1e"


def serialize_ttf_page(page: PageSpec) -> str:
    text = page.text.replace("\n", RECORD_SEPARATOR)
    return (
        f"{page.font_px}\t{page.top}\t{page.left}\t{page.right}\tttf_page\t{text}\n"
    )
