"""VOICE ACTOR — free Tamil text-to-speech, scene by scene.
Engines: Microsoft Edge neural voices (edge-tts) → Google Translate TTS (gTTS) fallback.
Produces one narration track + exact per-scene timings for subtitles and cuts."""
import asyncio
import subprocess
from pathlib import Path

from .core import config, get_logger, mock

log = get_logger("voice")


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def _edge(text: str, out: Path):
    import edge_tts
    v = config()["voice"]

    async def go():
        await edge_tts.Communicate(text, v["edge_voice"], rate=v["edge_rate"], pitch=v["edge_pitch"]).save(str(out))
    asyncio.run(go())


def _gtts(text: str, out: Path):
    from gtts import gTTS
    raw = out.with_suffix(".raw.mp3")
    gTTS(text=text, lang="ta").save(str(raw))
    # gTTS is slow & flat — speed it up a bit
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-filter:a", "atempo=1.2", str(out)], check=True)
    raw.unlink(missing_ok=True)


def _mock(text: str, out: Path):
    secs = max(1.5, len(text.split()) / 2.3)  # ≈ Tamil speaking rate
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency=180:duration={secs}",
                    "-filter:a", "volume=0.05", str(out)], check=True)


ENGINES = {"edge": _edge, "gtts": _gtts}


def synth(text: str, out: Path):
    if mock():
        return _mock(text, out)
    errs = []
    for name in config()["voice"]["engine_order"]:
        for attempt in range(2):
            try:
                ENGINES[name](text, out)
                if out.exists() and out.stat().st_size > 1000:
                    return name
            except Exception as e:  # noqa: BLE001
                errs.append(f"{name}: {e}")
    raise RuntimeError("All TTS engines failed: " + " | ".join(errs[-3:]))


def run(script: dict, workdir: Path) -> dict:
    vdir = workdir / "voice"
    vdir.mkdir(parents=True, exist_ok=True)
    gap = 0.25  # breath between scenes
    t = 0.0
    parts = []
    for i, sc in enumerate(script["scenes"]):
        mp3 = vdir / f"s{i:02d}.mp3"
        synth(sc["narration"], mp3)
        wav = vdir / f"s{i:02d}.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-af", f"apad=pad_dur={gap}",
                        "-ar", "44100", "-ac", "2", str(wav)], check=True)
        d = ffprobe_duration(wav)
        sc["start"], sc["end"] = round(t, 3), round(t + d, 3)
        t += d
        parts.append(wav)
    lst = vdir / "list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
    track = workdir / "narration.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(track)],
                   check=True, cwd=vdir)
    log.info("narration %.1fs across %d scenes", t, len(parts))
    return {"audio": track, "duration": t}
