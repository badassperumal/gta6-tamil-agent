"""STRATEGIST (concept agent) — decides WHAT to make next.
Blends: fresh trends, viewer requests from comments, pillar weights learned by the analyst,
and the channel's history (so it never repeats itself)."""
import json
import random

from .core import State, config, get_logger, now
from .core.llm import chat_json

log = get_logger("strategist")


def _pillar_weights():
    cfg = config()["pillars"]
    learned = State.load("insights", {}).get("pillar_weights", {})
    return {p: learned.get(p, v["weight"]) for p, v in cfg.items()}


def run(fmt: str, breaking: bool = False) -> dict:
    cfg = config()
    trends = State.load("trends", {"stories": [], "breaking": []})
    history = State.load("history", {"videos": [], "topic_keys": []})
    insights = State.load("insights", {})
    requests_q = State.load("queue", {"ideas": []})["ideas"][:15]

    stories = trends["breaking"] if breaking and trends["breaking"] else [s for s in trends["stories"] if not s["covered"]]
    story_brief = [{"key": s["key"], "headline": s["title"], "score": round(s["score"], 1),
                    "facts": [i["summary"][:250] for i in s["items"][:3]], "links": [i["link"] for i in s["items"][:3]]}
                   for s in stories[:12]]
    weights = _pillar_weights()
    suggested_pillar = "news" if breaking else random.choices(list(weights), weights=list(weights.values()))[0]
    days_to_launch = (__import__("datetime").date.fromisoformat(cfg["channel"]["game_release_date"]) - now().date()).days

    system = f"""You are the content strategist for a Tamil YouTube channel: {cfg['channel']['niche']}.
Your job: pick the single best next video that maximises views, CTR and watch time for TAMIL-speaking gamers
(Tamil Nadu, Sri Lanka, Singapore, Malaysia, Gulf). Think like a top Tamil gaming creator.
Rules:
- Only use facts present in the provided stories or in confirmed_facts_always_true. Never invent leaks, release dates, prices or features.
- A detail mentioned by only one news headline (price, edition, Game Pass, etc.) is unconfirmed: leave it out of "facts" unless several sources agree.
- If it's speculation/theory, the angle must say so.
- Respect game_status. Before launch nobody has played it: never claim hours played, discoveries,
  "I found", walkthroughs or gameplay secrets. Pre-launch angles = news, confirmed features, trailer analysis
  (clearly labelled), what to expect, preparation tips (storage, pre-load, platform), community theories (labelled).
- The working_title may only promise what the facts can deliver. No invented numbers ("70 hours", "5 secrets")
  unless the facts contain them.
- Language: Tamil as spoken in Tamil Nadu (Chennai/Madurai), not Sri Lankan Tamil vocabulary
  (e.g. "மணி நேரம்" not "மணித்தியாலம்").
- Prefer topics with search demand ("GTA 6 tamil", "GTA 6 money tips tamil", "GTA 6 secrets").
- Do not repeat a recent title or angle.
- Never promote piracy, cracks, mod menus, cheats that break ToS, or "free download".
Content pillars: {json.dumps({k: v['desc'] for k, v in cfg['pillars'].items()})}"""

    user = json.dumps({
        "format": fmt, "breaking_news_mode": breaking, "suggested_pillar": suggested_pillar,
        "today": str(now().date()),
        "days_until_gta6_launch": days_to_launch,
        "confirmed_facts_always_true": cfg["channel"].get("known_facts", []),
        "game_status": "released — gameplay footage available" if days_to_launch <= 0 else "pre-release",
        "trending_stories": story_brief,
        "viewer_requests_from_comments": requests_q,
        "recent_titles_do_not_repeat": [v["title"] for v in history["videos"][-30:]],
        "what_works_on_this_channel": insights.get("notes", "no data yet — channel is new"),
        "output_schema": {
            "pillar": "one of the pillar keys", "topic": "short english topic", "story_key": "key of the chosen story or null",
            "angle": "the specific hook/angle in english", "working_title": "Tamil+English title idea",
            "hook_line": "first 3 seconds line idea", "footage_tags": ["3-6 english keywords describing visuals"],
            "facts": ["the verified facts the script may use"], "sources": ["links"], "why": "1 line reasoning",
        },
    }, ensure_ascii=False)

    plan = chat_json(system, user, temperature=0.9)
    plan["format"] = fmt
    plan["breaking"] = breaking
    if plan.get("pillar") not in cfg["pillars"]:
        plan["pillar"] = suggested_pillar
    # consume a viewer request if the plan used one
    used = [r for r in requests_q if r.lower()[:25] in json.dumps(plan, ensure_ascii=False).lower()]
    if used:
        q = State.load("queue", {"ideas": []})
        q["ideas"] = [r for r in q["ideas"] if r not in used]
        State.save("queue", q)
    log.info("plan: [%s/%s] %s", fmt, plan["pillar"], plan.get("working_title"))
    return plan
