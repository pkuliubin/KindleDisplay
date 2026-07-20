from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from kindle_display.devices.layout_protocol import serialize_ttf_page
from kindle_display.models import CodexStatusSnapshot, SessionSnapshot
from kindle_display.runtime.models import PageSpec


class KindleTextRenderer:
    """Render compact CJK monospaced tables as complete FBInk pages."""

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
    BODY_LINES_PER_PAGE = 13

    def __init__(self, width: int = 25, max_pages: int = 8) -> None:
        if width < 16:
            raise ValueError("width must be at least 16")
        if max_pages < 1:
            raise ValueError("max_pages must be positive")
        self.width = width
        self.max_pages = max_pages

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
        """Return the first TrueType page for the legacy single-page caller."""
        return serialize_ttf_page(self.render_page(snapshot))

    def render_page(self, snapshot: CodexStatusSnapshot) -> PageSpec:
        """Return the first page for callers that only support a single page."""
        return self.render_pages(snapshot)[0]

    def render_pages(self, snapshot: CodexStatusSnapshot) -> tuple[PageSpec, ...]:
        """Render project groups continuously and label only real page continuations."""
        page_bodies = self._paginate_sessions(snapshot)
        visible_bodies = page_bodies[: self.max_pages]
        hidden_sessions = snapshot.session_count - sum(session_count for _, session_count in visible_bodies)
        return tuple(
            self._render_page(snapshot, body_lines, index, hidden_sessions if index == len(visible_bodies) - 1 else 0)
            for index, (body_lines, _) in enumerate(visible_bodies)
        )

    def _paginate_sessions(self, snapshot: CodexStatusSnapshot) -> list[tuple[list[str], int]]:
        if not snapshot.projects:
            return [(["NO ACTIVE SESSIONS"], 0)]

        pages: list[tuple[list[str], int]] = []
        lines: list[str] = []
        session_count = 0

        def finish_page() -> None:
            nonlocal lines, session_count
            pages.append((lines, session_count))
            lines = []
            session_count = 0

        for project in snapshot.projects:
            session_index = 0
            continued = False
            while session_index < len(project.sessions):
                label = f"{project.name} (续)" if continued else project.name
                prefix = [] if not lines else [""]
                # Never strand a project heading without a session below it.
                if len(lines) + len(prefix) + 2 > self.BODY_LINES_PER_PAGE:
                    finish_page()
                    continue

                lines.extend((*prefix, self._clip(label, self.PROJECT_TITLE_WIDTH)))
                available_sessions = self.BODY_LINES_PER_PAGE - len(lines)
                sessions = project.sessions[session_index : session_index + available_sessions]
                lines.extend(self._session_row(session) for session in sessions)
                session_count += len(sessions)
                session_index += len(sessions)
                if session_index < len(project.sessions):
                    finish_page()
                    continued = True

        if lines:
            finish_page()
        return pages

    def _render_page(
        self,
        snapshot: CodexStatusSnapshot,
        body_lines: list[str],
        page_index: int,
        hidden_sessions: int,
    ) -> PageSpec:
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
        lines.extend(body_lines)
        if hidden_sessions:
            lines.append(f"+{hidden_sessions} SESSIONS HIDDEN")
        return PageSpec(
            page_id=f"codex:{page_index}",
            text="\n".join(lines),
            font_role="cjk_mono",
            font_px=24,
            top=20,
            left=20,
            right=15,
            bottom=20,
        )

    def _session_row(self, session: SessionSnapshot) -> str:
        metrics = session.metrics
        title = "> " + self._clip_title(self._display_title(session.title, session.id), self.SESSION_TITLE_WIDTH)
        context = f"{metrics.context_percent}%"
        token_total = f"{self._tokens(metrics.today_tokens)}/{self._tokens(metrics.total_tokens)}"
        cache = f"{metrics.cache_last_percent}/{metrics.cache_total_percent}"
        return self._table_row(
            title,
            self._model_label(session.model),
            self._state_label(session.state),
            context,
            token_total,
            cache,
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
        normalized = " ".join(printable_title)
        # Codex skill prompts prepend a local Markdown link that is not useful on Kindle.
        normalized = re.sub(r"^(?:\[[^\]]+\]\([^)]+\)\s*)+", "", normalized)
        return normalized or f"session-{session_id[-6:]}"

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
