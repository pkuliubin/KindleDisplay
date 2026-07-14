from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any


class CommandJsonError(RuntimeError):
    pass


class OutputLimitError(CommandJsonError):
    pass


class CommandJsonSource:
    STDERR_TAIL_BYTES = 8 * 1024
    READ_CHUNK_BYTES = 64 * 1024

    def __init__(self, cwd: Path, argv: tuple[str, ...], max_stdout_bytes: int) -> None:
        self.cwd = cwd
        self.argv = argv
        self.max_stdout_bytes = max_stdout_bytes

    async def collect(self) -> Any:
        process = await asyncio.create_subprocess_exec(
            *self.argv,
            cwd=self.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_task = asyncio.create_task(self._read_stdout(process.stdout))
        stderr_task = asyncio.create_task(self._read_stderr_tail(process.stderr))
        wait_task = asyncio.create_task(process.wait())
        tasks = (stdout_task, stderr_task, wait_task)
        try:
            stdout, stderr, returncode = await asyncio.gather(*tasks)
            if returncode != 0:
                message = stderr.decode("utf-8", errors="replace").strip()
                raise CommandJsonError(f"command exited with status {returncode}: {message[-1000:]}")
            try:
                decoded = stdout.decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise CommandJsonError("command stdout is not valid UTF-8") from error
            try:
                return json.loads(decoded)
            except json.JSONDecodeError as error:
                raise CommandJsonError(f"command stdout is not valid JSON: {error}") from error
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2)
                except TimeoutError:
                    process.kill()
                    await process.wait()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _read_stdout(self, reader: asyncio.StreamReader) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while chunk := await reader.read(self.READ_CHUNK_BYTES):
            total += len(chunk)
            if total > self.max_stdout_bytes:
                raise OutputLimitError(f"command stdout exceeded {self.max_stdout_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)

    async def _read_stderr_tail(self, reader: asyncio.StreamReader) -> bytes:
        tail = bytearray()
        while chunk := await reader.read(self.READ_CHUNK_BYTES):
            tail.extend(chunk)
            if len(tail) > self.STDERR_TAIL_BYTES:
                del tail[: len(tail) - self.STDERR_TAIL_BYTES]
        return bytes(tail)
