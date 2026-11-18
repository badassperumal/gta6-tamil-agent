"""Free-LLM router. Walks the provider chain in config.yaml and falls through on
missing keys, rate limits or errors, so one provider going down never stops the channel.

All providers speak the OpenAI chat-completions format:
  gemini     → Google AI Studio free tier (no card)          GEMINI_API_KEY
  groq       → open-weight models, free tier                  GROQ_API_KEY
  openrouter → ":free" open models                            OPENROUTER_API_KEY
  ollama     → your own server (OLLAMA_URL), no key
"""
import json
import os
import re
import time

import requests

from . import config, get_logger, mock

log = get_logger("llm")

PROVIDERS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "GEMINI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", "OPENROUTER_API_KEY"),
    "ollama": (os.getenv("OLLAMA_URL", "http://localhost:11434/v1/chat/completions"), None),
}


class LLMError(RuntimeError):
    pass


_DISCOVERED: dict[str, list[str]] = {}
PREFER = {
    # newest/best first; anything matching is used, unknown future names are ranked by version number
    "gemini": ["flash"],
    "groq": ["openai/gpt-oss-120b", "qwen/qwen3.6-27b", "openai/gpt-oss-20b", "moonshotai/kimi"],
}
SKIP_WORDS = ("image", "tts", "audio", "live", "embedding", "vision", "guard", "whisper", "native", "robotics", "computer")


def _version_key(name: str):
    nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)", name.split("/")[-1])[:1]] or [0.0]
    lite = "lite" in name or "8b" in name or "20b" in name
    preview = "preview" in name or "exp" in name
    return (-nums[0], lite, preview, name)


def discover(provider: str, key: str) -> list[str]:
    """Ask the provider which models exist right now, so retired names never break the channel."""
    if provider in _DISCOVERED:
        return _DISCOVERED[provider]
    names: list[str] = []
    try:
        if provider == "gemini":
            r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                             params={"key": key, "pageSize": 200}, timeout=30)
            r.raise_for_status()
            for m in r.json().get("models", []):
                n = m["name"].removeprefix("models/")
                if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in n \
                        and not any(w in n for w in SKIP_WORDS):
                    names.append(n)
            names.sort(key=_version_key)
        elif provider == "groq":
            r = requests.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
            r.raise_for_status()
            live = [m["id"] for m in r.json().get("data", []) if m.get("active", True)]
            names = [m for pref in PREFER["groq"] for m in live if m.startswith(pref)]
        log.info("%s models available: %s", provider, names[:4])
    except Exception as e:  # noqa: BLE001
        log.warning("model discovery for %s failed: %s", provider, e)
    if not names:  # discovery failed → known-good defaults so the provider still works
        names = {"gemini": ["gemini-flash-latest", "gemini-flash-lite-latest"],
                 "groq": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]}.get(provider, [])
    _DISCOVERED[provider] = names
    return names


def _expand_chain(chain: list[dict]) -> list[dict]:
    out, seen = [], set()
    for link in chain:
        url, key_env = PROVIDERS[link["provider"]]
        key = os.getenv(key_env) if key_env else None
        models = [link["model"]]
        if link["model"] == "auto":
            found = discover(link["provider"], key) if key else []
            if link["provider"] == "gemini":
                # newest full Flash + newest Flash-Lite (Lite has much higher free quotas)
                full = [m for m in found if "lite" not in m][:2]
                lite = [m for m in found if "lite" in m][:1]
                models = full + lite
            else:
                models = found[:3]
        for m in models:
            if (link["provider"], m) not in seen:
                seen.add((link["provider"], m))
                out.append({"provider": link["provider"], "model": m})
    return out


_DEAD: set[tuple[str, str]] = set()      # retired / unusable this run
_COOL: dict[tuple[str, str], float] = {}  # busy (429/503) → skip until this timestamp
PASS_WAITS = [0, 20, 60]                  # pause before each full pass over all models


def _try_once(link: dict, system: str, user: str, temperature: float, max_tokens: int) -> str | None:
    """One attempt on one model. Returns text, or None (and records cooldown) on failure."""
    url, key_env = PROVIDERS[link["provider"]]
    key = os.getenv(key_env) if key_env else "ollama"
    ident = (link["provider"], link["model"])
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if link["provider"] == "openrouter":
        headers["HTTP-Referer"] = "https://github.com"
        headers["X-Title"] = "gta6-tamil-agent"
    body = {"model": link["model"], "temperature": temperature, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    try:
        r = requests.post(url, headers=headers, json=body, timeout=(10, 90))
    except requests.RequestException as e:
        log.warning("%s/%s → %s", *ident, type(e).__name__)
        _COOL[ident] = time.time() + 120
        return None
    if r.status_code in (400, 404) and "model" in r.text.lower():
        _DEAD.add(ident)
        return None
    if r.status_code in (401, 403):
        log.warning("%s/%s → %s (check the API key)", *ident, r.status_code)
        _DEAD.add(ident)
        return None
    if r.status_code == 429 or r.status_code >= 500:
        try:
            ra = float(r.headers.get("retry-after", 0))
        except ValueError:
            ra = 0
        _COOL[ident] = time.time() + max(ra, 90)   # don't hammer a busy model on the next call either
        log.warning("%s/%s → %s (busy, switching)", *ident, r.status_code)
        return None
    if not r.ok:
        log.warning("%s/%s → %s %s", *ident, r.status_code, r.text[:150])
        _COOL[ident] = time.time() + 300
        return None
    text = (r.json()["choices"][0]["message"].get("content") or "").strip()
    if text:
        _COOL.pop(ident, None)
        log.info("answered by %s/%s", *ident)
        return text
    return None


def chat(system: str, user: str, temperature: float | None = None, max_tokens: int = 8000) -> str:
    """Fast failover: one quick try per model, cycling providers; only pause when ALL are busy."""
    if mock():
        from tests.mock_llm import mock_reply
        return mock_reply(system, user)

    cfg = config()["llm"]
    temperature = cfg["temperature"] if temperature is None else temperature
    chain = []
    for link in _expand_chain(cfg["chain"]):
        _, key_env = PROVIDERS[link["provider"]]
        if link["provider"] == "ollama" and not os.getenv("OLLAMA_URL"):
            continue
        if key_env and not os.getenv(key_env):
            continue
        chain.append(link)
    if not chain:
        raise LLMError("No LLM configured. Add GEMINI_API_KEY and/or GROQ_API_KEY as repository secrets.")

    for n, wait in enumerate(PASS_WAITS):
        if wait:
            log.info("all models busy — pausing %ss before retry pass %d", wait, n + 1)
            time.sleep(wait)
        live = [l for l in chain if (l["provider"], l["model"]) not in _DEAD]
        # models not cooling down first, then the ones whose cooldown ends soonest
        live.sort(key=lambda l: _COOL.get((l["provider"], l["model"]), 0))
        for link in live:
            ident = (link["provider"], link["model"])
            if n == 0 and _COOL.get(ident, 0) > time.time():
                continue
            text = _try_once(link, system, user, temperature, max_tokens)
            if text:
                return text
    raise LLMError("All LLM providers are busy or failing right now: "
                   + ", ".join(f"{p}/{m}" for p, m in [(l['provider'], l['model']) for l in chain]))


def _extract_json(text: str):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)  # reasoning models
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
    if start == -1:
        raise ValueError("no JSON found")
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    end = text.rfind(closer)
    return json.loads(text[start:end + 1])


def chat_json(system: str, user: str, temperature: float | None = None, tries: int = 3):
    """Ask for JSON and keep asking until it parses."""
    sys_prompt = system + "\n\nReply with ONE valid JSON value only. No markdown, no commentary."
    last_err = None
    for _ in range(tries):
        raw = chat(sys_prompt, user, temperature=temperature)
        try:
            return _extract_json(raw)
        except Exception as e:  # noqa: BLE001
            last_err = e
            user = user + f"\n\n(Your previous answer was not valid JSON: {e}. Return only valid JSON.)"
    raise LLMError(f"LLM never returned valid JSON: {last_err}")
