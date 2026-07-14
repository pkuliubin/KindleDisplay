from __future__ import annotations

import tomllib
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelPricing:
    """Short-context USD prices per million tokens."""

    input_per_million: Decimal
    cached_input_per_million: Decimal
    output_per_million: Decimal

    def estimate_cost(self, *, input_tokens: int, cached_input_tokens: int, output_tokens: int) -> Decimal:
        uncached_input_tokens = input_tokens - cached_input_tokens
        return (
            Decimal(uncached_input_tokens) * self.input_per_million
            + Decimal(cached_input_tokens) * self.cached_input_per_million
            + Decimal(output_tokens) * self.output_per_million
        ) / Decimal(1_000_000)


class CodexPricing:
    """Optional local pricing table; unknown models deliberately have no estimate."""

    def __init__(self, models: dict[str, ModelPricing]) -> None:
        self.models = models

    @classmethod
    def from_toml(cls, path: Path) -> CodexPricing:
        try:
            with path.open("rb") as source:
                document = tomllib.load(source)
        except (OSError, tomllib.TOMLDecodeError):
            return cls({})

        models: dict[str, ModelPricing] = {}
        for model, config in document.get("models", {}).items():
            if not isinstance(config, dict):
                continue
            short_context = config.get("short_context")
            if not isinstance(short_context, dict):
                continue
            pricing = cls._pricing_from_config(short_context)
            if pricing is not None:
                models[model.lower()] = pricing
        return cls(models)

    @staticmethod
    def _pricing_from_config(config: dict[str, Any]) -> ModelPricing | None:
        try:
            return ModelPricing(
                input_per_million=Decimal(str(config["input"])),
                cached_input_per_million=Decimal(str(config["cached_input"])),
                output_per_million=Decimal(str(config["output"])),
            )
        except (KeyError, ValueError):
            return None

    def get(self, model: str) -> ModelPricing | None:
        return self.models.get(model.lower())
