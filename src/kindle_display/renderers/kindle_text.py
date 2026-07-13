from __future__ import annotations

import unicodedata

from kindle_display.models import CodexStatusSnapshot


class KindleTextRenderer:
    """Render a compact fixed-width status page for the verified K4 layout."""

    def __init__(self, width: int = 25) -> None:
        if width < 16:
            raise ValueError("width must be at least 16")
        self.width = width

    def render(self, snapshot: CodexStatusSnapshot) -> str:
        running = sum(project.running_count for project in snapshot.projects)
        header = f"CODEX {snapshot.generated_at.astimezone().strftime('%H:%M')} {running}R {snapshot.session_count - running}W"
        lines = [self._clip(header)]
        for project in snapshot.projects:
            project_suffix = f" [{len(project.sessions)}]"
            lines.extend(["", self._clip(project.name, self.width - self._width(project_suffix)) + project_suffix])
            for session in project.sessions:
                metrics = session.metrics
                suffix = f" [{session.state}]"
                lines.append(self._clip(self._display_title(session.title, session.id), self.width - self._width(suffix)) + suffix)
        return "\n".join(lines) + "\n"

    def render_layout(self, snapshot: CodexStatusSnapshot) -> str:
        """Return FBInk blocks: size, column, top, left, renderer, text."""
        status_counts = {
            status: sum(session.state == status for project in snapshot.projects for session in project.sessions)
            for status in ("RUN", "DONE", "STAL", "ABRT", "IDLE")
        }
        status_summary = " / ".join(f"{count} {status}" for status, count in status_counts.items() if count)
        blocks = [
            (3, 1, 35, 0, "bitmap", f"CODEX STATUS / {snapshot.generated_at.astimezone().strftime('%H:%M')}"),
            (
                2,
                1,
                70,
                8,
                "bitmap",
                status_summary.replace(" RUN", "R").replace(" DONE", "D").replace(" STAL", "S").replace(" ABRT", "A").replace(" IDLE", "I"),
            ),
            (2, 1, 98, 8, "bitmap", f"{'TASK':<8} {'MODEL':<14} {'S':<1} {'CTX':>4} {'TOK':>7} {'C L/T':>7}"),
            (2, 1, 119, 8, "bitmap", "----------------------------------------"),
        ]
        top = 145
        for project in snapshot.projects[:3]:
            blocks.append((3, 1, top, 0, "cjk_heading", self._clip(project.name, 25)))
            top += 38
            for session in project.sessions[:3]:
                metrics = session.metrics
                title = self._pad(self._clip(self._display_title(session.title, session.id), 8), 8)
                context = f"{metrics.context_percent}%"
                token_total = self._tokens(metrics.total_tokens)
                cache = f"{metrics.cache_last_percent}/{metrics.cache_total_percent}"
                # The title occupies the original eight-character column; metrics stay bitmap-aligned.
                row = f"{' ':8} {self._model_label(session.model):<14} {self._state_label(session.state)} {context:>4} {token_total:>7} {cache:>7}"
                blocks.append((2, 1, top, 8, "bitmap", row))
                blocks.append((2, 1, top, 8, "cjk_row", title.rstrip()))
                top += 27
            top += 50
        return "\n".join(
            f"{size}\t{column}\t{pixel_top}\t{pixel_left}\t{renderer}\t{text}"
            for size, column, pixel_top, pixel_left, renderer, text in blocks
        ) + "\n"

    def _clip(self, value: str, width: int | None = None) -> str:
        width = width or self.width
        value = " ".join(value.split())
        if self._width(value) <= width:
            return value
        if width <= 1:
            return "."
        kept: list[str] = []
        used = 0
        for char in value:
            char_width = 2 if unicodedata.east_asian_width(char) in "WF" else 1
            if used + char_width > width - 1:
                break
            kept.append(char)
            used += char_width
        return "".join(kept) + "."

    def _pad(self, value: str, width: int) -> str:
        return value + " " * max(0, width - self._width(value))

    @staticmethod
    def _width(value: str) -> int:
        return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in value)

    @staticmethod
    def _tokens(value: int) -> str:
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        return f"{value // 1_000}k"

    @staticmethod
    def _display_title(title: str, session_id: str) -> str:
        printable_title = "".join(char if char.isprintable() else " " for char in title).split()
        return " ".join(printable_title) or f"session-{session_id[-6:]}"

    @staticmethod
    def _model_label(model: str) -> str:
        normalized = model.lower()
        if "gpt-5.6-terra" in normalized:
            return "gpt-5.6-terra"
        if "gpt-5.6-sol" in normalized:
            return "gpt-5.6-sol"
        return KindleTextRenderer._clip_static(model, 14)

    @staticmethod
    def _state_label(state: str) -> str:
        return {
            "RUN": "R",
            "DONE": "D",
            "ABRT": "A",
            "STAL": "S",
            "IDLE": "I",
        }.get(state, "?")

    @staticmethod
    def _clip_static(value: str, width: int) -> str:
        return value if len(value) <= width else value[: width - 1] + "."
