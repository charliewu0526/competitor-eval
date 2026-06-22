"""Dual-AI review client. Calls Gemini + Codex(OpenAI) via HTTP.

Keys come from env (injected by violoop secrets): GEMINI_API_KEY, OPENAI_API_KEY.
If a key is missing, that panelist returns a DRY-RUN stub so the pipeline still
flows end-to-end without credentials. All traffic honors HTTPS_PROXY if set.
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


def review_gemini(prompt: str) -> dict:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return {"panelist": "gemini", "dry_run": True,
                "S1": 3, "S2": 3, "S3": 3, "S4": 3, "justifications": {}}
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"gemini-2.5-pro:generateContent?key={key}")
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    out = _post(url, {"Content-Type": "application/json"}, body)
    txt = out["candidates"][0]["content"]["parts"][0]["text"]
    return {"panelist": "gemini", "dry_run": False, **_parse_scores(txt)}


def review_codex(prompt: str) -> dict:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return {"panelist": "codex", "dry_run": True,
                "S1": 3, "S2": 3, "S3": 3, "S4": 3, "justifications": {}}
    url = "https://api.openai.com/v1/chat/completions"
    body = {"model": "gpt-5-codex", "messages": [{"role": "user", "content": prompt}]}
    hdr = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    out = _post(url, hdr, body)
    txt = out["choices"][0]["message"]["content"]
    return {"panelist": "codex", "dry_run": False, **_parse_scores(txt)}
