"""MARKETING — promotes every new upload for free:
engagement comment on the video, Telegram channel post, Discord webhook post."""
import os

import requests

from .core import Quota, config, dry_run, get_logger

log = get_logger("marketing")


def run(plan: dict, meta: dict, script: dict, video_id: str | None):
    cfg = config()
    m = cfg["marketing"]
    url = f"https://youtu.be/{video_id}" if video_id else "(dry run)"
    caption = f"🔥 புது video! {meta['title']}\n\n{script.get('end_question', '')}\n👉 {url}"

    if dry_run() or not video_id:
        log.info("DRY_RUN — would post:\n%s", caption)
        tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
        run_url = f"{os.getenv('GITHUB_SERVER_URL', '')}/{os.getenv('GITHUB_REPOSITORY', '')}/actions/runs/{os.getenv('GITHUB_RUN_ID', '')}"
        notify = os.getenv("TELEGRAM_OWNER_CHAT_ID") or None
        if tok and notify and os.getenv("GITHUB_RUN_ID"):
            try:  # manual-upload mode: ping the owner that a video is ready
                requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": notify,
                              "text": f"🎬 Ready to upload: {meta['title']}\nDownload video + thumbnail + metadata.txt:\n{run_url}"}, timeout=30)
            except Exception as e:  # noqa: BLE001
                log.warning("owner notify failed: %s", e)
        return

    if m.get("self_comment") and script.get("end_question") and Quota.can_spend("insert_comment"):
        try:
            from .core.youtube import yt
            yt().commentThreads().insert(part="snippet", body={"snippet": {"videoId": video_id, "topLevelComment": {
                "snippet": {"textOriginal": f"💬 {script['end_question']}\nComment பண்ணுங்க 👇 Best answer-க்கு next video-ல shoutout!"}}}}).execute()
            Quota.spend("insert_comment")
        except Exception as e:  # noqa: BLE001
            log.warning("self comment failed: %s", e)

    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if m.get("telegram") and tok and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": chat, "text": caption, "disable_web_page_preview": False}, timeout=30).raise_for_status()
        except Exception as e:  # noqa: BLE001
            log.warning("telegram failed: %s", e)

    hook = os.getenv("DISCORD_WEBHOOK_URL")
    if m.get("discord") and hook:
        try:
            requests.post(hook, json={"content": caption}, timeout=30).raise_for_status()
        except Exception as e:  # noqa: BLE001
            log.warning("discord failed: %s", e)
    log.info("promoted %s", url)
