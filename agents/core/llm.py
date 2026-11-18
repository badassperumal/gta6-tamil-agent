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


def chat(system: str, user: str, temperature: float | None = None, max_tokens: int = 8000) -> str:
    if mock():
        from tests.mock_llm import mock_reply
        return mock_reply(system, user)

    cfg = config()["llm"]
    temperature = cfg["temperature"] if temperature is None else temperature
    errors = []
    for link in cfg["chain"]:
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
        for attempt in range(cfg.get("max_retries_per_model", 2)):
            try:
                r = requests.post(url, headers=headers, json=body, timeout=180)
                if r.status_code == 429 or r.status_code >= 500:
                    wait = min(60, 10 * (attempt + 1))
                    log.warning("%s/%s → %s, waiting %ss", link["provider"], link["model"], r.status_code, wait)
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
