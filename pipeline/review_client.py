"""Dual-AI review client. Panel = Gemini + Claude(via AWS Bedrock).

Different model families -> guards against same-family bias.
Keys/config from env (violoop secrets):
  GEMINI_API_KEY
  AWS_BEARER_TOKEN_BEDROCK, BEDROCK_REGION, BEDROCK_CLAUDE_MODEL_ID, CLAUDE_MAX_TOKENS
Missing config -> that panelist returns a DRY-RUN stub so the pipeline still flows.
All traffic honors HTTPS_PROXY if set.
"""
from __future__ import annotations
import os, json, urllib.request

PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")


def _post(url: str, headers: dict, payload: dict, timeout: int = 120) -> dict:
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
    token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
    region = os.environ.get("BEDROCK_REGION") or os.environ.get("AWS_REGION") or "ap-southeast-1"
    model = os.environ.get("BEDROCK_CLAUDE_MODEL_ID", "global.anthropic.claude-opus-4-8")
    max_tokens = int(os.environ.get("CLAUDE_MAX_TOKENS", "4096"))
    if not token:
        return _stub("claude")
    base = os.environ.get("BEDROCK_RUNTIME_BASE_URL") or \
        f"https://bedrock-runtime.{region}.amazonaws.com"
    url = f"{base}/model/{model}/invoke"
    hdr = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    body = {"anthropic_version": "bedrock-2023-05-31", "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]}
    try:
        out = _post(url, hdr, body)
        txt = out["content"][0]["text"]
        return {"panelist": "claude", "dry_run": False, **_parse_scores(txt)}
    except Exception as ex:
        return {"panelist": "claude", "dry_run": False, "error": str(ex)[:200]}
