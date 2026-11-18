"""ORCHESTRATOR — the 'channel manager' agent that directs every sub-agent.

  python orchestrator.py produce --format long|short [--breaking]
  python orchestrator.py scout        # refresh trends; signals breaking news to the workflow
  python orchestrator.py engage       # comments
  python orchestrator.py analyze [--weekly]
  python orchestrator.py ingest --urls "https://youtu.be/... https://youtu.be/..." [--no-upload]
"""
import argparse
import os
import shutil
import sys
import traceback

from agents import (analyst, community, editor, footage, ingest, marketing, publisher, reviewer, scriptwriter,
                    seo, strategist, thumbnail, trend_scout, voice)
from agents.core import OUT_DIR, State, config, get_logger, now, today
from agents.trend_scout import _key

log = get_logger("orchestrator")


def produce(fmt: str, breaking: bool = False):
    run_id = now().strftime("%Y%m%d-%H%M%S") + f"-{fmt}"
    work = OUT_DIR / run_id
    work.mkdir(parents=True, exist_ok=True)
    State.append_log("runs", {"run": run_id, "event": "start", "format": fmt, "breaking": breaking})

    trends = State.load("trends", {})
    if not trends or (now() - __import__("datetime").datetime.fromisoformat(trends["updated"])).total_seconds() > 3 * 3600:
        trend_scout.run()

    # 1) concept → 2) script → 3) review loop (max 3 drafts)
    plan = strategist.run(fmt, breaking)
    feedback, script = None, None
    for attempt in range(3):
        script = scriptwriter.run(plan, feedback)
        ok, feedback = reviewer.run(plan, script)
        if ok:
            break
        log.info("draft %d rejected → rewriting", attempt + 1)
    else:
        State.append_log("runs", {"run": run_id, "event": "rejected", "feedback": feedback})
        raise SystemExit(f"Script failed review 3 times, not publishing. Last feedback: {feedback}")

    # 4) voice → 5) visuals → 6) edit → 7) thumbnail → 8) SEO
    v = voice.run(script, work)
    portrait = fmt == "short"
    picks = footage.pick(script["scenes"], work, portrait)
    video = editor.run(plan, script, v, picks, work)
    thumb = thumbnail.run(work / "visual.mp4", script.get("thumbnail_text") or "GTA 6", work, portrait)
    meta = seo.run(plan, script)
    State.save(f"last_{fmt}", {"plan": plan, "script": script, "meta": meta})

    # 9) publish → 10) market
    vid = publisher.run(plan, meta, video, thumb)
    marketing.run(plan, meta, script, vid)

    hist = State.load("history", {"videos": [], "topic_keys": [], "breaking_days": {}})
    hist["videos"].append({"run": run_id, "video_id": vid, "title": meta["title"], "format": fmt, "pillar": plan["pillar"],
                           "topic": plan.get("topic"), "hook": script["scenes"][0]["narration"][:120],
                           "duration": round(v["duration"], 1), "published_at": now().isoformat(), "breaking": breaking})
    hist["videos"] = hist["videos"][-500:]
    if plan.get("story_key"):
        hist["topic_keys"].append(plan["story_key"])
    hist["topic_keys"].append(_key(plan.get("topic") or meta["title"]))
    hist["topic_keys"] = hist["topic_keys"][-1000:]
    if breaking:
        hist.setdefault("breaking_days", {})[today()] = hist.get("breaking_days", {}).get(today(), 0) + 1
    State.save("history", hist)
    State.append_log("runs", {"run": run_id, "event": "done", "video_id": vid, "title": meta["title"]})

    # keep only the final files (workflow uploads them as an artifact), drop the heavy temp work
    keep = OUT_DIR / "latest"
    shutil.rmtree(keep, ignore_errors=True)
    keep.mkdir()
    for f in (video, thumb, work / "subs.ass"):
        shutil.copy(f, keep / f.name)
    (keep / "metadata.txt").write_text(
        f"TITLE:\n{meta['title']}\n\nDESCRIPTION:\n{meta['description']}\n\nTAGS:\n{', '.join(meta['tags'])}\n\n"
        f"PLAYLIST: {config()['publish']['playlists']['shorts' if fmt == 'short' else plan['pillar']]}\n"
        f"Altered/synthetic content: {'Yes' if config()['publish']['disclose_synthetic'] else 'No'} · Made for kids: No · Language: Tamil\n",
        encoding="utf-8")
    if os.getenv("CI"):
        shutil.rmtree(work, ignore_errors=True)
    log.info("✅ done: %s → %s", meta["title"], f"https://youtu.be/{vid}" if vid else "(dry run)")


def scout():
    out = trend_scout.run()
    cfg = config()["schedule"]
    hist = State.load("history", {"videos": [], "breaking_days": {}})
    fired_today = hist.get("breaking_days", {}).get(today(), 0)
    fire = bool(out["breaking"]) and cfg["breaking_news_shorts"] and fired_today < cfg["max_breaking_per_day"]
    gh_out = os.getenv("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"breaking={'true' if fire else 'false'}\n")
    log.info("breaking news: %s", [b["title"] for b in out["breaking"]] if fire else "none")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["produce", "scout", "engage", "analyze", "ingest"])
    ap.add_argument("--format", default="short", choices=["long", "short"])
    ap.add_argument("--breaking", action="store_true")
    ap.add_argument("--weekly", action="store_true")
    ap.add_argument("--urls", default=os.getenv("INGEST_TEXT", ""), help="YouTube links of your own gameplay")
    ap.add_argument("--no-upload", action="store_true", help="keep clips in assets/footage instead of the GitHub Release")
    a = ap.parse_args()
    try:
        if a.task == "produce":
            produce(a.format, a.breaking)
        elif a.task == "scout":
            scout()
        elif a.task == "engage":
            community.run()
        elif a.task == "analyze":
            analyst.run(a.weekly)
        elif a.task == "ingest":
            msg = ingest.run(a.urls, upload=not a.no_upload)
            (OUT_DIR / "ingest_report.md").write_text(msg, encoding="utf-8")
            print(msg)
    except SystemExit:
        raise
    except Exception:
        State.append_log("runs", {"task": a.task, "event": "error", "error": traceback.format_exc()[-2000:]})
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
