#!/usr/bin/env python3
"""MR-15 (#52) CLI: 实习生机器上把一次运行打成标准交付物压缩包。

这是 pipeline.pack 的命令行皮 —— 客户端打包 skill 调用它。做三件事:
  1. show-recipe: 查某产品的导出配方(自动/半自动/手动 + 分步指引)。
  2. list-recipes: 列已就绪配方。
  3. pack: 组 manifest -> 铺目录 -> 校验 -> 出 zip(缺证据当场拒绝出包)。

诚实边界(与服务端 intake 同源):拿不到的 token 传 "unavailable",绝不填 0;
末态达成由 --assert 人工勾选,绝不从产品自述读成功。

用法示例:
  # 看 simular 怎么导出(闭源、手动)
  python scripts/pack_submission.py show-recipe simular

  # 打包一次 vio 运行(自动:有精确 token)
  python scripts/pack_submission.py pack \
      --product vio --assignment A123 --task T1-wechat-send-001 \
      --artifact ~/runs/vio_shot.png --artifact ~/runs/vio_export.json \
      --input-tokens 5120 --output-tokens 880 --model-calls 6 \
      --model claude-sonnet --cost-source proxy \
      --claimed-success true --assert msg_sent=true \
      --out ~/submissions/vio_T1.zip

  # 打包一次 simular 运行(闭源:token 拿不到 -> 全 unavailable)
  python scripts/pack_submission.py pack \
      --product simular --assignment A123 --task T1-wechat-send-001 \
      --artifact ~/runs/simular_screencast.mp4 \
      --cost-source unavailable --claimed-success false --assert msg_sent=false \
      --out ~/submissions/simular_T1.zip
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from pipeline import pack as PACK  # noqa: E402


def _tok(v):
    """token 参数:未给或字面 'unavailable' -> UNAVAILABLE(诚实缺失);否则 int。"""
    if v is None or str(v).strip().lower() == PACK.UNAVAILABLE:
        return PACK.UNAVAILABLE
    return int(v)


def _bool(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes", "y"):
        return True
    if s in ("false", "0", "no", "n"):
        return False
    raise argparse.ArgumentTypeError(f"不是布尔: {v!r}")


def _kv_pairs(pairs):
    """--assert key=value ... -> {key: 解析后的值}。value 支持 true/false/数字/字符串。"""
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"--assert 需 key=value 形式,得到 {p!r}")
        k, v = p.split("=", 1)
        sv = v.strip().lower()
        if sv in ("true", "false"):
            out[k] = (sv == "true")
        else:
            try:
                out[k] = int(v)
            except ValueError:
                out[k] = v
    return out


def cmd_list_recipes(args):
    ready = PACK.list_recipes()
    print("已就绪导出配方(加新竞品只加一个 <product>.json,打包器代码不动):")
    for pid in ready:
        r = PACK.load_recipe(pid)
        print(f"  {pid:<20} {r.get('export_mode','?'):<10} {r.get('display_name','')}")
    print("\n没配方的产品会退到 _default(手动 + 成本默认 unavailable)。")


def cmd_show_recipe(args):
    r = PACK.load_recipe(args.product)
    if r.get("_fallback"):
        print(f"[{args.product}] 无专属配方 -> 用默认配方(手动、成本 unavailable)。")
    print(json.dumps(r, ensure_ascii=False, indent=2))


def cmd_pack(args):
    cost = {
        "input_tokens": _tok(args.input_tokens),
        "output_tokens": _tok(args.output_tokens),
        "model_calls": _tok(args.model_calls),
    }
    bundle_dir = args.bundle_dir or tempfile.mkdtemp(prefix=f"submission_{args.product}_")
    try:
        result = PACK.pack(
            bundle_dir=bundle_dir,
            product=args.product,
            assignment_id=args.assignment,
            task_id=args.task,
            claimed_success=_bool(args.claimed_success),
            artifact_paths=args.artifact,
            manual_assertions=_kv_pairs(args.assert_),
            cost=cost,
            model=args.model,
            cost_source=args.cost_source,
            evidence_source=args.evidence_source,
            competitor_version=args.competitor_version,
            run_idx=args.run_idx,
            transcript_excerpt=args.transcript or "",
            out_zip=args.out,
        )
    except PACK.PackError as e:
        print(f"打包失败(拒绝出包):{e}", file=sys.stderr)
        return 2

    if result["problems"]:
        print("校验未通过 —— 当场拒绝出包(缺证据别传服务端):", file=sys.stderr)
        for p in result["problems"]:
            print(f"  - {p}", file=sys.stderr)
        print(f"\n已铺目录留在 {result['bundle_dir']} 供你补齐后重跑。", file=sys.stderr)
        return 2

    av = result["manifest"]["availability"]
    unavail = [k for k, ok in av.items() if not ok]
    print(f"✅ 出包成功: {result['zip']}")
    print(f"   产品={args.product}  任务={args.task}  assignment={args.assignment}")
    if unavail:
        print(f"   如实标 unavailable 的字段(不伪装成 0): {', '.join(unavail)}")
    print("   上传此 zip 到评测服务,intake 会解包翻译成 RunRecord。")
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description="交付物打包器 (MR-15 #52)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-recipes").set_defaults(func=cmd_list_recipes)

    sr = sub.add_parser("show-recipe")
    sr.add_argument("product")
    sr.set_defaults(func=cmd_show_recipe)

    pk = sub.add_parser("pack")
    pk.add_argument("--product", required=True)
    pk.add_argument("--assignment", required=True)
    pk.add_argument("--task", required=True)
    pk.add_argument("--artifact", action="append", required=True,
                    help="原始产物文件/目录(可多次);至少一个非空,否则拒收")
    pk.add_argument("--log", help="(可选)已导出的日志包 JSON;不给则写占位包(字段 unavailable)")
    pk.add_argument("--input-tokens", help="int 或 'unavailable'(拿不到别填 0)")
    pk.add_argument("--output-tokens", help="int 或 'unavailable'")
    pk.add_argument("--model-calls", help="int 或 'unavailable'")
    pk.add_argument("--model", help="用的模型名(看得到才填,看不到留空)")
    pk.add_argument("--cost-source", default="self-report",
                    choices=list(PACK.COST_SOURCE_VALUES))
    pk.add_argument("--evidence-source", default="log",
                    choices=list(PACK.EVIDENCE_SOURCE_VALUES))
    pk.add_argument("--competitor-version")
    pk.add_argument("--run-idx", type=int, default=1)
    pk.add_argument("--transcript", help="AI 对话记录摘录(透传给 intake)")
    pk.add_argument("--claimed-success",
                    help="该产品是否『自称』完成 true/false(自报占位,喂 H1)")
    pk.add_argument("--assert", dest="assert_", action="append",
                    help="人工勾选的客观断言 key=value(你核对末态后填,绝不自证)")
    pk.add_argument("--bundle-dir", help="铺包目录(默认临时目录)")
    pk.add_argument("--out", help="输出 zip 路径(默认 <bundle-dir>.zip)")
    pk.set_defaults(func=cmd_pack)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    # --log 覆盖:若给了已导出的日志包,读进来当 log_facts。
    if getattr(args, "log", None):
        lp = pathlib.Path(args.log).expanduser()
        if not lp.exists():
            print(f"--log 指向的文件不存在: {lp}", file=sys.stderr)
            return 2
        # pack() 内部默认从 manifest 派生 log_facts;这里直接把导出的日志接线进去。
        raw = json.loads(lp.read_text())
        # #7 修复: intake 解析器只认扁平 input_tokens/output_tokens/model_calls。
        # 很多导出日志把 token 塞在嵌套 cost{} 对象里(或用 cost_input_tokens 别名),
        # 直接透传会让服务端读到 None -> 成本静默丢失。这里统一抬平到扁平字段。
        raw = _flatten_log_cost(raw)
        # 显式 --input-tokens 等参数与 --log 里的值冲突时: 显式参数优先并告警
        # (--log 是"已导出日志", 但实习生手动核对后的显式值更权威)。
        for flat, cli in (("input_tokens", args.input_tokens),
                          ("output_tokens", args.output_tokens),
                          ("model_calls", args.model_calls)):
            cval = _tok(cli)
            if cval is not None and cval != PACK.UNAVAILABLE:
                if raw.get(flat) not in (None, cval):
                    print(f"[warn] --{flat.replace('_','-')}={cval} 覆盖 --log 里的 "
                          f"{flat}={raw.get(flat)}", file=sys.stderr)
                raw[flat] = int(cval)
        _orig = PACK.pack

        def _pack_with_log(**kw):
            kw["log_facts"] = raw
            return _orig(**kw)
        PACK.pack = _pack_with_log
    return args.func(args)


def _flatten_log_cost(raw: dict) -> dict:
    """把日志包里嵌套/别名的 token 字段抬平成 intake 认识的扁平字段。

    intake 的 LogBundleParser 只读扁平 input_tokens / output_tokens / model_calls。
    容忍两种常见变体, 抬平到扁平键(已存在的扁平键不覆盖):
      * 嵌套 cost 对象: {"cost": {"input_tokens": 155, ...}}
      * cost_ 前缀别名: {"cost_input_tokens": 155, ...}
    """
    if not isinstance(raw, dict):
        return raw
    out = dict(raw)
    nested = out.get("cost") if isinstance(out.get("cost"), dict) else {}
    for f in ("input_tokens", "output_tokens", "model_calls"):
        if out.get(f) is None:
            if nested.get(f) is not None:
                out[f] = nested[f]
            elif out.get(f"cost_{f}") is not None:
                out[f] = out[f"cost_{f}"]
    # model / cost_source 同样容忍嵌套。
    for f in ("model", "cost_source"):
        if out.get(f) is None and nested.get(f) is not None:
            out[f] = nested[f]
    return out


if __name__ == "__main__":
    raise SystemExit(main())
