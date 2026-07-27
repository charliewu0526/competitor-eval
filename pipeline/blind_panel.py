"""MR-10 (#46): 送评审面板前打乱产品标签 + 每份交付物独立打分 (ADR-0012).

盲评的两条铁律,在这一层落地(评分核心 orchestrate.score_run 一字不改复用):

  1. 打乱标签(#46 AC1):送面板前给每个产品一个 Product A/B/C… 标签,标签复用
     registry 的 blind_letter,但**顺序被随机置换**——不能用注册序,否则 vio 恒为
     Product A、面板一眼看穿自家,盲评就失效了。产品 id ↔ 盲标签是双射:面板只见
     标签,聚合 / 排行 / gap 仍按真实 id 归位。

  2. 独立打分(#46 AC2):每份 Submission 各自跑一次 score_run,产品之间零耦合——
     差距 = 独立分数差(可被黄金集锚定),绝不做成对对比(A 比 B 好这类相对判断会
     让分数无法被绝对校准)。

  3. 面板看脱敏日志(#46 AC3):喂给面板的 process evidence(transcript 摘录 /
     artifact 摘要 / 事件时间线)先经 logview.make_redactor 洗掉品牌 / 模型指纹,
     面板拿不到产品身份线索。原始 RunRecord(成本 / 抽查用)照常落库不脱敏。

  4. 端到端(#46 AC4):真实 Submission → intake.translate → 独立盲评分 → 落库,
     榜单按真实 id 出分带版本 / 日期。

这是编排层,不是新评分逻辑:translate 复用 intake(唯一新接缝),打分复用
orchestrate.score_run,脱敏复用 logview,标签复用 registry.blind_letter。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from pipeline import orchestrate as ORCH
from pipeline import intake as IN
from pipeline.registry import blind_letter
from pipeline.logview import make_redactor


# --- 1. 打乱标签 --------------------------------------------------------------
def shuffle_blind_labels(products, *, rng=None, seed=None) -> dict[str, str]:
    """给一组产品 id 派发**打乱顺序**的盲标签 {product_id: "Product X"}.

    标签取值仍是 registry.blind_letter 那套(Product A/B/C… 双射永不撞、永不耗尽),
    但产品→标签的配对被随机置换,所以基准产品(vio)不会稳定落在 Product A,面板
    无从按位置反推身份。传 seed / rng 让测试可复现(注入确定性顺序)。

    去重且保持「产品集合稳定 => 标签集合稳定」:置换的是配对,不是标签取值。
    """
    ids = list(dict.fromkeys(products))          # 去重,保序仅为确定输入
    labels = [blind_letter(i) for i in range(len(ids))]
    r = rng or random.Random(seed)
    r.shuffle(labels)                            # 打乱的是配对,标签集合不变
    return dict(zip(ids, labels))


# --- 2. 脱敏面板上下文 --------------------------------------------------------
def _redacted_panel_ctx(run, base_ctx, redactor) -> dict:
    """构造喂给面板的 ctx:洗掉 process evidence 里的品牌 / 模型指纹 (#46 AC3).

    面板通过 orchestrate.score_run 读 ctx 的 artifact_summary / screenshots_note /
    transcript(经 run.transcript_excerpt)。这里把这些字符串都过一遍 redactor,
    面板拿到的证据不含任何产品身份线索。数值事实(成本 / 断言结果)不经面板,不动。
    """
    ctx = dict(base_ctx or {})
    ctx["artifact_summary"] = redactor.redact_text(
        ctx.get("artifact_summary", "(none)"))
    ctx["screenshots_note"] = redactor.redact_text(
        ctx.get("screenshots_note", "(none)"))
    return ctx


def _blind_run(run, redactor):
    """派生一个「面板视图」的 RunRecord:仅 transcript_excerpt 被脱敏.

    score_run 会从 run.transcript_excerpt 取 trimmed transcript 喂面板,故必须洗。
    其余字段(gate / objective / cost)不喂面板文本、且是打分/落库依据,原样保留——
    我们浅拷贝一份只改 transcript,不污染将要落库的原始 run。
    """
    import copy
    view = copy.copy(run)
    view.transcript_excerpt = redactor.redact_text(run.transcript_excerpt or "")
    return view


# --- 3. 独立盲评一份交付物 ----------------------------------------------------
@dataclass
class BlindScore:
    """一份交付物的独立盲评结果:真实 id + 盲标签 + score_run 输出 + 原始 run.

    product      : 真实产品 id(聚合 / 落库 / gap 用,面板看不到)。
    blind_label  : 送面板时用的打乱标签(Product X)。
    score        : orchestrate.score_run 的输出 dict(独立打分,非成对)。
    run          : 原始 RunRecord(未脱敏,成本 / 抽查 / 落库用)。
    """
    product: str
    blind_label: str
    score: dict
    run: object


def score_submissions(submissions, task_meta, registry, *,
                      translator=None, ctx_by_product=None,
                      rng=None, seed=None,
                      price_table=None) -> list[BlindScore]:
    """一道对比任务的全部 Submission → 独立盲评分列表 (#46 AC1/AC2/AC3).

    submissions   : 同一道 Assignment 下每个产品各一份 Submission(intake.Submission)。
    task_meta     : duck-typed suite.LoadedTask(.task_spec + .assertions),同 intake。
    registry      : F2 registry — 派生 GATE + 品牌脱敏词典 + 盲标签取值。
    translator    : intake 翻译器(缺省用生产 SubmissionTranslator);注入假实现离线测。
    ctx_by_product: {product_id: ctx dict} 每份交付物的 artifact/screenshots 摘要。
    rng/seed      : 注入确定性置换(测试复现)。

    步骤:①一次性给所有产品打乱盲标签(同一道题内一致);②逐份 translate 成
    RunRecord(独立,产品间零耦合);③脱敏 process evidence;④用打乱后的标签调
    score_run 独立打分。返回真实 id ↔ 盲标签 ↔ 分数 ↔ 原始 run 的对账列表。
    """
    subs = list(submissions)
    tr = translator or IN.SubmissionTranslator()
    ctx_by_product = ctx_by_product or {}
    parser = getattr(tr, "log_parser", None) or IN.LogBundleParser()

    # ① 送面板前打乱标签(同题一致:一次派发,所有产品共用这份映射)。
    label_map = shuffle_blind_labels((s.product for s in subs), rng=rng, seed=seed)

    out: list[BlindScore] = []
    for sub in subs:
        # ② 独立翻译:每份交付物各自成 RunRecord,产品之间不互相参照。
        run = tr.translate(sub, task_meta, registry)
        blind = label_map[sub.product]

        # ③ 脱敏词典 DERIVED 自 registry(品牌)+ 价表(模型)+ 本包实际用的 model
        #    名 —— 与 logview 日志双视图同源。闭源竞品常用价表外模型,故必须把该份
        #    日志里的 model 也纳入指纹,否则 transcript 里的模型名会漏进面板破盲。
        facts = parser.parse(sub.log_bundle_path)
        m = facts.get("model")
        extra = (m,) if (m and str(m).strip()) else ()
        redactor = make_redactor(registry, price_table, extra_terms=extra)

        panel_ctx = _redacted_panel_ctx(run, ctx_by_product.get(sub.product), redactor)
        panel_run = _blind_run(run, redactor)
        # ④ 独立打分:用打乱后的盲标签,score_run 不知道也不需要真实身份。
        sc = ORCH.score_run(task_meta.task_spec, panel_run, panel_ctx, blind)
        # 分数按**真实** id 归位(面板盲的是身份,不是归属);带上新鲜度。
        sc["product"] = run.product
        sc["competitor_version"] = run.competitor_version
        sc["tested_at"] = run.tested_at
        out.append(BlindScore(product=run.product, blind_label=blind,
                              score=sc, run=run))
    return out


# --- 4. 端到端:独立盲评分落库 ------------------------------------------------
def persist_blind_scores(con, blind_scores) -> None:
    """把独立盲评结果落库:原始 RunRecord + score,均按真实 id (#46 AC4).

    落库的是**未脱敏**的原始 run(成本 / 抽查要真数据)与按真实 id 归位的 score。
    脱敏只作用于「送面板」这一瞬,不改变持久化事实——盲评不篡改结论。
    """
    from pipeline import store as STORE
    for bs in blind_scores:
        STORE.upsert_run(con, bs.run)
        STORE.upsert_score(con, bs.score)
    con.commit()
