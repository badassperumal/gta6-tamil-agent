"""Shared infrastructure for all sub-agents: config, state, logging, LLM, YouTube client."""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "state"
OUT_DIR = ROOT / "output"
STATE_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    stream=sys.stdout,
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


_CONFIG = None


def config() -> dict:
    global _CONFIG
    if _CONFIG is None:
        with open(ROOT / "config.yaml", encoding="utf-8") as f:
            _CONFIG = yaml.safe_load(f)
    return _CONFIG


def now() -> datetime:
    return datetime.now(timezone.utc)


def today() -> str:
    return now().strftime("%Y-%m-%d")


def dry_run() -> bool:
    return os.getenv("DRY_RUN", "0") == "1"


def mock() -> bool:
    """MOCK=1 → no network: canned LLM answers, silent TTS. Used for local tests."""
    return os.getenv("MOCK", "0") == "1"


class State:
    """Tiny JSON-file store under state/. Committed back to the repo after every run,
    which is also what keeps GitHub's scheduled workflows from going dormant."""

    @staticmethod
    def load(name: str, default):
        p = STATE_DIR / f"{name}.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        return default

    @staticmethod
    def save(name: str, data):
        p = STATE_DIR / f"{name}.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)

    @staticmethod
    def append_log(name: str, record: dict):
        p = STATE_DIR / f"{name}.jsonl"
        record = {"ts": now().isoformat(), **record}
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


class Quota:
    """Tracks YouTube Data API units spent today so agents never blow the daily budget."""

    COSTS = {"list": 1, "insert_comment": 50, "moderate": 50, "thumbnail": 50,
             "playlist_insert": 50, "playlist_create": 50, "search": 100, "update": 50}

    @classmethod
    def _data(cls):
        d = State.load("quota", {})
        if d.get("day") != today():
            d = {"day": today(), "used": 0}
        return d

    @classmethod
    def can_spend(cls, op: str, n: int = 1) -> bool:
        cfg = config()["quota"]
        d = cls._data()
        return d["used"] + cls.COSTS[op] * n <= cfg["daily_units"] - cfg["reserve_units"]

    @classmethod
    def spend(cls, op: str, n: int = 1):
        d = cls._data()
        d["used"] += cls.COSTS[op] * n
        State.save("quota", d)


def retry(fn, tries=3, delay=3, log=None):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if log:
                log.warning("attempt %d/%d failed: %s", i + 1, tries, e)
            time.sleep(delay * (i + 1))
    raise last
