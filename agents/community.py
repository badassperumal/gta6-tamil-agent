"""COMMUNITY MANAGER — replies to comments in Tamil, holds spam for review,
and harvests viewer video requests into the idea queue (feeds the strategist)."""
import json

from .core import Quota, State, config, dry_run, get_logger, today
from .core.llm import chat_json

log = get_logger("community")


def run():
    cfg = config()["community"]
    from .core.youtube import my_channel_id, yt

    st = State.load("comments", {"replied": [], "day": today(), "today_count": 0})
    if st.get("day") != today():
        st.update(day=today(), today_count=0)
    budget = min(cfg["max_replies_per_run"], cfg["max_replies_per_day"] - st["today_count"])
    if budget <= 0:
        log.info("daily reply budget used")
        return

    cid = my_channel_id()
    r = yt().commentThreads().list(part="snippet,replies", allThreadsRelatedToChannelId=cid, order="time",
                                   maxResults=100, textFormat="plainText").execute()
    Quota.spend("list")
    replied = set(st["replied"])
    fresh = []
    for th in r.get("items", []):
        top = th["snippet"]["topLevelComment"]
        if th["id"] in replied or top["snippet"].get("authorChannelId", {}).get("value") == cid:
            continue
        we_replied = any(c["snippet"].get("authorChannelId", {}).get("value") == cid
                         for c in th.get("replies", {}).get("comments", []))
        if we_replied:
            replied.add(th["id"])
            continue
        fresh.append({"id": th["id"], "comment_id": top["id"], "video": th["snippet"].get("videoId"),
                      "author": top["snippet"]["authorDisplayName"], "text": top["snippet"]["textDisplay"][:500]})
    if not fresh:
        log.info("no new comments")
        State.save("comments", {**st, "replied": list(replied)[-3000:]})
        return

    system = f"""You manage comments for the Tamil YouTube channel {config()['channel']['name']} (GTA 6 in Tamil).
For each comment decide: category = spam | toxic | question | request | praise | other.
Write a SHORT warm reply in natural spoken Tamil (Tanglish ok), max 25 words, 0-1 emoji. Answer questions only with
general/safe info; never promise dates or features; never share download/cheat links. For toxic: reply null.
If the viewer asks for a video topic, put it in "video_request" (english, short)."""
    user = json.dumps({"comments": fresh[:40], "output_schema": [
        {"id": "", "category": "", "reply": "Tamil reply or null", "video_request": "topic or null"}]}, ensure_ascii=False)
    decisions = chat_json(system, user, temperature=0.7)
    by_id = {c["id"]: c for c in fresh}

    q = State.load("queue", {"ideas": []})
    sent = 0
    for d in decisions if isinstance(decisions, list) else []:
        c = by_id.get(d.get("id"))
        if not c:
            continue
        cat = d.get("category")
        if cfg["harvest_requests"] and d.get("video_request"):
            q["ideas"].append(d["video_request"])
        if cat == "spam" and cfg["hold_spam"] and Quota.can_spend("moderate") and not dry_run():
            yt().comments().setModerationStatus(id=c["comment_id"], moderationStatus="heldForReview").execute()
            Quota.spend("moderate")
        elif d.get("reply") and cat not in ("spam", "toxic") and sent < budget and Quota.can_spend("insert_comment"):
            if not dry_run():
                yt().comments().insert(part="snippet", body={"snippet": {"parentId": c["comment_id"],
                                                                          "textOriginal": d["reply"][:500]}}).execute()
                Quota.spend("insert_comment")
            sent += 1
        replied.add(c["id"])
    q["ideas"] = list(dict.fromkeys(q["ideas"]))[-100:]
    State.save("queue", q)
    st.update(replied=list(replied)[-3000:], today_count=st["today_count"] + sent)
    State.save("comments", st)
    log.info("handled %d comments, sent %d replies, queue now %d ideas", len(decisions), sent, len(q["ideas"]))
