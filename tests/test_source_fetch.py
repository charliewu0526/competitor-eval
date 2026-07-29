"""D 来源抓取器 source_fetch 离线单测(不打网络,monkeypatch requests.get)。

  (a) 成功页 -> ok=True 有 text。
  (b) 非 200 -> ok=False 标状态码。
  (c) 非 HTTP(S) 链接 -> ok=False 跳过。
  (d) 抓取异常 -> ok=False 如实标。
  (e) 空列表 -> 空;merge 只合并成功来源,全失败 -> ("", [])。
"""
from __future__ import annotations
import unittest

from pipeline import source_fetch as SF


class _Resp:
    def __init__(self, status=200, text="", ctype="text/html"):
        self.status_code = status
        self.text = text
        self.headers = {"Content-Type": ctype}


class TestSourceFetch(unittest.TestCase):
    def setUp(self):
        self._orig = SF.requests.get

    def tearDown(self):
        SF.requests.get = self._orig

    def test_a_success(self):
        SF.requests.get = lambda *a, **k: _Resp(
            text="<html><body><h1>Town</h1><p>专属邮箱入口</p></body></html>")
        r = SF.fetch_one("https://town.com")
        self.assertTrue(r["ok"])
        self.assertIn("专属邮箱入口", r["text"])
        self.assertTrue(r["fetched_at"])

    def test_b_non_200(self):
        SF.requests.get = lambda *a, **k: _Resp(status=404)
        r = SF.fetch_one("https://town.com/x")
        self.assertFalse(r["ok"])
        self.assertIn("404", r["note"])

    def test_c_non_http_skipped(self):
        r = SF.fetch_one("ftp://x")
        self.assertFalse(r["ok"])
        self.assertIn("非 HTTP", r["note"])

    def test_d_exception(self):
        def _boom(*a, **k):
            raise RuntimeError("timeout")
        SF.requests.get = _boom
        r = SF.fetch_one("https://town.com")
        self.assertFalse(r["ok"])
        self.assertIn("timeout", r["note"])

    def test_e_empty_and_merge(self):
        self.assertEqual(SF.fetch_sources([]), [])
        # 全失败 -> merge 返回空
        fetched = [{"url": "u", "ok": False, "text": "", "fetched_at": "t", "note": "x"}]
        text, ok = SF.merge_fetched_text(fetched)
        self.assertEqual((text, ok), ("", []))
        # 有成功 -> merge 带来源头
        fetched2 = [{"url": "https://a", "ok": True, "text": "正文A", "fetched_at": "t"}]
        text2, ok2 = SF.merge_fetched_text(fetched2)
        self.assertIn("来源: https://a", text2)
        self.assertIn("正文A", text2)
        self.assertEqual(len(ok2), 1)

    def test_f_empty_body(self):
        SF.requests.get = lambda *a, **k: _Resp(text="<html><body></body></html>")
        r = SF.fetch_one("https://town.com")
        self.assertFalse(r["ok"])
        self.assertIn("无可读正文", r["note"])


if __name__ == "__main__":
    unittest.main()
