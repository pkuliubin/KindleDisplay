from __future__ import annotations

import asyncio
import os
from pathlib import Path

from kindle_display.devices.layout_protocol import serialize_ttf_page
from kindle_display.runtime.config import KindleConfig
from kindle_display.runtime.models import PageSpec, RefreshMode


class KindleDisplayError(RuntimeError):
    pass


class KindleSink:
    def __init__(self, config: KindleConfig, sender_path: Path) -> None:
        self.config = config
        self.sender_path = sender_path

    async def display(self, page: PageSpec, refresh_mode: RefreshMode) -> None:
        try:
            font_path = self.config.fonts[page.font_role]
        except KeyError as error:
            raise KindleDisplayError(f"unknown font role: {page.font_role}") from error
        profile = (
            self.config.full_refresh_profile
            if refresh_mode is RefreshMode.FULL
            else self.config.normal_refresh_profile
        )
        environment = os.environ.copy()
        environment.update(
            {
                "KINDLE_HOST": self.config.host,
                "KINDLE_SSH_KEY": str(self.config.ssh_key),
                "KINDLE_CJK_FONT": font_path,
                "KINDLE_CONNECT_TIMEOUT": str(self.config.connect_timeout_seconds),
            }
        )
        process = await asyncio.create_subprocess_exec(
            str(self.sender_path),
            "--layout",
            "--refresh-profile",
            profile,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(serialize_ttf_page(page).encode("utf-8")),
                timeout=self.config.display_timeout_seconds,
            )
        except TimeoutError as error:
            await self._terminate(process)
            raise KindleDisplayError("Kindle display command timed out") from error
        except asyncio.CancelledError:
            await self._terminate(process)
            raise
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise KindleDisplayError(
                f"Kindle display command exited with status {process.returncode}: {message[-1000:]}"
            )
        _ = stdout

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                return
            await process.wait()
