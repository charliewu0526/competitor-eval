"""Dual-AI review client. Panel = Gemini + Claude (different families -> anti same-family bias).

Keys from env (violoop secrets): GEMINI_API_KEY, CLAUDE_API_KEY.
Missing key -> that panelist returns a DRY-RUN stub so the pipeline still flows.
All traffic honors HTTPS_PROXY if set.
"""
from __future__ import annotations
import os, json, urllib.request

PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")


def _post(url: str, headers: dict, payload: dict, timeout: int = 90) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    if PROXY:
        req.set_proxy(PROXY.replace("http://", ""), "https")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _parse_scores(text: str) -> dict:
    s = text.find("{"); e = text.rfind("}")
    if s >= 0 and e > s:
        try:
            return json.loads(text[s:e + 1])
        except Exception:
            pass
    return {"error": "unparseable", "raw": text[:300]}


def _stub(name: str) -> dict:
    return {"panelist": name, "dry_run": True,
            "S1": 3, "S2": 3, "S3": 3, "S4": 3, "justifications": {}}


def review_gemini(prompt: str) -> dict:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return _stub("gemini")
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"gemini-2.5-pro:generateContent?key={key}")
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        out = _post(url, {"Content-Type": "application/json"}, body)
        txt = out["candidates"][0]["content"]["parts"][0]["text"]
        return {"panelist": "gemini", "dry_run": False, **_parse_scores(txt)}
    except Exception as ex:
        return {"panelist": "gemini", "dry_run": False, "error": str(ex)[:200]}


def review_claude(prompt: str) -> dict:
    key = os.environ.get("CLAUDE_API_KEY")
    if not key:
        return _stub("claude")
    url = "https://api.anthropic.com/v1/messages"
    hdr = {"Content-Type": "application/json", "x-api-key": key,
           "anthropic-version": "2023-06-01"}
    body = {"model": "claude-sonnet-4-5", "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}]}
    try:
        out = _post(url, hdr, body)
        txt = out["content"][0]["text"]
        return {"panelist": "claude", "dry_run": False, **_parse_scores(txt)}
    except Exception as ex:
        return {"panelist": "claude", "dry_run": False, "error": str(ex)[:200]}
