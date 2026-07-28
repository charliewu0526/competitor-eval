"""A3: cost-accounting adapter (production). 按任务记 token+调用+折算$，诚实标源。

The 5th seam adapter (ADR-0008). Per task it records THREE numbers, kept apart:

    cost_input_tokens + cost_output_tokens   — 技术效率 (token 用量)
    cost_model_calls                         — 架构效率 (来回轮数)
    cost_usd                                  — 商业效率, 给 PM/老板看的决策数

`cost_usd` is FOLDED from tokens via an INDEPENDENT price table (model_prices.json):
改价不改代码. Prices change, so they live in data, never in code.

Two iron rules from ADR-0008 / issue #21:
  1. 诚实标源 (cost_source): self-report (竞品自报 usage, 最准) > proxy (我们代理截流量,
     需工程) > unavailable (云端黑箱拿不到). 拿不到 NEVER masquerades as a 0 — cost_usd
     is None and cost_source='unavailable'. 缺单价 同理: tokens 有但价格表里没这个模型
     -> cost_usd=None, priced=False.
  2. 成本必须和「是否真完成」一起看: this adapter NEVER decides完成度. cost_usd is read
     SIDE BY SIDE with sample_score (see store.cost_with_completion) so 「摆烂没干完」
     can't disguise itself as 「省 token」.

Contract dict (shared by production CostAccountant + FakeCostAccountant):
  {"cost_input_tokens": int, "cost_output_tokens": int, "cost_model_calls": int,
   "cost_usd": float | None,           # None => not priced (unavailable | 缺价)
   "cost_source": str,                 # self-report | proxy | unavailable
   "priced": bool,                     # True iff cost_usd is a real number
   "model": str | None,                # which price-table key was used
   "price_table_updated": str | None}  # provenance of the price snapshot used
"""
from __future__ import annotations
import json
import pathlib

from pipeline.schema import COST_SOURCE_VALUES

UNAVAILABLE = "unavailable"
NATIVE = "native"
DEFAULT_PRICE_TABLE = pathlib.Path(__file__).resolve().parent / "model_prices.json"

# token usage is denominated per MILLION tokens in the price table.
_PER = 1_000_000


class PriceTable:
    """The independent 单价表. Loaded from JSON so 改价不改代码.

    A missing model is NOT an error and NOT a 0 — price_of() returns None so the
    caller stamps cost_usd=unavailable rather than inventing a free run.
    """

    def __init__(self, data: dict):
        self.currency = data.get("currency", "USD")
        self.unit = data.get("unit", "per_million_tokens")
        self.updated = data.get("updated")
        self._models = data.get("models", {})

    @classmethod
    def load(cls, path: str | pathlib.Path | None = None) -> "PriceTable":
        p = pathlib.Path(path) if path else DEFAULT_PRICE_TABLE
        return cls(json.loads(p.read_text()))

    def has(self, model: str) -> bool:
        return model in self._models

    def price_of(self, model: str) -> dict | None:
        """Return {'input':$,'output':$} per-million for model, or None if 缺价."""
        return self._models.get(model)

    def cost_usd(self, model: str, in_tok: int, out_tok: int) -> float | None:
        """Fold tokens -> $ via the table. None when the model isn't priced."""
        p = self.price_of(model)
        if p is None:
            return None
        return round((in_tok * p["input"] + out_tok * p["output"]) / _PER, 6)


def _result(*, in_tok: int, out_tok: int, calls: int, cost_usd: float | None,
            cost_source: str, model: str | None,
            price_updated: str | None) -> dict:
    """Build the shared contract dict, validating cost_source against schema.

    cost_usd is coerced to None (=> priced False) whenever the source is
    unavailable — 拿不到来源不能折出一个数. priced is the single boolean callers
    check before treating cost_usd as real money.
    """
    if cost_source not in COST_SOURCE_VALUES:
        raise ValueError(f"cost_source must be one of {COST_SOURCE_VALUES}, "
                         f"got {cost_source!r}")
    if cost_source == UNAVAILABLE:
        cost_usd = None
    priced = cost_usd is not None
    return {
        "cost_input_tokens": int(in_tok),
        "cost_output_tokens": int(out_tok),
        "cost_model_calls": int(calls),
        "cost_usd": cost_usd,
        "cost_source": cost_source,
        "priced": priced,
        "model": model,
        "price_table_updated": price_updated,
    }


class CostAccountant:
    """Production accountant: records token/call usage and folds $ via the table.

    The usage numbers (tokens, calls) come from the run harness; their accuracy
    is captured by cost_source. The $ figure is always derived HERE from the
    independent price table, so a price change is a data edit, never a code edit.
    """

    def __init__(self, prices: PriceTable | None = None):
        self.prices = prices or PriceTable.load()

    def account(self, *, model: str | None,
                input_tokens: int = 0, output_tokens: int = 0,
                model_calls: int = 0,
                cost_source: str = "self-report") -> dict:
        """Account ONE run's cost. Returns the shared contract dict.

        model: price-table key (e.g. 'deepseek-v4-pro'). None or 缺价 => cost_usd
               unavailable even though tokens are still recorded honestly.
        cost_source: self-report | proxy | unavailable (诚实标源).
        """
        if cost_source == UNAVAILABLE:
            # Black-box: we may not even trust the token counts; record what we
            # were given but refuse to price it.
            return _result(in_tok=input_tokens, out_tok=output_tokens,
                           calls=model_calls, cost_usd=None,
                           cost_source=UNAVAILABLE, model=model,
                           price_updated=self.prices.updated)
        if cost_source == NATIVE:
            # 自家原生产品无 LLM 环路: 零成本是可核查事实, 记 cost_usd=0.0 (priced=True),
            # 既不谎称 self-report, 也不标 unavailable(那是"拿不到", 会被误读成很省)。
            return _result(in_tok=input_tokens, out_tok=output_tokens,
                           calls=model_calls, cost_usd=0.0,
                           cost_source=NATIVE, model=model,
                           price_updated=self.prices.updated)
        usd = (self.prices.cost_usd(model, input_tokens, output_tokens)
               if model else None)
        return _result(in_tok=input_tokens, out_tok=output_tokens,
                       calls=model_calls, cost_usd=usd,
                       cost_source=cost_source, model=model,
                       price_updated=self.prices.updated)

    def apply_to_run(self, run, *, model: str | None,
                     input_tokens: int | None = None,
                     output_tokens: int | None = None,
                     model_calls: int | None = None,
                     cost_source: str | None = None) -> dict:
        """Account a RunRecord IN PLACE: write the cost_* fields back onto it,
        then return the contract dict. Token/call/source default to whatever the
        run already carries, so this also works as a 'price an existing run' pass.
        """
        out = self.account(
            model=model,
            input_tokens=run.cost_input_tokens if input_tokens is None else input_tokens,
            output_tokens=run.cost_output_tokens if output_tokens is None else output_tokens,
            model_calls=run.cost_model_calls if model_calls is None else model_calls,
            cost_source=cost_source if cost_source is not None else run.cost_source,
        )
        run.cost_input_tokens = out["cost_input_tokens"]
        run.cost_output_tokens = out["cost_output_tokens"]
        run.cost_model_calls = out["cost_model_calls"]
        run.cost_usd = out["cost_usd"]
        run.cost_source = out["cost_source"]
        return out
