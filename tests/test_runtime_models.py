from __future__ import annotations

import unittest

from kindle_display.runtime.models import DisplayPolicy, PageSpec, validate_pages


class RuntimeModelsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = DisplayPolicy(block_seconds=60, min_page_seconds=20, max_pages=3)
        self.fonts = frozenset({"cjk_mono"})

    def page(self, **changes: object) -> PageSpec:
        values: dict[str, object] = {
            "page_id": "page-1",
            "text": "hello\n中文",
            "font_role": "cjk_mono",
            "font_px": 26,
            "top": 20,
            "left": 20,
            "right": 15,
            "bottom": 20,
        }
        values.update(changes)
        return PageSpec(**values)  # type: ignore[arg-type]

    def test_accepts_a_valid_page(self) -> None:
        validate_pages((self.page(),), self.policy, self.fonts)

    def test_rejects_protocol_control_characters(self) -> None:
        for text in ("a\tb", "a\x00b", "a\x1eb", "a\x07b"):
            with self.subTest(text=repr(text)), self.assertRaises(ValueError):
                validate_pages((self.page(text=text),), self.policy, self.fonts)

    def test_rejects_duplicate_ids_unknown_fonts_and_odd_sizes(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_pages((self.page(), self.page()), self.policy, self.fonts)
        with self.assertRaisesRegex(ValueError, "font_role"):
            validate_pages((self.page(font_role="missing"),), self.policy, self.fonts)
        with self.assertRaisesRegex(ValueError, "even"):
            validate_pages((self.page(font_px=25),), self.policy, self.fonts)

    def test_rejects_pages_that_cannot_fit_the_block_budget(self) -> None:
        policy = DisplayPolicy(block_seconds=60, min_page_seconds=30, max_pages=2)
        pages = (self.page(page_id="one"), self.page(page_id="two"))
        validate_pages(pages, policy, self.fonts)
        with self.assertRaisesRegex(ValueError, "max_pages"):
            validate_pages((*pages, self.page(page_id="three")), policy, self.fonts)
