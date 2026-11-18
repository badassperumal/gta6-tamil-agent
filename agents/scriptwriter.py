"""SCRIPTWRITER — writes the spoken Tamil script, split into scenes with visual cues."""
import json

from .core import config, get_logger
from .core.llm import chat_json

log = get_logger("writer")


def run(plan: dict, feedback: str | None = None) -> dict:
    cfg = config()
    fmt = plan["format"]
    lo, hi = cfg["video"][fmt]["target_words"]
    scenes = "6-8 scenes of 1-2 sentences" if fmt == "short" else "14-22 scenes of 2-4 sentences"
    structure = (
        "Short: 0-2s scroll-stopping hook (question or shock fact) → 3-4 fast value beats → loopable last line that "
        "makes people rewatch + 'Subscribe பண்ணுங்க' in under 3 words."
        if fmt == "short" else
        "Long: 0-15s hook that promises a payoff → quick intro (channel name once) → numbered sections with "
        "open loops ('last tip தான் மிக முக்கியம்') → mid-video like/subscribe nudge → strong ending + next-video tease."
    )
    system = f"""You are the head scriptwriter of "{cfg['channel']['name']}", a Tamil GTA 6 YouTube channel.
Persona: {cfg['channel']['persona']}
Write narration in natural SPOKEN Tamil (Tamil script), keeping common English gaming words in English letters
(GTA 6, mission, car, map, update, Rockstar, Jason, Lucia, Vice City, Leonida). No formal/literary Tamil.
{structure}
Hard rules:
- Use ONLY the facts given. If something is a rumour or theory, say so in the narration ("இது ஒரு theory தான்").
- Story content: add a spoiler warning at the start.
- No piracy, cracks, free-download claims, cheats that break ToS, hate, or misleading clickbait.
- Total narration {lo}-{hi} words, {scenes}.
- Each scene gets a "visual" = 2-4 English keywords for footage search (e.g. "car chase night", "beach vice city", "map overview").
- "onscreen" = optional 1-4 word caption (English or Tamil) shown big on screen, for emphasis."""

    user = json.dumps({
        "plan": {k: plan.get(k) for k in ("format", "pillar", "topic", "angle", "working_title", "hook_line", "facts")},
        "reviewer_feedback_to_fix": feedback,
        "output_schema": {"scenes": [{"narration": "Tamil text", "visual": "english keywords", "onscreen": "short caption or empty"}],
                          "thumbnail_text": "2-4 punchy words, CAPS if English", "end_question": "a Tamil question for viewers to answer in comments"},
    }, ensure_ascii=False)

    script = chat_json(system, user, temperature=0.85)
    script["scenes"] = [s for s in script.get("scenes", []) if s.get("narration", "").strip()]
    script["word_count"] = sum(len(s["narration"].split()) for s in script["scenes"])
    log.info("script: %d scenes, %d words", len(script["scenes"]), script["word_count"])
    return script
