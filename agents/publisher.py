"""PUBLISHER — uploads to YouTube (resumable), sets thumbnail, files the video into the right playlist."""
from pathlib import Path

from .core import Quota, State, config, dry_run, get_logger, retry

log = get_logger("publisher")


def _playlist_id(name: str) -> str | None:
    from .core.youtube import yt
    cache = State.load("playlists", {})
    if name in cache:
        return cache[name]
    page = None
    while True:
        r = yt().playlists().list(part="snippet", mine=True, maxResults=50, pageToken=page).execute()
        Quota.spend("list")
        for p in r.get("items", []):
            cache[p["snippet"]["title"]] = p["id"]
        page = r.get("nextPageToken")
        if not page:
            break
    if name not in cache and Quota.can_spend("playlist_create"):
        p = yt().playlists().insert(part="snippet,status", body={
            "snippet": {"title": name, "description": f"{name} — {config()['channel']['name']}", "defaultLanguage": "ta"},
            "status": {"privacyStatus": "public"}}).execute()
        Quota.spend("playlist_create")
        cache[name] = p["id"]
    State.save("playlists", cache)
    return cache.get(name)


def run(plan: dict, meta: dict, video: Path, thumb: Path) -> str | None:
    cfg = config()["publish"]
    if dry_run():
        log.info("DRY_RUN — skipping upload of %s", video.name)
        return None
    from googleapiclient.http import MediaFileUpload
    from .core.youtube import yt

    body = {
        "snippet": {"title": meta["title"], "description": meta["description"], "tags": meta["tags"],
                    "categoryId": cfg["category_id"], "defaultLanguage": "ta", "defaultAudioLanguage": "ta"},
        "status": {"privacyStatus": cfg["privacy"], "selfDeclaredMadeForKids": cfg["made_for_kids"],
                   "containsSyntheticMedia": cfg["disclose_synthetic"], "embeddable": True},
    }
    media = MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/mp4")
    req = yt().videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        status, resp = req.next_chunk(num_retries=5)
        if status:
            log.info("upload %d%%", int(status.progress() * 100))
    vid = resp["id"]
    log.info("uploaded https://youtu.be/%s (privacy: %s)", vid, resp.get("status", {}).get("privacyStatus"))

    if Quota.can_spend("thumbnail"):
        try:
            retry(lambda: yt().thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb), mimetype="image/jpeg")).execute(), log=log)
            Quota.spend("thumbnail")
        except Exception as e:  # noqa: BLE001
            log.warning("thumbnail failed (channel must be phone-verified for custom thumbnails): %s", e)

    pl_name = cfg["playlists"]["shorts" if plan["format"] == "short" else plan["pillar"]]
    try:
        pid = _playlist_id(pl_name)
        if pid and Quota.can_spend("playlist_insert"):
            yt().playlistItems().insert(part="snippet", body={"snippet": {"playlistId": pid,
                                        "resourceId": {"kind": "youtube#video", "videoId": vid}}}).execute()
            Quota.spend("playlist_insert")
    except Exception as e:  # noqa: BLE001
        log.warning("playlist step failed: %s", e)
    return vid
