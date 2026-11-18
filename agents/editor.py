"""VIDEO EDITOR — cuts footage to the narration, adds Tamil subtitles, captions,
watermark, music and loudness normalisation. Outputs 16:9 long videos or 9:16 Shorts. Pure FFmpeg."""
import random
import subprocess
from pathlib import Path

from .core import ROOT, config, get_logger
from .voice import ffprobe_duration

log = get_logger("editor")
VICE = ["0xff2d95", "0x7b2ff7", "0x00e5ff", "0xff8a00", "0x18ffb0"]


def _run(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(map(str, cmd[:6]))}…\n{r.stderr[-1500:]}")


def _segment(pick: dict, dur: float, out: Path, W: int, H: int):
    v = config()["video"]
    enc = ["-an", "-c:v", "libx264", "-preset", v["preset"], "-crf", str(v["crf"]), "-pix_fmt", "yuv420p", "-r", str(v["fps"])]
    if pick["type"] == "clip":
        src = pick["path"]
        try:
            total = ffprobe_duration(src)
        except Exception:  # noqa: BLE001
            total = 0
        start = random.uniform(0, max(0.0, total - dur - 0.5)) if total > dur + 1 else 0
        # cover-crop + slow drift so static shots still feel alive
        vf = (f"scale={int(W*1.08)}:{int(H*1.08)}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H}:x='(iw-{W})/2+(iw-{W})/2*sin(t/4)':y='(ih-{H})/2',"
              f"eq=saturation=1.15:contrast=1.05,setsar=1")
        _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-stream_loop", "-1", "-i", str(src),
              "-t", f"{dur:.3f}", "-vf", vf, *enc, str(out)])
    else:
        c0, c1, c2 = random.sample(VICE, 3)
        src = f"gradients=s={W}x{H}:c0={c0}:c1={c1}:c2={c2}:nb_colors=3:speed=0.015:d={dur:.3f}:r={v['fps']}"
        vf = "noise=alls=8:allf=t,vignette=PI/4,setsar=1"
        _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", src, "-vf", vf, *enc, str(out)])


def _ass_time(t: float) -> str:
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _chunks(text: str, n: int) -> list[str]:
    words = text.split()
    return [" ".join(words[i:i + n]) for i in range(0, len(words), n)] or [text]


def _ass_escape(s: str) -> str:
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(scenes: list[dict], W: int, H: int, portrait: bool) -> str:
    cfg = config()
    font = cfg["video"]["font"]
    sub_size = int(H * (0.042 if portrait else 0.058))
    cap_size = int(H * (0.055 if portrait else 0.085))
    sub_margin = int(H * (0.30 if portrait else 0.07))
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font},{sub_size},&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,{max(3, sub_size//12)},2,2,{int(W*0.06)},{int(W*0.06)},{sub_margin},1
Style: Cap,{font},{cap_size},&H0000E5FF,&H000000FF,&H00952DFF,&H96000000,-1,0,0,0,100,100,1,0,1,{max(4, cap_size//9)},3,8,{int(W*0.05)},{int(W*0.05)},{int(H*(0.12 if portrait else 0.06))},1
Style: Mark,{font},{int(H*0.026)},&H50FFFFFF,&H000000FF,&H80000000,&H00000000,-1,0,0,0,100,100,0,0,1,2,0,9,30,30,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    per = 5 if portrait else 8
    for sc in scenes:
        a, b = sc["start"], sc["end"] - 0.2
        chunks = _chunks(sc["narration"], per)
        total = sum(len(c) for c in chunks) or 1
        t = a
        for c in chunks:
            d = (b - a) * len(c) / total
            pop = r"{\fscx108\fscy108\t(0,120,\fscx100\fscy100)}" if portrait else ""
            lines.append(f"Dialogue: 0,{_ass_time(t)},{_ass_time(t + d)},Sub,,0,0,0,,{pop}{_ass_escape(c)}")
            t += d
        if sc.get("onscreen"):
            lines.append(f"Dialogue: 1,{_ass_time(a)},{_ass_time(min(b, a + 2.8))},Cap,,0,0,0,,"
                         r"{\fad(120,200)\fscx70\fscy70\t(0,180,\fscx100\fscy100)}" + _ass_escape(sc["onscreen"]))
    if cfg["video"].get("watermark"):
        lines.append(f"Dialogue: 2,0:00:00.00,{_ass_time(scenes[-1]['end'])},Mark,,0,0,0,,{_ass_escape(cfg['channel']['handle'])}")
    return head + "\n".join(lines) + "\n"


def run(plan: dict, script: dict, voice: dict, picks: list[dict], workdir: Path) -> Path:
    cfg = config()
    fmt = plan["format"]
    W, H = cfg["video"][fmt]["resolution"]
    portrait = H > W
    seg_dir = workdir / "segments"
    seg_dir.mkdir(exist_ok=True)
    segs = []
    for i, (sc, pk) in enumerate(zip(script["scenes"], picks)):
        dur = sc["end"] - sc["start"]
        # long scenes: split into 2–3 shots so the visuals keep moving
        shots = 1 if dur < 6 else min(3, int(dur // 4))
        for j in range(shots):
            out = seg_dir / f"{i:02d}_{j}.mp4"
            _segment(pk, dur / shots, out, W, H)
            segs.append(out)
    (seg_dir / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in segs))
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "../visual.mp4"],
         cwd=seg_dir)

    (workdir / "subs.ass").write_text(build_ass(script["scenes"], W, H, portrait), encoding="utf-8")

    music = sorted((ROOT / "assets" / "music").glob("*.mp3")) + sorted((ROOT / "assets" / "music").glob("*.m4a"))
    out = workdir / f"final_{fmt}.mp4"
    v = cfg["video"]
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", "visual.mp4", "-i", "narration.wav"]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(random.choice(music))]
        fc = (f"[0:v]ass=subs.ass[v];[1:a]aresample=44100[n];"
              f"[2:a]volume={v['music_volume']},aresample=44100[m];"
              f"[n][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    else:
        fc = "[0:v]ass=subs.ass[v];[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", v["preset"],
            "-crf", str(v["crf"]), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-t", f"{voice['duration']:.2f}", "-movflags", "+faststart", out.name]
    _run(cmd, cwd=workdir)
    log.info("rendered %s (%.1fs, %dx%d)", out.name, voice["duration"], W, H)
    return out
