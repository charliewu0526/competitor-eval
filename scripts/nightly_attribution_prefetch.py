"""每晚兜底: 增量预跑差距归因 + 自动提炼方法初稿(闭环)。

平时归因/方法初稿由收口入库自动增量预跑(见 server._score_assignment_into_board 钩子)。
这个脚本是**定时兜底**: 每晚全量扫一遍所有有分数的题, 对指纹变化(评测结果变了/从没
预跑过)的题补跑归因落缓存, 并顺带把有实质归因的题提炼成方法初稿(draft, 去重)。
已缓存且指纹未变的题跳过, 不重算不烧钱。

连线上 Postgres(board/pg_uri.txt)。需 backend.env 的 CLAUDE_API_KEY + 代理才能真跑
归因; cron 调用时已 source。无 key -> 归因走 dry_run(如实标, 不伪造)。
"""
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pipeline import store as STORE
from pipeline import attribution_prefetch as APF


def main() -> int:
    uri = (REPO / "board" / "pg_uri.txt").read_text().strip()
    con = STORE.connect(url=uri)
    stats = APF.prefetch(con, baseline="vio", also_synthesize=True)
    print("[nightly-prefetch]", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
