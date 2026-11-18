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
    _DISCOVERED[provider] = names
    return names


def _expand_chain(chain: list[dict]) -> list[dict]:
    out, seen = [], set()
    for link in chain:
        url, key_env = PROVIDERS[link["provider"]]
        key = os.getenv(key_env) if key_env else None
        models = [link["model"]]
        if link["model"] == "auto":
            models = discover(link["provider"], key)[:3] if key else []
        for m in models:
            if (link["provider"], m) not in seen:
                seen.add((link["provider"], m))
                out.append({"provider": link["provider"], "model": m})
    return out


def chat(system: str, user: str, temperature: float | None = None, max_tokens: int = 8000) -> str:
    if mock():
        from tests.mock_llm import mock_reply
        return mock_reply(system, user)

    cfg = config()["llm"]
    temperature = cfg["temperature"] if temperature is None else temperature
    errors = []
    for link in _expand_chain(cfg["chain"]):
        url, key_env = PROVIDERS[link["provider"]]
        if link["provider"] == "ollama" and not os.getenv("OLLAMA_URL"):
            continue
        key = os.getenv(key_env) if key_env else "ollama"
        if not key:
            continue
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if link["provider"] == "openrouter":
            headers["HTTP-Referer"] = "https://github.com"
            headers["X-Title"] = "gta6-tamil-agent"
        body = {
            "model": link["model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        for attempt in range(cfg.get("max_retries_per_model", 4)):
            try:
                r = requests.post(url, headers=headers, json=body, timeout=180)
                if r.status_code in (404, 400) and "model" in r.text.lower():
                    errors.append(f"{link['provider']}/{link['model']}: model not available")
                    break                                   # retired model → next one
                if r.status_code == 429 or r.status_code >= 500:
                    try:
                        wait = float(r.headers.get("retry-after", 0))
                    except ValueError:
                        wait = 0
                    wait = min(90, max(wait, 15 * (attempt + 1)))
                    log.warning("%s/%s → %s, waiting %ss", link["provider"], link["model"], r.status_code, int(wait))
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"] or ""
                if text.strip():
                    log.info("answered by %s/%s", link["provider"], link["model"])
                    return text
            except Exception as e:  # noqa: BLE001
                errors.append(f"{link['provider']}/{link['model']}: {e}")
                break
        else:
            errors.append(f"{link['provider']}/{link['model']}: still rate-limited")
    raise LLMError("All LLM providers failed. Add at least GEMINI_API_KEY or GROQ_API_KEY. " + " | ".join(errors[-4:]))


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
