"""Token pricing and rupee conversion.

Why this exists
---------------
The evaluation report previously multiplied an internal "adapter unit" by a
hardcoded ``RUPEES_PER_ADAPTER_UNIT = 0.8`` carrying the comment "adjust based
on actual adapter pricing". That is not a rupee figure, and the brief asks for
cost per question in tokens *and* rupees.

Design rule: never invent a price. If the configured model is not in the table
and no override is set, ``price_run`` returns ``None`` and the report says
"unpriced" with the environment variables needed to fix it. A plausible-looking
fabricated number in a cost table is exactly the failure the auditor half of
this project exists to catch, and it would be dishonest to commit one here.

Rates are list prices in USD per million tokens, recorded with the date they
were checked. They go stale; ``DYLA_PRICE_*`` overrides them without a code
change.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# USD per 1M tokens, list prices. Checked 2026-09-05.
KNOWN_MODEL_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    # Anthropic
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-sonnet-4": (3.00, 15.00),
    # Google
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-2.0-flash": (0.10, 0.40),
    # Open-weight, typical hosted rates
    "llama-3.1-8b-instruct": (0.05, 0.08),
    "llama-3.3-70b-instruct": (0.59, 0.79),
    "qwen2.5-72b-instruct": (0.35, 0.40),
    "mistral-small": (0.20, 0.60),
}

# USD/INR spot, checked 2026-09-05 (investing.com). Override with DYLA_USD_TO_INR.
DEFAULT_USD_TO_INR = 94.5

_ENV_INPUT = "DYLA_PRICE_INPUT_PER_MTOK_USD"
_ENV_OUTPUT = "DYLA_PRICE_OUTPUT_PER_MTOK_USD"
_ENV_FX = "DYLA_USD_TO_INR"


@dataclass(frozen=True)
class Pricing:
    """Resolved prices for one model, in USD per million tokens."""

    model: str
    input_per_mtok_usd: float
    output_per_mtok_usd: float
    usd_to_inr: float
    source: str  # "override" | "table" | "table (matched <key>)"

    def usd(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.input_per_mtok_usd
            + output_tokens * self.output_per_mtok_usd
        ) / 1_000_000

    def inr(self, input_tokens: int, output_tokens: int) -> float:
        return self.usd(input_tokens, output_tokens) * self.usd_to_inr


def _float_env(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _normalise(model: str) -> str:
    name = model.strip().casefold()
    # Deployment names often carry a provider prefix or a dated suffix, e.g.
    # "openai/gpt-4o-mini-2024-07-18". Match on the recognisable stem.
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    return name


def resolve_pricing(model: str | None) -> Pricing | None:
    """Resolve prices for ``model``, or None when they are genuinely unknown."""
    usd_to_inr = _float_env(_ENV_FX) or DEFAULT_USD_TO_INR
    override_in, override_out = _float_env(_ENV_INPUT), _float_env(_ENV_OUTPUT)
    if override_in is not None and override_out is not None:
        return Pricing(model or "unknown", override_in, override_out, usd_to_inr, "override")

    if not model:
        return None
    name = _normalise(model)
    if name in KNOWN_MODEL_PRICING:
        rates = KNOWN_MODEL_PRICING[name]
        return Pricing(model, rates[0], rates[1], usd_to_inr, "table")

    # Longest matching stem wins, so "gpt-4o-mini-2024-07-18" does not match "gpt-4o".
    matches = sorted(
        (key for key in KNOWN_MODEL_PRICING if key in name), key=len, reverse=True
    )
    if matches:
        rates = KNOWN_MODEL_PRICING[matches[0]]
        return Pricing(model, rates[0], rates[1], usd_to_inr, f"table (matched {matches[0]})")
    return None


def price_run(model: str | None, input_tokens: int, output_tokens: int) -> dict[str, object]:
    """Cost for one run. ``priced`` is False when no rate could be established."""
    pricing = resolve_pricing(model)
    if pricing is None:
        return {
            "priced": False,
            "model": model,
            "cost_usd": None,
            "cost_inr": None,
            "note": (
                f"No price known for model {model!r}. Set {_ENV_INPUT} and "
                f"{_ENV_OUTPUT} (USD per 1M tokens), or add the model to "
                "dyla.pricing.KNOWN_MODEL_PRICING."
            ),
        }
    return {
        "priced": True,
        "model": pricing.model,
        "cost_usd": round(pricing.usd(input_tokens, output_tokens), 8),
        "cost_inr": round(pricing.inr(input_tokens, output_tokens), 6),
        "input_per_mtok_usd": pricing.input_per_mtok_usd,
        "output_per_mtok_usd": pricing.output_per_mtok_usd,
        "usd_to_inr": pricing.usd_to_inr,
        "rate_source": pricing.source,
    }
