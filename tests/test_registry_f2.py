"""F2: competitor registry adapter tests. Stdlib unittest (no pytest dep).

Run: python -m unittest tests.test_registry_f2 -v

Covers acceptance:
- production FileRegistry reads from file -> competitor set
- in-memory FakeRegistry returns fixed set, no IO
- BOTH impls satisfy ONE contract (same suite runs against both)
- blind A/B/C dispatched by registration order, adding competitor needs no code
- add a competitor -> auto-gets the next blind letter
"""
from __future__ import annotations
import json, tempfile, unittest, pathlib
from pipeline.registry import (
    FileRegistry, Competitor, blind_letter, STATUS_VALUES, DEFAULT_PATH,
)
from pipeline.registry_fakes import FakeRegistry, make_fake_registry, FAKE_COMPETITORS


class BlindLetter(unittest.TestCase):
    def test_order_to_letter(self):
        self.assertEqual(blind_letter(0), "Product A")
        self.assertEqual(blind_letter(1), "Product B")
        self.assertEqual(blind_letter(25), "Product Z")

    def test_overflow_past_z(self):
        # never runs out: 26 -> AA, 27 -> AB
        self.assertEqual(blind_letter(26), "Product AA")
        self.assertEqual(blind_letter(27), "Product AB")


class CompetitorModel(unittest.TestCase):
    def test_requires_id(self):
        with self.assertRaises(ValueError):
            Competitor(id="", display_name="x")

    def test_bad_status_rejected(self):
        with self.assertRaises(ValueError):
            Competitor(id="x", display_name="X", status="zombie")

    def test_reachable_envs_reserved_default_empty(self):
        c = Competitor(id="x", display_name="X")
        self.assertEqual(c.reachable_envs, [])
        self.assertFalse(c.can_operate_local_desktop)


# ---- One contract, two implementations -------------------------------------
# A mixin holding every contract assertion; two TestCase subclasses bind it to
# the production FileRegistry and the in-memory FakeRegistry. If either drifts,
# the SAME test fails — that's what "two adapters prove one seam" means.
class _RegistryContract:
    def make_registry(self, competitors):
        raise NotImplementedError

    SEED = [
        Competitor("vio", "Violoop", can_operate_local_desktop=True),
        Competitor("rival_one", "Rival One", can_operate_local_desktop=True),
        Competitor("rival_two", "Rival Two", is_open_source=True,
                   repo="https://example.com/r2"),
    ]

    def test_competitors_in_registration_order(self):
        r = self.make_registry(self.SEED)
        self.assertEqual([c.id for c in r.competitors()],
                         ["vio", "rival_one", "rival_two"])

    def test_get_by_id(self):
        r = self.make_registry(self.SEED)
        self.assertEqual(r.get("rival_two").display_name, "Rival Two")
        with self.assertRaises(KeyError):
            r.get("nope")

    def test_blind_map_by_order(self):
        r = self.make_registry(self.SEED)
        self.assertEqual(r.blind_map(),
                         {"vio": "Product A", "rival_one": "Product B",
                          "rival_two": "Product C"})

    def test_blind_label_lookup(self):
        r = self.make_registry(self.SEED)
        self.assertEqual(r.blind_label("vio"), "Product A")
        with self.assertRaises(KeyError):
            r.blind_label("ghost")

    def test_add_competitor_gets_next_letter(self):
        # the headline acceptance test: append -> auto next blind letter, no code change
        r = self.make_registry(self.SEED)
        label = self._append(r, Competitor("rival_three", "Rival Three"))
        self.assertEqual(label, "Product D")
        self.assertEqual(r.blind_label("rival_three"), "Product D")
        self.assertEqual([c.id for c in r.competitors()][-1], "rival_three")

    def test_duplicate_id_rejected(self):
        r = self.make_registry(self.SEED)
        with self.assertRaises(ValueError):
            self._append(r, Competitor("vio", "Dup"))


class FakeRegistryContract(_RegistryContract, unittest.TestCase):
    def make_registry(self, competitors):
        return FakeRegistry(list(competitors))

    def _append(self, r, comp):
        return r.add(comp)


class FileRegistryContract(_RegistryContract, unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def make_registry(self, competitors):
        from dataclasses import asdict
        p = pathlib.Path(self._tmp.name) / "competitors.json"
        p.write_text(json.dumps([asdict(c) for c in competitors], ensure_ascii=False))
        return FileRegistry(p)

    def _append(self, r, comp):
        return r.register(comp)


class FileRegistryPersistence(unittest.TestCase):
    def test_register_persists_to_disk(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "competitors.json"
            p.write_text(json.dumps([{"id": "vio", "display_name": "Violoop"}]))
            r = FileRegistry(p)
            r.register(Competitor("simular", "Simular", can_operate_local_desktop=True))
            # a fresh reader sees the appended competitor + correct letter
            r2 = FileRegistry(p)
            self.assertEqual([c.id for c in r2.competitors()], ["vio", "simular"])
            self.assertEqual(r2.blind_label("simular"), "Product B")


class SeedRegistryFile(unittest.TestCase):
    def test_shipped_seed_loads_and_vio_is_product_a(self):
        # the real registry/competitors.json must load and put baseline first
        r = FileRegistry(DEFAULT_PATH)
        comps = r.competitors()
        self.assertTrue(comps, "seed registry is empty")
        self.assertEqual(comps[0].id, "vio")
        self.assertEqual(r.blind_label("vio"), "Product A")

    def test_fake_seed_matches_contract(self):
        r = make_fake_registry()
        self.assertEqual(r.blind_label("vio"), "Product A")
        self.assertEqual(len(r.competitors()), len(FAKE_COMPETITORS))


if __name__ == "__main__":
    unittest.main()
