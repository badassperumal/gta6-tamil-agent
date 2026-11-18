"""FOOTAGE LIBRARIAN — finds visuals for each scene.
Priority: 1) your own GTA 6 gameplay clips (GitHub Release 'footage', name files with tags,
e.g. `car_chase_night_vicecity_01.mp4`)  2) free Pexels b-roll (Miami/neon/cars)
3) generated Vice-City-style neon motion backgrounds. Never downloads trailers or other creators' videos."""
import os
import random
import re
from pathlib import Path

import requests

from .core import ROOT, State, config, get_logger, mock

log = get_logger("footage")
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm"}


def _tags(p: Path) -> set[str]:
    return set(re.findall(r"[a-z]+", p.stem.lower())) - {"mp", "clip", "gta", "gameplay"}


def library() -> list[Path]:
    d = ROOT / config()["footage"]["local_dir"]
    return sorted(p for p in d.rglob("*") if p.suffix.lower() in VIDEO_EXT)


def _pexels(query: str, dest: Path, portrait: bool) -> Path | None:
    key = os.getenv("PEXELS_API_KEY")
    if not key or mock():
        return None
    try:
        r = requests.get("https://api.pexels.com/videos/search", headers={"Authorization": key},
                         params={"query": query, "per_page": 10, "orientation": "portrait" if portrait else "landscape"},
                         timeout=30)
        r.raise_for_status()
        vids = r.json().get("videos", [])
        random.shuffle(vids)
        for v in vids:
            files = sorted([f for f in v["video_files"] if (f.get("height") or 0) >= 720],
                           key=lambda f: f.get("height") or 0)
            if not files:
                continue
            out = dest / f"pexels_{v['id']}.mp4"
            if not out.exists():
                with requests.get(files[0]["link"], stream=True, timeout=120) as s:
                    s.raise_for_status()
                    with open(out, "wb") as f:
                        for chunk in s.iter_content(1 << 20):
                            f.write(chunk)
            return out
    except Exception as e:  # noqa: BLE001
        log.warning("pexels '%s' failed: %s", query, e)
    return None


def pick(scenes: list[dict], workdir: Path, portrait: bool) -> list[dict]:
    """Returns per-scene {'type': 'clip'|'generated', 'path': Path|None}."""
    lib = library()
    usage = State.load("footage_usage", {})
    cache = workdir / "broll"
    cache.mkdir(exist_ok=True)
    used_now: set[str] = set()
    picks = []
    pex_q = config()["footage"]["pexels_queries"]
    for sc in scenes:
        want = set(re.findall(r"[a-z]+", sc.get("visual", "").lower()))
        choice = None
        if lib:
            def rank(p):
                return (len(_tags(p) & want) * 10) - usage.get(p.name, 0) - (50 if p.name in used_now else 0) + random.random()
            choice = max(lib, key=rank)
        elif config()["footage"]["pexels_fallback"]:
            choice = _pexels(sc.get("visual") or random.choice(pex_q), cache, portrait) or _pexels(random.choice(pex_q), cache, portrait)
        if choice:
            used_now.add(choice.name)
            usage[choice.name] = usage.get(choice.name, 0) + 1
            picks.append({"type": "clip", "path": choice})
        else:
            picks.append({"type": "generated", "path": None})
    State.save("footage_usage", usage)
    n_clip = sum(p["type"] == "clip" for p in picks)
    log.info("visuals: %d clips, %d generated (library has %d clips)", n_clip, len(picks) - n_clip, len(lib))
    return picks
