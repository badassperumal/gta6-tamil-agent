"""THUMBNAIL DESIGNER — grabs the most vivid frame, boosts it, and stamps big Tamil/English
text + a 'TAMIL' badge. Rendered with FFmpeg + libass so Tamil glyphs shape correctly."""
import re
import subprocess
from pathlib import Path

from .core import config, get_logger
from .voice import ffprobe_duration

log = get_logger("thumbnail")


def _best_frame(video: Path, out: Path):
    """Sample frames and keep the most colourful/contrasty one (YouTube CTR loves saturation)."""
    dur = ffprobe_duration(video)
    best, best_score = None, -1
    for k in range(1, 9):
        t = dur * k / 10
        f = out.parent / f"cand_{k}.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                        "-vf", "scale=320:-1", str(f)], check=True)
        stats = subprocess.run(["ffprobe", "-v", "error", "-f", "lavfi", "-i",
                                f"movie={f.name},signalstats", "-show_entries",
                                "frame_tags=lavfi.signalstats.SATAVG,lavfi.signalstats.YHIGH,lavfi.signalstats.YLOW",
                                "-of", "default=nw=1:nk=1"], capture_output=True, text=True, cwd=out.parent).stdout.split()
        try:
            sat, yhi, ylo = map(float, stats[:3])
            score = sat * 2 + (yhi - ylo)
        except ValueError:
            score = 0
        if score > best_score:
            best, best_score = t, score
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{best:.2f}", "-i", str(video), "-frames:v", "1", str(out)],
                   check=True)


def run(video: Path, text: str, workdir: Path, portrait: bool) -> Path:
    cfg = config()
    font = cfg["video"]["font"]
    W, H = 1280, 720
    frame = workdir / "thumb_frame.png"
    _best_frame(video, frame)
    text = re.sub(r"[^\u0000-\uFFFF]|[\u2600-\u27BF]", "", text)  # emoji don't render in libass
    words = text.strip().split() or ["GTA", "6"]
    line1 = " ".join(words[: max(1, len(words) // 2 + len(words) % 2)])
    line2 = " ".join(words[len(line1.split()):])
    ass = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Big,{font},132,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,11,6,1,50,50,60,1
Style: Big2,{font},132,&H0000E5FF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,11,6,1,50,50,60,1
Style: Badge,{font},54,&H00FFFFFF,&H000000FF,&H00952DFF,&H00952DFF,-1,0,0,0,100,100,2,0,3,14,0,7,40,40,36,1
Style: Game,{font},64,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,1,0,1,6,3,9,40,40,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,Badge,,0,0,0,,TAMIL
Dialogue: 0,0:00:00.00,0:00:05.00,Game,,0,0,0,,GTA 6
Dialogue: 0,0:00:00.00,0:00:05.00,Big,,0,0,0,,{{\\an1\\pos(50,{H - 60 - (150 if line2 else 0)})}}{line1}
Dialogue: 0,0:00:00.00,0:00:05.00,Big2,,0,0,0,,{{\\an1\\pos(50,{H - 60})}}{line2}
"""
    (workdir / "thumb.ass").write_text(ass, encoding="utf-8")
    out = workdir / "thumbnail.jpg"
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          "eq=saturation=1.45:contrast=1.18:brightness=0.02,unsharp=5:5:1.0,vignette=PI/5,ass=thumb.ass")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", frame.name, "-vf", vf, "-q:v", "3", "-frames:v", "1", out.name],
                   check=True, cwd=workdir)
    log.info("thumbnail '%s' → %s (%d KB)", text, out.name, out.stat().st_size // 1024)
    return out
