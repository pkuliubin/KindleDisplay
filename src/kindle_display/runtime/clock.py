from __future__ import annotations

import asyncio
import datetime as dt
import time
from typing import Protocol


class Clock(Protocol):
    def monotonic(self) -> float:
        ...

    def now(self) -> dt.datetime:
        ...

    async def sleep(self, seconds: float) -> None:
        ...


class RealClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
