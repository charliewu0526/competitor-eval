"""A1 review-panel adapter. Production panel = DeepSeek + GLM + Claude.

两中一西 (DeepSeek + GLM 中文, Claude 西): guards against same-family bias and
fits Chinese desktop scenarios. Each panelist scores S1-S5 back-to-back blind and
MUST attach a per-dimension justification; a score with no justification is
dropped downstream (pipeline.aggregate._justified) — that is the contract this
adapter feeds.

Each client returns the SAME contract dict:
  {"panelist": str, "dry_run": bool,
   "S1":int,"S2":int,"S3":int,"S4":int,"S5":int|null,
   "justifications": {"S1":str,...}, "defects": [str]}
or, on a network/parse error:
  {"panelist": str, "dry_run": False, "error": str}

Keys/config from env (violoop secrets); HTTPS_PROXY honored if set:
  DEEPSEEK_API_KEY                         (DeepSeek chat)
  ZHIPU_API_KEY                            (GLM / 智谱 open.bigmodel.cn)
  CLAUDE_API_KEY  OR  AWS_BEARER_TOKEN_BEDROCK + BEDROCK_* (Claude)
  GEMINI_API_KEY                           (legacy panelist, kept for back-compat)
Missing config -> that panelist returns a DRY-RUN stub so the pipeline still flows.
"""
from __future__ import annotations
import os, json, urllib.request
from urllib.parse import urlparse

PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
_DIMS = ("S1", "S2", "S3", "S4", "S5")
# A browser-like UA: DeepSeek's WAF returns 418 to the default Python-urllib UA.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# CN-hosted endpoints must NOT go through the GFW proxy — the proxy routes them
# wrong (DeepSeek -> 418, 智谱 -> alicdn 404). Western endpoints (Anthropic,
# Google) DO need the proxy. Match by host suffix.
_DIRECT_HOST_SUFFIXES = ("deepseek.com", "bigmodel.cn", "zhipuai.cn")


def _needs_proxy(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return not any(host == s or host.endswith("." + s) or host.endswith(s)
                   for s in _DIRECT_HOST_SUFFIXES)


def _post(url: str, headers: dict, payload: dict, timeout: int = 120) -> dict:
    headers = {"User-Agent": _UA, **headers}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    if PROXY and _needs_proxy(url):
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
    # Provide per-dim justifications (else scores get dropped as unjustified)
    # and an empty defects list, plus an S5 placeholder.
    just = {d: "dry-run stub" for d in _DIMS}
    return {"panelist": name, "dry_run": True,
            "S1": 3, "S2": 3, "S3": 3, "S4": 3, "S5": 3,
            "justifications": just, "defects": []}


# --- OpenAI-compatible chat clients (DeepSeek + GLM share this shape) --------

def _openai_chat(name: str, base_url: str, model: str, key: str,
                 prompt: str) -> dict:
    url = f"{base_url}/chat/completions"
    hdr = {"Content-Type": "application/json",
           "Authorization": f"Bearer {key}"}
    body = {"model": model, "temperature": 0,
            "messages": [{"role": "user", "content": prompt}]}
    try:
        out = _post(url, hdr, body)
        txt = out["choices"][0]["message"]["content"]
        return {"panelist": name, "dry_run": False, **_parse_scores(txt)}
    except Exception as ex:
        return {"panelist": name, "dry_run": False, "error": str(ex)[:200]}


def review_deepseek(prompt: str) -> dict:
    # DeepSeek V4 — deepseek-v4-pro is the max-capability tier (smartest).
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return _stub("deepseek")
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    return _openai_chat("deepseek", base, model, key, prompt)


def review_glm(prompt: str) -> dict:
    # 智谱 GLM via OpenAI-compatible endpoint. glm-5.2 = current flagship SOTA.
    key = os.environ.get("ZHIPU_API_KEY") or os.environ.get("GLM_API_KEY")
    if not key:
        return _stub("glm")
    base = os.environ.get("ZHIPU_BASE_URL",
                          "https://open.bigmodel.cn/api/paas/v4")
    model = os.environ.get("GLM_MODEL", "glm-5.2")
    return _openai_chat("glm", base, model, key, prompt)


# --- Claude: direct Anthropic API (preferred) or AWS Bedrock fallback --------

def review_claude(prompt: str) -> dict:
    # claude-opus-4-8 = current flagship Opus (smartest GA Opus tier).
    key = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    max_tokens = int(os.environ.get("CLAUDE_MAX_TOKENS", "4096"))
    if key:
        model = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")
        url = "https://api.anthropic.com/v1/messages"
        hdr = {"Content-Type": "application/json", "x-api-key": key,
               "anthropic-version": "2023-06-01"}
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]}
        try:
            out = _post(url, hdr, body)
            txt = out["content"][0]["text"]
            return {"panelist": "claude", "dry_run": False, **_parse_scores(txt)}
        except Exception as ex:
            return {"panelist": "claude", "dry_run": False, "error": str(ex)[:200]}
    # Bedrock fallback (legacy path) ----------------------------------------
    token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
    if not token:
        return _stub("claude")
    region = os.environ.get("BEDROCK_REGION") or os.environ.get("AWS_REGION") or "ap-southeast-1"
    model = os.environ.get("BEDROCK_CLAUDE_MODEL_ID", "global.anthropic.claude-opus-4-8")
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


# --- legacy Gemini panelist (kept so old PANELISTS config still resolves) ----

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
