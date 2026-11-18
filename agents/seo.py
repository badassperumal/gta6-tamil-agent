"""SEO AGENT — title, description (with chapters), tags and hashtags tuned for Tamil + Tanglish search."""
import json

from .core import config, get_logger
from .core.llm import chat_json

log = get_logger("seo")


def _chapters(scenes):
    """YouTube chapters need ≥3 entries, first at 0:00, each ≥10s apart."""
    out, last = [], -999
    for i, sc in enumerate(scenes):
        if sc["start"] - last >= 30 or i == 0:
            m, s = divmod(int(sc["start"] if i else 0), 60)
            label = (sc.get("onscreen") or " ".join(sc["narration"].split()[:6]))[:40].strip()
            out.append(f"{m}:{s:02d} {label}")
            last = sc["start"]
    return out if len(out) >= 3 else []


def run(plan: dict, script: dict) -> dict:
    cfg = config()
    fmt = plan["format"]
    system = f"""You are a YouTube SEO expert for Tamil gaming channels. Channel: {cfg['channel']['name']} ({cfg['channel']['handle']}).
Tamil viewers search in Tanglish and English ("gta 6 tamil", "gta 6 money tips tamil", "gta 6 secrets in tamil").
Write metadata from the FINAL SCRIPT only. The title and description may only promise what the script actually
says — no invented numbers, hours played, or secrets the script doesn't reveal. Curiosity is fine; lying is not.
Use Tamil as spoken in Tamil Nadu (not Sri Lankan vocabulary such as "மணித்தியாலம்")."""
    user = json.dumps({
        "format": fmt, "pillar": plan["pillar"],
        "final_script": " ".join(s["narration"] for s in script["scenes"])[:2500],
        "thumbnail_text": script.get("thumbnail_text"),
        "rules": {
            "title": "max 70 chars, must contain 'GTA 6' and 'Tamil' or Tamil words, curiosity + clarity" + (", end with #Shorts" if fmt == "short" else ""),
            "description": "first 2 lines = hook with main keywords; then 3-5 line Tamil summary; no links section (added automatically)",
            "tags": "15-25 tags, mix Tamil, Tanglish, English, total under 450 characters",
            "hashtags": "exactly 3, e.g. #GTA6 #GTA6Tamil #TamilGaming",
        },
        "output_schema": {"title": "", "description": "", "tags": [""], "hashtags": ["#GTA6"]},
    }, ensure_ascii=False)
    meta = chat_json(system, user, temperature=0.7)

    title = meta.get("title", plan.get("working_title", "GTA 6 Tamil"))[:100]
    if fmt == "short" and "#shorts" not in title.lower():
        title = (title[:90] + " #Shorts")
    tags, total = [], 0
    for t in meta.get("tags", []) + ["GTA 6", "GTA 6 Tamil", "GTA VI", "Tamil Gaming"]:
        t = t.strip().replace("<", "").replace(">", "")
        if t and t.lower() not in [x.lower() for x in tags] and total + len(t) + 3 < 480:
            tags.append(t)
            total += len(t) + 3

    desc = [meta.get("description", "").strip(), ""]
    if fmt == "long":
        ch = _chapters(script["scenes"])
        if ch:
            desc += ["⏱️ Chapters", *ch, ""]
    desc += [
        f"🔔 Subscribe {cfg['channel']['handle']} — daily GTA 6 updates in Tamil!",
        f"💬 {script.get('end_question', '')}",
        "",
        "Grand Theft Auto VI © Rockstar Games / Take-Two Interactive. This channel is a fan channel and is not affiliated with Rockstar Games.",
        "Narration uses AI-generated Tamil voice.",
        "",
        " ".join(meta.get("hashtags", ["#GTA6", "#GTA6Tamil", "#TamilGaming"])[:3]),
    ]
    out = {"title": title, "description": "\n".join(desc)[:4900], "tags": tags}
    log.info("seo title: %s", title)
    return out
