"""ANALYST — reads YouTube Analytics, learns which pillars/formats/hooks work,
re-weights the strategist, and writes a weekly report (posted as a GitHub Issue by the workflow)."""
import json
from datetime import timedelta

from .core import OUT_DIR, State, config, get_logger, now
from .core.llm import chat_json

log = get_logger("analyst")


def run(weekly: bool = False):
    from .core.youtube import yta
    from .trend_scout import youtube_competitors

    end = now().date()
    start = end - timedelta(days=28)
    rep = yta().reports().query(ids="channel==MINE", startDate=str(start), endDate=str(end), dimensions="video",
                                metrics="views,estimatedMinutesWatched,averageViewPercentage,likes,comments,subscribersGained",
                                sort="-views", maxResults=50).execute()
    cols = [c["name"] for c in rep.get("columnHeaders", [])]
    rows = [dict(zip(cols, r)) for r in rep.get("rows", [])]

    hist = State.load("history", {"videos": []})
    meta = {v.get("video_id"): v for v in hist["videos"] if v.get("video_id")}
    perf = []
    for r in rows:
        v = meta.get(r["video"])
        if v:
            perf.append({**r, "title": v["title"], "pillar": v["pillar"], "format": v["format"], "hook": v.get("hook")})

    # pillar weights = smoothed average views per video (min weight 1 so nothing dies completely)
    cfg_p = config()["pillars"]
    weights = {}
    for p in cfg_p:
        vs = [x["views"] for x in perf if x["pillar"] == p]
        weights[p] = round(1 + (sum(vs) / len(vs)) / max(1, max([x["views"] for x in perf] or [1])) * 4, 2) if vs else cfg_p[p]["weight"]

    competitors = []
    try:
        competitors = youtube_competitors(config()["trends"]["youtube_competitor_query"])
    except Exception as e:  # noqa: BLE001
        log.warning("competitor scan failed: %s", e)

    system = "You are a YouTube growth analyst for a Tamil GTA 6 channel. Be concrete and data-driven. Short bullet points."
    user = json.dumps({"our_videos_last_28d": perf[:30], "trending_competitor_titles": competitors[:20],
                       "output_schema": {"notes": "5-8 bullet lessons for the strategist (what to do more/less)",
                                         "title_patterns_that_work": [""], "next_week_topic_ideas": [""],
                                         "report_markdown": "weekly report for the owner, markdown"}}, ensure_ascii=False)
    ai = chat_json(system, user, temperature=0.4) if (perf or competitors) else {
        "notes": "No data yet.", "next_week_topic_ideas": [], "report_markdown": "No published videos with data yet."}

    State.save("insights", {"updated": now().isoformat(), "pillar_weights": weights, "notes": ai.get("notes"),
                            "title_patterns": ai.get("title_patterns_that_work", []), "competitors": competitors[:20]})
    q = State.load("queue", {"ideas": []})
    q["ideas"] = list(dict.fromkeys(q["ideas"] + ai.get("next_week_topic_ideas", [])))[-100:]
    State.save("queue", q)

    total_views = sum(r.get("views", 0) for r in rows)
    subs = sum(r.get("subscribersGained", 0) for r in rows)
    report = f"# Weekly channel report — {end}\n\n**Last 28 days:** {total_views:,} views · +{subs} subscribers · {len(rows)} videos with data\n\n" \
             f"**Pillar weights now:** {weights}\n\n{ai.get('report_markdown', '')}\n"
    (OUT_DIR / "weekly_report.md").write_text(report, encoding="utf-8")
    log.info("analytics: %d videos, %d views, weights %s", len(rows), total_views, weights)
    return report
