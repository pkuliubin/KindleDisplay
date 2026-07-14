from __future__ import annotations

import unicodedata
from decimal import Decimal

from kindle_display.devices.layout_protocol import serialize_ttf_page
from kindle_display.models import CodexStatusSnapshot
from kindle_display.runtime.models import PageSpec


class KindleTextRenderer:
    """Render a compact CJK monospaced table in one FBInk text block."""

    TASK_WIDTH = 14
    MODEL_WIDTH = 14
    STATE_WIDTH = 3
    CONTEXT_WIDTH = 4
    TOKEN_WIDTH = 12
    CACHE_WIDTH = 7
    SESSION_TITLE_WIDTH = TASK_WIDTH - 2
    PROJECT_TITLE_WIDTH = 28
    # FBInk collapses ASCII and no-break spaces; figure space remains a glyph.
    TABLE_SPACE = "\u2007"
    TASK_MODEL_GAP = 2
    MODEL_STATE_GAP = 2

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
                suffix = f" [{self._state_label(session.state)}]"
                lines.append(self._clip(self._display_title(session.title, session.id), self.width - self._width(suffix)) + suffix)
        return "\n".join(lines) + "\n"

    def render_layout(self, snapshot: CodexStatusSnapshot) -> str:
        """Return one TrueType table block, using an ASCII-safe line separator."""
        return serialize_ttf_page(self.render_page(snapshot))

    def render_page(self, snapshot: CodexStatusSnapshot) -> PageSpec:
        """Return one complete page without transport-specific TSV encoding."""
        status_counts = {
            status: sum(session.state == status for project in snapshot.projects for session in project.sessions)
            for status in ("RUN", "DONE", "STAL", "ABRT", "IDLE")
        }
        status_summary = " / ".join(
            f"{count} {self._state_label(status)}" for status, count in status_counts.items() if count
        )
        header = f"CODEX STATUS / {snapshot.generated_at.astimezone().strftime('%H:%M')}"
        if status_summary:
            header += f" / {status_summary}"
        lines = [header, *self._model_summary_lines(snapshot)]
        lines.append("")
        lines.extend(
            (
                self._table_row("TASK", "MODEL", "STA", "CTX", "TOK", "C L/T"),
                "-" * self._table_width(),
            )
        )
        for project_index, project in enumerate(snapshot.projects[:3]):
            if project_index:
                lines.append("")
            lines.append(self._clip(project.name, self.PROJECT_TITLE_WIDTH))
            for session in project.sessions[:3]:
                metrics = session.metrics
                title = "> " + self._clip_title(self._display_title(session.title, session.id), self.SESSION_TITLE_WIDTH)
                context = f"{metrics.context_percent}%"
                token_total = f"{self._tokens(metrics.today_tokens)}/{self._tokens(metrics.total_tokens)}"
                cache = f"{metrics.cache_last_percent}/{metrics.cache_total_percent}"
                lines.append(
                    self._table_row(
                        title,
                        self._model_label(session.model),
                        self._state_label(session.state),
                        context,
                        token_total,
                        cache,
                    )
                )
        font_px = 26 if len(lines) <= 15 else 22
        return PageSpec(
            page_id="codex:0",
            text="\n".join(lines),
            font_role="cjk_mono",
            font_px=font_px,
            top=20,
            left=20,
            right=15,
            bottom=20,
        )

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

    def _clip_title(self, value: str, width: int) -> str:
        normalized = " ".join(value.split())
        clipped = self._clip(normalized, width)
        if self._width(normalized) > width:
            clipped += "." * (width - self._width(clipped))
        return clipped

    def _pad(self, value: str, width: int) -> str:
        return value + self.TABLE_SPACE * max(0, width - self._width(value))

    def _table_row(self, task: str, model: str, state: str, context: str, tokens: str, cache: str) -> str:
        task_gap = self.TABLE_SPACE * self.TASK_MODEL_GAP
        return (
            self._pad(task, self.TASK_WIDTH)
            + task_gap
            + self._pad(model, self.MODEL_WIDTH)
            + self.TABLE_SPACE * self.MODEL_STATE_GAP
            + self.TABLE_SPACE.join(
                (
                    self._pad(state, self.STATE_WIDTH),
                    self._pad_left(context, self.CONTEXT_WIDTH),
                    self._pad_left(tokens, self.TOKEN_WIDTH),
                    self._pad_left(cache, self.CACHE_WIDTH),
                )
            )
        )

    def _pad_left(self, value: str, width: int) -> str:
        return self.TABLE_SPACE * max(0, width - self._width(value)) + value

    def _table_width(self) -> int:
        return sum(
            (
                self.TASK_WIDTH,
                self.MODEL_WIDTH,
                self.STATE_WIDTH,
                self.CONTEXT_WIDTH,
                self.TOKEN_WIDTH,
                self.CACHE_WIDTH,
            )
        ) + self.TASK_MODEL_GAP + self.MODEL_STATE_GAP + 3

    @staticmethod
    def _width(value: str) -> int:
        return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in value)

    @staticmethod
    def _tokens(value: int) -> str:
        if value >= 1_000_000_000:
            return f"{value / 1_000_000_000:.1f}B"
        if value >= 1_000_000:
            return f"{value / 1_000_000:.1f}M"
        if value >= 1_000:
            return f"{value // 1_000}k"
        return str(value)

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
    def _model_summary_label(model: str) -> str:
        normalized = model.lower()
        if "gpt-5.6-terra" in normalized:
            return "gpt-5.6-terra"
        if "gpt-5.6-sol" in normalized:
            return "gpt-5.6-sol"
        if "gpt-5.5" in normalized:
            return "gpt-5.5"
        if normalized == "unknown":
            return "unknown"
        return KindleTextRenderer._clip_static(model, 18)

    def _model_summary_lines(self, snapshot: CodexStatusSnapshot) -> list[str]:
        if not snapshot.daily_model_tokens:
            return ["no token usage"]
        return [
            self.TABLE_SPACE.join(
                (
                    self._pad(self._model_summary_label(usage.model), 14),
                    self._pad_left(self._tokens(usage.today_tokens), 6),
                    self._pad_left(f"{usage.output_token_rate:.1%}", 5),
                    self._pad_left(self._usd(usage.estimated_cost_usd), 8),
                )
            )
            for usage in snapshot.daily_model_tokens
        ]

    @staticmethod
    def _usd(value: Decimal | None) -> str:
        if value is None:
            return ""
        if value >= 1:
            return f"${value:.2f}"
        if value >= 0.01:
            return f"${value:.3f}"
        return f"${value:.4f}"

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
