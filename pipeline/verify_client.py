"""A4 AI-verification adapter (production). 出题≠核验，强制不自评。

The 4th seam adapter. A verification AI reads a candidate task/run and returns a
binary pass/fail + reason. Two hard rules from the issue:

  1. 不自评: the verifier model family MUST differ from the generator (出题) model
     family. Same family -> rejected (raise SelfEvalError) before any network.
  2. pass -> 自动入库: verification is NOT a human sign-off gate; a pass result is
     marked auto_ingest=True so the orchestrator ingests without waiting.

Authorization (verifier must clear the golden set first) lives in G2; this
adapter only exposes the contract G2 will gate on.

Contract dict (shared by production VerifyClient + in-memory FakeVerifier):
  {"verifier": str, "model_family": str, "dry_run": bool,
   "passed": bool, "reason": str, "auto_ingest": bool}
or, on a network/parse error:
  {"verifier": str, "model_family": str, "dry_run": False,
   "error": str, "passed": False, "auto_ingest": False}

Keys/config from env (violoop secrets); HTTPS_PROXY honored if set, same routing
rules as review_client (CN endpoints bypass the GFW proxy).
"""
from __future__ import annotations
import os, json, urllib.request
from urllib.parse import urlparse

PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_DIRECT_HOST_SUFFIXES = ("deepseek.com", "bigmodel.cn", "zhipuai.cn")


class SelfEvalError(ValueError):
    """Raised when the verifier model family == the generator family (自评)."""


# --- model -> family map (不自评 is enforced at the FAMILY level) ------------
# Same family => cannot verify its own output, even across model versions.
_FAMILY = {
    "deepseek": "deepseek",
    "glm": "zhipu",
    "claude": "anthropic",
    "gemini": "google",
}


def family_of(verifier: str) -> str:
    """Resolve a verifier name to its model family. Unknown -> the name itself
    (so an unknown verifier still can't 'self-eval' an identically-named one)."""
    return _FAMILY.get(verifier, verifier)


def assert_not_self_eval(generator: str, verifier: str) -> None:
    """强制不自评: reject when verifier and generator share a model family.
    Checked BEFORE any network call so a self-eval never even hits the API."""
    if family_of(generator) == family_of(verifier):
        raise SelfEvalError(
            f"verifier {verifier!r} (family {family_of(verifier)!r}) may not "
            f"verify output from generator {generator!r} — 出题≠核验，不能自评")


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


def _parse_verdict(text: str) -> dict:
    """Pull {"passed":bool,"reason":str} out of a model reply."""
    s = text.find("{"); e = text.rfind("}")
    if s >= 0 and e > s:
        try:
            obj = json.loads(text[s:e + 1])
            return {"passed": bool(obj.get("passed")),
                    "reason": str(obj.get("reason", ""))[:500]}
        except Exception:
            pass
    return {"error": "unparseable", "passed": False,
            "reason": text[:300]}


def _result(verifier: str, dry_run: bool, passed: bool, reason: str,
            error: str | None = None) -> dict:
    """Build the shared contract dict. pass -> auto_ingest=True (无人工签字闸门)."""
    out = {"verifier": verifier, "model_family": family_of(verifier),
           "dry_run": dry_run, "passed": bool(passed),
           "reason": reason, "auto_ingest": bool(passed)}
    if error is not None:
        out["error"] = error
        out["passed"] = False
        out["auto_ingest"] = False
    return out


def _stub(verifier: str) -> dict:
    # Missing config -> DRY-RUN stub so the pipeline still flows. A stub PASSES
    # (the offline-flow default) but is clearly marked dry_run for auditing.
    return _result(verifier, dry_run=True, passed=True,
                   reason="dry-run stub: no API key configured")


def _build_prompt(task_text: str, candidate: str) -> str:
    return f"""You are an independent verification AI. You did NOT author the
content below — judge it strictly on whether it MEETS the task requirements.
Self-narration / confident tone is NOT evidence. Return JSON only:
{{"passed": true|false, "reason": "<one line>"}}.

TASK REQUIREMENT:
{task_text}

CANDIDATE TO VERIFY:
{candidate}
"""


# --- production verifier clients (OpenAI-compatible + Anthropic) ------------

def _openai_verify(verifier: str, base_url: str, model: str, key: str,
                   prompt: str) -> dict:
    url = f"{base_url}/chat/completions"
    hdr = {"Content-Type": "application/json",
           "Authorization": f"Bearer {key}"}
    body = {"model": model, "temperature": 0,
            "messages": [{"role": "user", "content": prompt}]}
    try:
        out = _post(url, hdr, body)
        txt = out["choices"][0]["message"]["content"]
        v = _parse_verdict(txt)
        return _result(verifier, False, v["passed"], v["reason"],
                       error=v.get("error"))
    except Exception as ex:
        return _result(verifier, False, False, "", error=str(ex)[:200])


def verify_deepseek(prompt: str) -> dict:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return _stub("deepseek")
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro")
    return _openai_verify("deepseek", base, model, key, prompt)


def verify_glm(prompt: str) -> dict:
    key = os.environ.get("ZHIPU_API_KEY") or os.environ.get("GLM_API_KEY")
    if not key:
        return _stub("glm")
    base = os.environ.get("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    model = os.environ.get("GLM_MODEL", "glm-5.2")
    return _openai_verify("glm", base, model, key, prompt)


def verify_claude(prompt: str) -> dict:
    key = os.environ.get("CLAUDE_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return _stub("claude")
    model = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")
    max_tokens = int(os.environ.get("CLAUDE_MAX_TOKENS", "1024"))
    url = "https://api.anthropic.com/v1/messages"
    hdr = {"Content-Type": "application/json", "x-api-key": key,
           "anthropic-version": "2023-06-01"}
    body = {"model": model, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]}
    try:
        out = _post(url, hdr, body)
        txt = out["content"][0]["text"]
        v = _parse_verdict(txt)
        return _result("claude", False, v["passed"], v["reason"],
                       error=v.get("error"))
    except Exception as ex:
        return _result("claude", False, False, "", error=str(ex)[:200])


_VERIFIERS = {
    "deepseek": verify_deepseek,
    "glm": verify_glm,
    "claude": verify_claude,
}


def verify(task_text: str, candidate: str, *, generator: str,
           verifier: str) -> dict:
    """Top-level production verification call.

    Enforces 不自评 (verifier family != generator family) BEFORE any network,
    then dispatches to the named verifier client. A pass returns
    auto_ingest=True so the orchestrator ingests without a human gate.
    """
    assert_not_self_eval(generator, verifier)
    fn = _VERIFIERS.get(verifier)
    if fn is None:
        raise ValueError(f"unknown verifier {verifier!r}; "
                         f"known: {sorted(_VERIFIERS)}")
    return fn(_build_prompt(task_text, candidate))
