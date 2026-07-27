"""MR-15 (#52): 客户端交付物打包器 + 校验器 + 每竞品导出配方.

Run: python -m unittest tests.test_pack_mr15 -v

Acceptance (issue #52), all OFFLINE:
  - AC1 打包器产出结构固定的标准压缩包(manifest.json + artifacts/ + logs/)
  - AC2 压缩包结构与 #37 Submission schema 对齐 —— 服务端 intake 能解包翻译成 RunRecord
  - AC3 vio 走自动(精确 token);simular 走手动(闭源)—— 至少各一
  - AC4 拿不到的字段如实标 unavailable,校验器放行(不伪装成 0)
  - AC5 校验器:缺日志 / 缺原始产物 / 字段缺失未标 unavailable -> 当场拒绝出包
  - AC6 manifest 标产品身份(供服务端脱敏);skill 不做脱敏、不判末态
  - AC7 至少 vio + 一个竞品配方就绪,配方可扩展(加竞品 = 加 JSON 不改码)

立身之本回归:打包器只收证据 + 如实标缺失,绝不从产品自述读成功;末态达成由
manual_assertions 人工勾选,claimed_success 只是自报占位喂 H1。
"""
from __future__ import annotations
import json
import pathlib
import tempfile
import unittest
import zipfile

from pipeline import pack as PACK
from pipeline import intake as IN


def _tmp() -> pathlib.Path:
    return pathlib.Path(tempfile.mkdtemp())


def _artifact(root: pathlib.Path, name="shot.png", body="pixels") -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    p = root / name
    p.write_text(body)
    return p


def _pack_vio(bundle_dir, art):
    """一次典型的 vio 自动打包(精确 token)。"""
    return PACK.pack(
        bundle_dir=bundle_dir, product="vio", assignment_id="A1",
        task_id="T1-wechat-send-001", claimed_success=True,
        artifact_paths=[str(art)],
        cost={"input_tokens": 5120, "output_tokens": 880, "model_calls": 6},
        model="claude-sonnet", cost_source="proxy",
        manual_assertions={"msg_sent": True})


def _pack_simular(bundle_dir, art):
    """一次典型的 simular 手动打包(闭源:token 拿不到 -> unavailable)。"""
    return PACK.pack(
        bundle_dir=bundle_dir, product="simular", assignment_id="A1",
        task_id="T1-wechat-send-001", claimed_success=False,
        artifact_paths=[str(art)],
        cost={"input_tokens": PACK.UNAVAILABLE, "output_tokens": PACK.UNAVAILABLE,
              "model_calls": PACK.UNAVAILABLE},
        cost_source="unavailable", manual_assertions={"msg_sent": False})


# =============================================================================
# AC1 + AC3: 标准压缩包结构 + vio 自动 / simular 手动 各一
# =============================================================================
class BundleStructure(unittest.TestCase):
    def test_vio_auto_bundle_has_fixed_structure(self):
        t = _tmp()
        art = _artifact(t / "in")
        res = _pack_vio(t / "b", art)
        self.assertEqual(res["problems"], [])
        self.assertTrue(res["zip"])
        # 固定结构三件套。
        with zipfile.ZipFile(res["zip"]) as z:
            names = set(z.namelist())
        self.assertIn(PACK.MANIFEST_NAME, names)
        self.assertIn(PACK.LOG_FILE, names)
        self.assertTrue(any(n.startswith(PACK.ARTIFACTS_DIR + "/") for n in names))

    def test_vio_records_precise_tokens(self):
        t = _tmp()
        res = _pack_vio(t / "b", _artifact(t / "in"))
        m = res["manifest"]
        self.assertEqual(m["cost"]["input_tokens"], 5120)
        self.assertEqual(m["cost_source"], "proxy")
        self.assertTrue(m["availability"]["input_tokens"])

    def test_simular_manual_all_unavailable(self):
        t = _tmp()
        res = _pack_simular(t / "b", _artifact(t / "in"))
        self.assertEqual(res["problems"], [])
        m = res["manifest"]
        for f in PACK.COST_FIELDS:
            self.assertEqual(m["cost"][f], PACK.UNAVAILABLE)
            self.assertFalse(m["availability"][f])
        self.assertEqual(m["cost_source"], "unavailable")


# =============================================================================
# AC2: 压缩包解开 = 一份 Submission,服务端 intake 能翻译成 RunRecord(真穿通)
# =============================================================================
class IntakeRoundTrip(unittest.TestCase):
    """打包器产出 -> 解包 -> intake.Submission -> translate -> RunRecord.

    用真 intake 翻译器(非 fake),证明压缩包契约与 #37/#38 服务端严丝合缝。
    task_meta / registry 用最小 duck-type,聚焦「字段对齐」这一件事。
    """
    def _unpack_to_submission(self, zip_path, extract_dir):
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extract_dir)
        manifest = json.loads((extract_dir / PACK.MANIFEST_NAME).read_text())
        # 服务端 intake 侧的解包翻译:manifest 字段 -> intake.Submission。
        return IN.Submission(
            assignment_id=manifest["assignment_id"],
            product=manifest["product"],
            task_id=manifest["task_id"],
            run_idx=manifest["run_idx"],
            artifact_path=str(extract_dir / PACK.ARTIFACTS_DIR),
            log_bundle_path=str(extract_dir / PACK.LOG_FILE),
            manual_assertions=manifest["manual_assertions"],
            claimed_success=manifest["claimed_success"],
            transcript_excerpt=manifest.get("transcript_excerpt", ""),
            competitor_version=manifest.get("competitor_version"),
            tested_at=manifest.get("tested_at"),
        ), manifest

    def _fake_meta_and_registry(self, product):
        from pipeline import objective as O
        from pipeline.schema import TaskSpec
        from pipeline.registry import Competitor

        spec = TaskSpec(task_id="T1-wechat-send-001", domain="1", app="wechat",
                        prompt="发条微信", core_assertions=["消息真发出了"],
                        requires_local_desktop=True)

        class Meta:
            task_spec = spec
            @staticmethod
            def assertions():
                return [O.manual_check("消息真发出了", "msg_sent", primary=True)]

        comp = Competitor(id=product, display_name=product,
                          can_operate_local_desktop=True, is_open_source=False)

        class Reg:
            @staticmethod
            def get(cid):
                if cid != product:
                    raise KeyError(cid)
                return comp
        return Meta(), Reg()

    def test_vio_bundle_translates_to_runrecord(self):
        t = _tmp()
        res = _pack_vio(t / "b", _artifact(t / "in"))
        sub, manifest = self._unpack_to_submission(res["zip"], t / "unpacked")
        meta, reg = self._fake_meta_and_registry("vio")
        rr = IN.translate(sub, meta, reg)
        # cost 从解出的日志包真解析(精确 token 一路带到 RunRecord)。
        self.assertEqual(rr.cost_input_tokens, 5120)
        self.assertEqual(rr.cost_source, "proxy")
        # claimed_success 透传喂 H1;末态由人工勾选断言判(msg_sent=True -> 通过)。
        self.assertTrue(rr.claimed_success)
        self.assertEqual(rr.objective_passed, 1)
        self.assertEqual(rr.product, "vio")

    def test_simular_unavailable_translates_honestly(self):
        t = _tmp()
        res = _pack_simular(t / "b", _artifact(t / "in"))
        sub, manifest = self._unpack_to_submission(res["zip"], t / "unpacked")
        meta, reg = self._fake_meta_and_registry("simular")
        rr = IN.translate(sub, meta, reg)
        # 闭源拿不到 -> cost_source 保持 unavailable,绝不折算成一个假 $ 成功。
        self.assertEqual(rr.cost_source, "unavailable")
        # 人工勾选 msg_sent=False -> primary 断言失败(诚实反映没做成)。
        self.assertEqual(rr.objective_passed, 0)
        self.assertFalse(rr.claimed_success)


# =============================================================================
# AC4: 拿不到如实标 unavailable,校验器放行(不伪装成 0)
# =============================================================================
class UnavailablePassesValidator(unittest.TestCase):
    def test_all_unavailable_bundle_valid(self):
        t = _tmp()
        res = _pack_simular(t / "b", _artifact(t / "in"))
        self.assertEqual(PACK.validate_bundle_dir(res["bundle_dir"]), [])

    def test_unavailable_is_not_zero(self):
        # 关键回归:标 unavailable 与「填 0」在 manifest 里是两种东西。
        t = _tmp()
        res = _pack_simular(t / "b", _artifact(t / "in"))
        self.assertEqual(res["manifest"]["cost"]["input_tokens"], "unavailable")
        self.assertNotEqual(res["manifest"]["cost"]["input_tokens"], 0)


# =============================================================================
# AC5: 校验器当场拒绝出包 —— 缺日志 / 缺产物 / 字段沉默缺失 / source 矛盾
# =============================================================================
class ValidatorRejects(unittest.TestCase):
    def test_missing_artifact_rejected(self):
        t = _tmp()
        # 铺一个只有 manifest + log、artifacts 空的目录。
        m = PACK.build_manifest(product="vio", assignment_id="A1",
                                task_id="T1-wechat-send-001", claimed_success=True,
                                cost={"input_tokens": 1, "output_tokens": 1,
                                      "model_calls": 1}, model="x")
        PACK.stage_bundle(t / "b", manifest=m, artifact_paths=[])
        problems = PACK.validate_bundle_dir(t / "b")
        self.assertTrue(any("原始产物" in p for p in problems))
        with self.assertRaises(PACK.PackError):
            PACK.zip_bundle(t / "b")

    def test_missing_log_rejected(self):
        t = _tmp()
        m = PACK.build_manifest(product="vio", assignment_id="A1",
                                task_id="T1-wechat-send-001", claimed_success=True,
                                cost={"input_tokens": 1, "output_tokens": 1,
                                      "model_calls": 1}, model="x")
        PACK.stage_bundle(t / "b", manifest=m, artifact_paths=[str(_artifact(t / "in"))])
        # 删掉日志包文件模拟没交包。
        (pathlib.Path(t / "b") / PACK.LOG_FILE).unlink()
        problems = PACK.validate_bundle_dir(t / "b")
        self.assertTrue(any("日志包" in p for p in problems))

    def test_silent_missing_field_rejected(self):
        # 成本字段既没真值也没标 unavailable -> 沉默缺失,拒收(会被误当 0)。
        bad = {"schema": PACK.MANIFEST_SCHEMA, "product": "vio",
               "assignment_id": "A1", "task_id": "T1",
               "cost_source": "self-report", "evidence_source": "log",
               "cost": {"input_tokens": 5}}  # 缺 output_tokens / model_calls
        problems = PACK.validate_manifest(bad)
        self.assertTrue(any("output_tokens" in p for p in problems))
        self.assertTrue(any("model_calls" in p for p in problems))

    def test_zero_is_not_unavailable(self):
        # 显式填 0 是合法(断言「真花了 0」),但不等于 unavailable —— 校验器都放行,
        # 语义区别留给 availability/cost_source 表达。这里确认 0 不被误拒。
        ok = {"schema": PACK.MANIFEST_SCHEMA, "product": "vio",
              "assignment_id": "A1", "task_id": "T1",
              "cost_source": "self-report", "evidence_source": "log",
              "cost": {"input_tokens": 0, "output_tokens": 0, "model_calls": 0}}
        self.assertEqual(PACK.validate_manifest(ok), [])

    def test_source_unavailable_but_real_tokens_contradiction(self):
        bad = {"schema": PACK.MANIFEST_SCHEMA, "product": "x",
               "assignment_id": "A1", "task_id": "T1",
               "cost_source": "unavailable", "evidence_source": "log",
               "cost": {"input_tokens": 99, "output_tokens": "unavailable",
                        "model_calls": "unavailable"}}
        problems = PACK.validate_manifest(bad)
        self.assertTrue(any("自相矛盾" in p for p in problems))


# =============================================================================
# AC6: manifest 标产品身份(供服务端脱敏);打包器不脱敏、不判末态
# =============================================================================
class ManifestIdentityForRedaction(unittest.TestCase):
    def test_manifest_carries_product_identity(self):
        t = _tmp()
        res = _pack_simular(t / "b", _artifact(t / "in"))
        self.assertEqual(res["manifest"]["product"], "simular")
        self.assertEqual(res["manifest"]["schema"], PACK.MANIFEST_SCHEMA)

    def test_packer_does_not_redact(self):
        # 打包器只收原始,不洗品牌/模型指纹(脱敏是服务端 logview 的活,ADR-0013)。
        t = _tmp()
        res = _pack_vio(t / "b", _artifact(t / "in"))
        log = json.loads((pathlib.Path(res["bundle_dir"]) / PACK.LOG_FILE).read_text())
        self.assertEqual(log["model"], "claude-sonnet")  # 原始模型名保留,未脱敏

    def test_packer_does_not_judge_end_state(self):
        # 末态由 manual_assertions 人工勾选;打包器绝不从 claimed_success 推末态达成。
        t = _tmp()
        res = PACK.pack(
            bundle_dir=t / "b", product="vio", assignment_id="A1",
            task_id="T1-wechat-send-001",
            claimed_success=True,               # 自称成功……
            manual_assertions={"msg_sent": False},  # ……但人工勾选没做成
            artifact_paths=[str(_artifact(t / "in"))],
            cost={"input_tokens": 1, "output_tokens": 1, "model_calls": 1},
            model="x", cost_source="self-report")
        # 打包器如实并存两者,不替竞品「读」成功。
        self.assertTrue(res["manifest"]["claimed_success"])
        self.assertFalse(res["manifest"]["manual_assertions"]["msg_sent"])


# =============================================================================
# AC7: 配方就绪 + 可扩展(加竞品 = 加 JSON 不改码)
# =============================================================================
class RecipesExtensible(unittest.TestCase):
    def test_vio_and_competitor_recipes_ready(self):
        ready = PACK.list_recipes()
        self.assertIn("vio", ready)
        self.assertIn("simular", ready)
        self.assertGreaterEqual(len(ready), 2)

    def test_unknown_product_falls_back_to_default(self):
        r = PACK.load_recipe("some_new_agent_2099")
        self.assertTrue(r.get("_fallback"))
        self.assertEqual(r["product"], "some_new_agent_2099")

    def test_new_recipe_picked_up_without_code_change(self):
        # 往一个隔离 recipe 目录丢新 JSON -> load_recipe 立刻认得,无需改代码。
        t = _tmp()
        (t / "newcomer.json").write_text(json.dumps(
            {"display_name": "Newcomer", "export_mode": "auto",
             "cost_source": "self-report", "evidence_source": "log"}))
        r = PACK.load_recipe("newcomer", recipe_dir=t)
        self.assertEqual(r["display_name"], "Newcomer")
        self.assertNotIn("_fallback", r)

    def test_vio_recipe_is_auto_simular_is_manual(self):
        self.assertEqual(PACK.load_recipe("vio")["export_mode"], "auto")
        self.assertEqual(PACK.load_recipe("simular")["export_mode"], "manual")


if __name__ == "__main__":
    unittest.main()
