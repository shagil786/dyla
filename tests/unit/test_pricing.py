"""Pricing must never invent a number it does not know."""

from __future__ import annotations

import pytest

from dyla.pricing import DEFAULT_USD_TO_INR, price_run, resolve_pricing


def test_known_model_prices_from_the_table():
    pricing = resolve_pricing("gpt-4o-mini")
    assert pricing is not None
    assert pricing.input_per_mtok_usd == 0.15
    assert pricing.output_per_mtok_usd == 0.60
    assert pricing.usd_to_inr == DEFAULT_USD_TO_INR


def test_dated_and_prefixed_deployment_names_resolve():
    pricing = resolve_pricing("openai/gpt-4o-mini-2024-07-18")
    assert pricing is not None
    assert pricing.input_per_mtok_usd == 0.15
    assert "matched gpt-4o-mini" in pricing.source


def test_longest_stem_wins_so_mini_is_not_billed_as_full_size():
    """'gpt-4o-mini-2024-07-18' contains both 'gpt-4o' and 'gpt-4o-mini'."""
    pricing = resolve_pricing("gpt-4o-mini-2024-07-18")
    assert pricing is not None
    assert pricing.input_per_mtok_usd == 0.15, "billed at gpt-4o rates, 16x too high"


def test_an_unknown_model_is_unpriced_rather_than_guessed():
    assert resolve_pricing("some-internal-model-v3") is None
    result = price_run("some-internal-model-v3", 1000, 500)
    assert result["priced"] is False
    assert result["cost_inr"] is None
    assert result["cost_usd"] is None
    assert "DYLA_PRICE_INPUT_PER_MTOK_USD" in result["note"]


def test_no_model_at_all_is_unpriced():
    assert resolve_pricing(None) is None
    assert price_run(None, 100, 100)["priced"] is False


def test_environment_overrides_take_precedence(monkeypatch):
    monkeypatch.setenv("DYLA_PRICE_INPUT_PER_MTOK_USD", "1.00")
    monkeypatch.setenv("DYLA_PRICE_OUTPUT_PER_MTOK_USD", "4.00")
    monkeypatch.setenv("DYLA_USD_TO_INR", "90")

    pricing = resolve_pricing("gpt-4o-mini")
    assert pricing is not None
    assert pricing.input_per_mtok_usd == 1.00
    assert pricing.source == "override"
    # 1M input + 1M output at 1 + 4 USD, at 90 INR/USD
    assert pricing.inr(1_000_000, 1_000_000) == pytest.approx(450.0)


def test_an_override_rescues_an_unknown_model(monkeypatch):
    monkeypatch.setenv("DYLA_PRICE_INPUT_PER_MTOK_USD", "0.20")
    monkeypatch.setenv("DYLA_PRICE_OUTPUT_PER_MTOK_USD", "0.80")
    result = price_run("some-internal-model-v3", 1_000_000, 1_000_000)
    assert result["priced"] is True
    assert result["cost_usd"] == pytest.approx(1.00)


def test_a_malformed_override_is_ignored_rather_than_crashing(monkeypatch):
    monkeypatch.setenv("DYLA_PRICE_INPUT_PER_MTOK_USD", "not-a-number")
    monkeypatch.setenv("DYLA_PRICE_OUTPUT_PER_MTOK_USD", "0.80")
    pricing = resolve_pricing("gpt-4o-mini")
    assert pricing is not None
    assert pricing.source == "table"


def test_cost_arithmetic():
    pricing = resolve_pricing("gpt-4o-mini")
    assert pricing is not None
    # 100k input, 20k output -> 0.015 + 0.012 = 0.027 USD
    assert pricing.usd(100_000, 20_000) == pytest.approx(0.027)
    assert pricing.inr(100_000, 20_000) == pytest.approx(0.027 * DEFAULT_USD_TO_INR)


def test_only_one_override_set_falls_back_to_the_table():
    """Half a price is not a price."""
    import os
    os.environ.pop("DYLA_PRICE_OUTPUT_PER_MTOK_USD", None)
    os.environ["DYLA_PRICE_INPUT_PER_MTOK_USD"] = "1.0"
    try:
        pricing = resolve_pricing("gpt-4o-mini")
        assert pricing is not None
        assert pricing.source == "table"
    finally:
        os.environ.pop("DYLA_PRICE_INPUT_PER_MTOK_USD", None)
