"""A3 in-memory fake cost accountant — the offline twin of cost_client.

Per PRD 「适配器各自用假实现测」: every adapter ships a production impl AND an
in-memory fake honoring the SAME contract. The fake NEVER reads the price-table
file — it returns a FIXED cost triple + source so tests stay stable + offline.

It STILL obeys the iron rules:
  1. 诚实标源: a fake with cost_source='unavailable' returns cost_usd=None
     (priced=False) — 拿不到 never fakes a 0.
  2. it carries the same three numbers (input/output tokens, calls) + $ + source,
     so the seam can't tell prod and fake apart on contract shape.

Contract (identical to cost_client):
  {"cost_input_tokens", "cost_output_tokens", "cost_model_calls",
   "cost_usd", "cost_source", "priced", "model", "price_table_updated"}
"""
from __future__ import annotations

from pipeline.cost_client import UNAVAILABLE, _result

_FAKE_UPDATED = "fake-table"


class FakeCostAccountant:
    """Offline twin: returns a fixed cost triple, no file I/O.

    Defaults model a small self-reported run that prices to $0.001. Pass
    cost_source='unavailable' (or priced=False) to model a black-box竞品.
    """

    def __init__(self, *, input_tokens: int = 1000, output_tokens: int = 500,
                 model_calls: int = 1, cost_usd: float | None = 0.001,
                 cost_source: str = "self-report", model: str | None = "fake-model"):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.model_calls = model_calls
        self.cost_usd = cost_usd
        self.cost_source = cost_source
        self.model = model

    def account(self, *, model=None, input_tokens=None, output_tokens=None,
                model_calls=None, cost_source=None) -> dict:
        # The fake ignores real prices; it honors its fixed config, but callers
        # may override source to exercise the unavailable path.
        src = cost_source if cost_source is not None else self.cost_source
        usd = None if src == UNAVAILABLE else self.cost_usd
        return _result(
            in_tok=self.input_tokens if input_tokens is None else input_tokens,
            out_tok=self.output_tokens if output_tokens is None else output_tokens,
            calls=self.model_calls if model_calls is None else model_calls,
            cost_usd=usd, cost_source=src,
            model=model if model is not None else self.model,
            price_updated=_FAKE_UPDATED)

    def apply_to_run(self, run, **kw) -> dict:
        out = self.account(**kw)
        run.cost_input_tokens = out["cost_input_tokens"]
        run.cost_output_tokens = out["cost_output_tokens"]
        run.cost_model_calls = out["cost_model_calls"]
        run.cost_usd = out["cost_usd"]
        run.cost_source = out["cost_source"]
        return out


def fake_account(*, cost_usd: float | None = 0.001,
                 cost_source: str = "self-report") -> dict:
    """One-shot offline twin of CostAccountant.account()."""
    return FakeCostAccountant(cost_usd=cost_usd,
                              cost_source=cost_source).account()


# Ready-made fakes: a priced self-report run, a proxy run, a black-box竞品.
fake_self_report = FakeCostAccountant(cost_source="self-report")
fake_proxy = FakeCostAccountant(cost_source="proxy", cost_usd=0.002)
fake_unavailable = FakeCostAccountant(cost_source="unavailable", cost_usd=None)

FAKE_ACCOUNTANTS = {
    "self-report": fake_self_report,
    "proxy": fake_proxy,
    "unavailable": fake_unavailable,
}

__all__ = [
    "FakeCostAccountant", "fake_account", "fake_self_report", "fake_proxy",
    "fake_unavailable", "FAKE_ACCOUNTANTS",
]
