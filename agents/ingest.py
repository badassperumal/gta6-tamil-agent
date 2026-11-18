"""FOOTAGE INGEST — turns YouTube links of YOUR OWN gameplay into a tagged clip library.

Flow:  link(s) → ownership check (must be your channel) → download (yt-dlp) →
       scene-cut into 6–30s clips → AI tags each clip from a frame (Gemini vision, free) →
       upload to the GitHub Release 'footage' → editor agent uses them in every video.

Links from any other channel are refused: re-using other creators' gameplay gets
copyright strikes and kills monetisation.
"""
import base64
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import requests

from .core import ROOT, State, config, get_logger, mock
from .voice import ffprobe_duration

log = get_logger("ingest")
YT_ID = re.compile(r"(?:youtu\.be/|youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/|embed/))([A-Za-z0-9_-]{11})")


def parse_ids(text: str) -> list[str]:
    return list(dict.fromkeys(YT_ID.findall(text or "")))


# ── 1. ownership ────────────────────────────────────────────────────────────
def check_ownership(ids: list[str]) -> tuple[list[dict], list[str]]:
    """Returns (allowed videos with metadata, rejection messages)."""
    from .core.youtube import my_channel_id, yt
    allowed_channels = {my_channel_id(), *config()["footage"].get("allowed_channel_ids", [])}
    r = yt().videos().list(part="snippet,contentDetails", id=",".join(ids[:50])).execute()
    found = {v["id"]: v for v in r.get("items", [])}
    ok, rejected = [], []
    for vid in ids:
        v = found.get(vid)
        if not v:
            rejected.append(f"`{vid}`: not found (private videos must be on your own channel; use unlisted).")
        elif v["snippet"]["channelId"] not in allowed_channels:
            rejected.append(f"`{vid}` ({v['snippet']['channelTitle']}): ❌ not your channel. Only your own gameplay is allowed.")
        else:
            ok.append({"id": vid, "title": v["snippet"]["title"], "description": v["snippet"].get("description", "")[:500],
                       "tags": v["snippet"].get("tags", [])[:15]})
    return ok, rejected


# ── 2. download ─────────────────────────────────────────────────────────────
def download(vid: str, dest: Path) -> Path:
    out = dest / f"{vid}.mp4"
    cmd = ["yt-dlp", "-q", "--no-playlist", "--no-warnings",
           "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
           "--merge-output-format", "mp4", "-o", str(out), f"https://www.youtube.com/watch?v={vid}"]
    cookies = os.getenv("YTDLP_COOKIES")
    if cookies:  # Netscape cookies.txt of YOUR account — helps when YouTube blocks cloud IPs
        cf = dest / "cookies.txt"
        cf.write_text(cookies)
        cmd[1:1] = ["--cookies", str(cf)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out.exists():
        hint = (" YouTube blocked the cloud server. Add the YTDLP_COOKIES secret, or run "
                "`python orchestrator.py ingest --urls ...` on your PC instead.") if "bot" in r.stderr.lower() or "sign in" in r.stderr.lower() else ""
        raise RuntimeError(f"download failed for {vid}: {r.stderr.strip()[-400:]}{hint}")
    return out


# ── 3. scene cut ────────────────────────────────────────────────────────────
def scene_cuts(video: Path, threshold: float = 0.32) -> list[float]:
    """Keyframe-only scene detection: fast even on hour-long recordings."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-skip_frame", "nokey", "-i", str(video), "-vf",
                        f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    return sorted(float(t) for t in re.findall(r"pts_time:([0-9.]+)", r.stderr))


def plan_segments(duration: float, cuts: list[float], lo: float, hi: float, max_n: int) -> list[tuple[float, float]]:
    edge = min(5.0, duration * 0.05)                     # skip menus / fade at start & end
    points = [edge] + [c for c in cuts if edge < c < duration - edge] + [duration - edge]
    segs, start = [], points[0]
    for p in points[1:]:
        if p - start < lo:
            continue                                      # too short → merge with next shot
        while p - start > hi:                             # too long → split evenly
            n = int((p - start) // hi) + 1
            step = (p - start) / n
            segs.append((start, start + step))
            start += step
        segs.append((start, p))
        start = p
    if len(segs) > max_n:                                 # keep an even spread across the video
        idx = [round(i * (len(segs) - 1) / (max_n - 1)) for i in range(max_n)]
        segs = [segs[i] for i in dict.fromkeys(idx)]
    return [(round(a, 2), round(b, 2)) for a, b in segs if b - a >= lo]


def cut_clip(src: Path, a: float, b: float, out: Path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{a}", "-i", str(src), "-t", f"{b - a:.2f}",
                    "-vf", "scale='min(1920,iw)':-2", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], check=True)


# ── 4. tagging ──────────────────────────────────────────────────────────────
def _slug(words: list[str]) -> str:
    clean = [re.sub(r"[^a-z0-9]", "", w.lower()) for w in words]
    return "_".join([w for w in clean if w][:6]) or "gameplay"


def base_tags(meta: dict) -> list[str]:
    text = " ".join([meta["title"], " ".join(meta["tags"])]).lower()
    vocab = ["car", "chase", "police", "heist", "bank", "beach", "night", "sunset", "boat", "swamp", "plane", "helicopter",
             "mission", "jason", "lucia", "city", "vice", "map", "gun", "fight", "race", "bike", "money", "story", "cutscene"]
    return [w for w in vocab if w in text][:4]


def vision_tags(frame: Path) -> list[str]:
    key = os.getenv("GEMINI_API_KEY")
    if not key or mock() or not config()["footage"].get("vision_tagging", True):
        return []
    from .core.llm import discover
    model = (discover("gemini", key) or ["gemini-flash-latest"])[0]
    b64 = base64.b64encode(frame.read_bytes()).decode()
    body = {"model": model, "temperature": 0.2, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "This is a GTA 6 gameplay frame. Return 3-5 lowercase English keywords for what is on screen "
                                 "(e.g. car, chase, police, night, beach, boat, heist, interior, cutscene, aerial, sunset). "
                                 "Return only a JSON array of strings."},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]}
    for attempt in range(3):
        try:
            r = requests.post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                              headers={"Authorization": f"Bearer {key}"}, json=body, timeout=60)
            if r.status_code == 429:
                time.sleep(15 * (attempt + 1))
                continue
            r.raise_for_status()
            txt = r.json()["choices"][0]["message"]["content"]
            return [str(t) for t in json.loads(txt[txt.find("["): txt.rfind("]") + 1])][:5]
        except Exception as e:  # noqa: BLE001
            log.warning("vision tag failed: %s", e)
            break
    return []


# ── 5. upload to release ────────────────────────────────────────────────────
def upload_release(files: list[Path]):
    tag = config()["footage"]["github_release_tag"]
    if subprocess.run(["gh", "release", "view", tag], capture_output=True).returncode != 0:
        subprocess.run(["gh", "release", "create", tag, "--title", "Footage library",
                        "--notes", "GTA 6 gameplay clips used by the editor agent."], check=True)
    for i in range(0, len(files), 20):
        subprocess.run(["gh", "release", "upload", tag, "--clobber", *map(str, files[i:i + 20])], check=True)


# ── orchestration ───────────────────────────────────────────────────────────
def process_video(meta: dict, work: Path, keep_local: bool) -> list[Path]:
    fcfg = config()["footage"]
    src = download(meta["id"], work)
    dur = ffprobe_duration(src)
    segs = plan_segments(dur, scene_cuts(src), fcfg.get("clip_min_seconds", 6), fcfg.get("clip_max_seconds", 30),
                         fcfg.get("max_clips_per_video", 40))
    base = base_tags(meta)
    lib = ROOT / fcfg["local_dir"]
    lib.mkdir(parents=True, exist_ok=True)
    clips = []
    for n, (a, b) in enumerate(segs, 1):
        tmp = work / f"tmp_{n:03d}.mp4"
        cut_clip(src, a, b, tmp)
        frame = work / f"f_{n:03d}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{(b - a) / 2:.2f}", "-i", str(tmp),
                        "-frames:v", "1", "-vf", "scale=640:-2", str(frame)], check=True)
        tags = list(dict.fromkeys(vision_tags(frame) + base))
        final = (lib if keep_local else work) / f"{_slug(tags)}_{meta['id']}_{n:02d}.mp4"
        tmp.replace(final)
        clips.append(final)
    src.unlink(missing_ok=True)
    log.info("%s → %d clips (%.0fs source)", meta["id"], len(clips), dur)
    return clips


def run(text: str, upload: bool = True) -> str:
    ids = parse_ids(text)
    if not ids:
        return "No YouTube links found. Paste links like https://youtu.be/XXXXXXXXXXX"
    done = State.load("ingested", {})
    new_ids = [i for i in ids if i not in done]
    report = [f"⏭️ `{i}` already in the library" for i in ids if i in done]
    if not new_ids:
        return "\n".join(report)
    allowed, rejected = check_ownership(new_ids)
    report += rejected
    total = 0
    with tempfile.TemporaryDirectory() as td:
        for meta in allowed:
            try:
                clips = process_video(meta, Path(td), keep_local=not upload)
                if upload and clips:
                    upload_release(clips)
                done[meta["id"]] = {"title": meta["title"], "clips": [c.name for c in clips]}
                State.save("ingested", done)
                total += len(clips)
                report.append(f"✅ **{meta['title']}** → {len(clips)} clips: " +
                              ", ".join(f"`{c.stem.rsplit('_', 2)[0]}`" for c in clips[:6]) + (" …" if len(clips) > 6 else ""))
            except Exception as e:  # noqa: BLE001
                report.append(f"⚠️ `{meta['id']}`: {e}")
    report.append(f"\n**{total} new clips** added to the footage library.")
    msg = "\n".join(report)
    log.info(msg)
    return msg
