"""QUALITY & POLICY REVIEWER — gatekeeper before anything gets rendered.
Rule checks (length, banned phrases) + an LLM editor pass for facts, hook strength and YouTube policy."""
import json

import datetime

from .core import config, get_logger
from .core.llm import chat_json

log = get_logger("reviewer")


def rule_check(plan: dict, script: dict) -> list[str]:
    cfg = config()
    issues = []
    lo, hi = cfg["video"][plan["format"]]["target_words"]
    wc = script.get("word_count", 0)
    if wc < lo * 0.8:
        issues.append(f"Too short: {wc} words, need at least {lo}.")
    if wc > hi * 1.25:
        issues.append(f"Too long: {wc} words, max {hi}.")
    if len(script.get("scenes", [])) < 4:
        issues.append("Too few scenes.")
    text = json.dumps(script, ensure_ascii=False).lower()
    for p in cfg["safety"]["banned_phrases"]:
        if p in text:
            issues.append(f"Banned phrase used: '{p}'.")
    return issues


def run(plan: dict, script: dict) -> tuple[bool, str]:
    issues = rule_check(plan, script)
    system = """You are a strict senior editor and YouTube policy reviewer for a Tamil gaming channel.
Check the script against plan_facts + confirmed_facts_always_true (both are TRUE; use "today" for any timing words
like "tomorrow" or "next week"). Fail it if ANY of these is true:
- states something as fact that is in neither list (invented leaks, dates, features, prices, editions, subscriptions)
- weak first line (would not stop a scroll)
- misleading clickbait the video does not pay off
- piracy / cheating / dangerous / hateful content, or story spoilers without warning
- Tamil reads unnatural or overly formal
Be practical: minor style nits are NOT failures."""
    user = json.dumps({"today": str(datetime.date.today()),
                       "confirmed_facts_always_true": config()["channel"].get("known_facts", []),
                       "plan_facts": plan.get("facts"), "angle": plan.get("angle"), "script": script,
                       "output_schema": {"pass": True, "score_1_to_10": 8, "problems": ["..."], "fix_instructions": "..."}},
                      ensure_ascii=False)
    verdict = chat_json(system, user, temperature=0.2)
    ok = bool(verdict.get("pass")) and not issues and verdict.get("score_1_to_10", 0) >= 6
    feedback = " ".join(issues + verdict.get("problems", []) + [verdict.get("fix_instructions", "")]).strip()
    log.info("review: %s (score %s) %s", "PASS" if ok else "FAIL", verdict.get("score_1_to_10"), feedback[:200])
    return ok, feedback
