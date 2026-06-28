"""F2: competitor registry — the 5th adapter (file/DB <-> competitor set).

Static record per competitor:
  { id, display_name, can_operate_local_desktop:bool, is_open_source, repo, status }
Capability domain is a bool in v1; `reachable_envs[]` is reserved so it can be
upgraded to a multi-env list later WITHOUT a schema break (PRD module note).

Blind labels (Product A/B/C ...) are dispatched by REGISTRATION ORDER, never
hardcoded — so adding a competitor means editing the table, not the code.

Contract (shared by FileRegistry + FakeRegistry, see registry_fakes):
  .competitors()      -> list[Competitor]   (registration order)
  .get(cid)           -> Competitor          (KeyError if absent)
  .blind_map()        -> {id: "Product X"}   (order-derived)
  .blind_label(cid)   -> "Product X"
Two impls honoring one contract = the seam holds (PRD "两个适配器证明一个接缝").
"""
from __future__ import annotations
import json, pathlib, string
from dataclasses import dataclass, field, asdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "registry" / "competitors.json"

STATUS_VALUES = ("active", "candidate", "retired")


@dataclass
class Competitor:
    id: str
    display_name: str
    can_operate_local_desktop: bool = False
    is_open_source: bool = False
    repo: str | None = None
    status: str = "active"                  # STATUS_VALUES
    # --- reserved future upgrade path (PRD): bool domain -> env list ---
    reachable_envs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("competitor id is required")
        if self.status not in STATUS_VALUES:
            raise ValueError(f"status must be one of {STATUS_VALUES}, got {self.status!r}")


def blind_letter(idx: int) -> str:
    """0->A, 25->Z, 26->AA ... bijective base-26, never runs out of labels."""
    s, n = "", idx
    while True:
        s = string.ascii_uppercase[n % 26] + s
        n = n // 26 - 1
        if n < 0:
            return f"Product {s}"


class BaseRegistry:
    """Shared contract. Subclasses implement _load() -> list[Competitor]."""

    def _load(self) -> list[Competitor]:
        raise NotImplementedError

    def competitors(self) -> list[Competitor]:
        return list(self._load())

    def get(self, cid: str) -> Competitor:
        for c in self._load():
            if c.id == cid:
                return c
        raise KeyError(cid)

    def blind_map(self) -> dict[str, str]:
        # registration order is the ONLY thing that decides the letter
        return {c.id: blind_letter(i) for i, c in enumerate(self._load())}

    def blind_label(self, cid: str) -> str:
        m = self.blind_map()
        if cid not in m:
            raise KeyError(cid)
        return m[cid]


class FileRegistry(BaseRegistry):
    """Production impl: reads the registry from a JSON file (or any DB later)."""

    def __init__(self, path: str | pathlib.Path | None = None) -> None:
        self.path = pathlib.Path(path) if path else DEFAULT_PATH

    def _load(self) -> list[Competitor]:
        data = json.loads(self.path.read_text())
        return [Competitor(**d) for d in data]

    def register(self, comp: Competitor) -> str:
        """Append a competitor and persist. New id -> next blind letter, no code change."""
        items = self._load()
        if any(c.id == comp.id for c in items):
            raise ValueError(f"duplicate competitor id: {comp.id!r}")
        items.append(comp)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(c) for c in items],
                                        ensure_ascii=False, indent=2))
        return self.blind_label(comp.id)


# Module-level convenience: the default production registry.
def default_registry() -> FileRegistry:
    return FileRegistry()
