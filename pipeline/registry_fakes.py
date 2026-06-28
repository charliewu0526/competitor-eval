"""F2 in-memory fake registry — the offline twin of FileRegistry.

Per PRD "适配器各自用假实现测": every adapter ships a production impl AND an
in-memory fake honoring the SAME contract. The fake NEVER touches IO — it holds a
fixed competitor list in memory so the seam can't tell the two apart and tests
stay deterministic + offline.
"""
from __future__ import annotations
from pipeline.registry import BaseRegistry, Competitor


class FakeRegistry(BaseRegistry):
    """In-memory registry. Mutable via add(); no disk, no DB."""

    def __init__(self, competitors: list[Competitor] | None = None) -> None:
        self._items: list[Competitor] = list(competitors) if competitors else []

    def _load(self) -> list[Competitor]:
        return self._items

    def add(self, comp: Competitor) -> str:
        if any(c.id == comp.id for c in self._items):
            raise ValueError(f"duplicate competitor id: {comp.id!r}")
        self._items.append(comp)
        return self.blind_label(comp.id)


# A ready-made fixed set mirroring the real seed (vio baseline first => Product A).
FAKE_COMPETITORS = [
    Competitor("vio", "Violoop", can_operate_local_desktop=True),
    Competitor("open_interpreter", "Open Interpreter",
               can_operate_local_desktop=True, is_open_source=True,
               repo="https://github.com/OpenInterpreter/open-interpreter"),
    Competitor("simular", "Simular", can_operate_local_desktop=True),
]


def make_fake_registry() -> FakeRegistry:
    return FakeRegistry(list(FAKE_COMPETITORS))
