"""Canned answers so the whole pipeline can be tested offline (MOCK=1)."""
import json
from datetime import datetime, timezone

SCENES = [
    {"narration": "GTA 6 la இந்த ஒரு secret உங்களுக்கு தெரியுமா? தெரியலனா இந்த video முழுசா பாருங்க!", "visual": "car chase night", "onscreen": "SECRET!"},
    {"narration": "வணக்கம் நண்பர்களே, நம்ம GTA 6 Tamil channel-க்கு welcome. இன்னைக்கு Vice City-ல இருக்குற மூணு முக்கியமான விஷயங்களை பாக்கலாம்.", "visual": "vice city beach", "onscreen": ""},
    {"narration": "முதல் விஷயம், map ரொம்ப பெரியது. Leonida state முழுசா explore பண்ணலாம், beach முதல் swamp வரைக்கும்.", "visual": "map overview aerial", "onscreen": "HUGE MAP"},
    {"narration": "ரெண்டாவது, Jason and Lucia ரெண்டு பேரையும் நீங்க switch பண்ணி play பண்ணலாம்னு Rockstar சொல்லியிருக்காங்க.", "visual": "characters jason lucia", "onscreen": "2 HEROES"},
    {"narration": "மூணாவது, இது ஒரு theory தான், ஆனா community நிறைய பேர் இதை நம்புறாங்க. உங்க opinion என்ன?", "visual": "neon city night", "onscreen": "THEORY?"},
    {"narration": "இந்த video பிடிச்சிருந்தா like பண்ணுங்க, subscribe பண்ணுங்க. அடுத்த video-ல சந்திப்போம்!", "visual": "sunset drive", "onscreen": "SUBSCRIBE"},
]


def mock_reply(system: str, user: str) -> str:
    s = system.lower()
    if "content strategist" in s:
        return json.dumps({"pillar": "secrets", "topic": "GTA 6 hidden secrets", "story_key": None,
                           "angle": "3 things most players miss", "working_title": "GTA 6 la யாருக்கும் தெரியாத 3 Secrets!",
                           "hook_line": "இந்த secret தெரியுமா?", "footage_tags": ["car", "night", "beach"],
                           "facts": ["GTA 6 is set in Leonida", "Protagonists are Jason and Lucia"], "sources": [], "why": "mock"},
                          ensure_ascii=False)
    if "head scriptwriter" in s:
        return json.dumps({"scenes": SCENES, "thumbnail_text": "3 SECRETS 😱", "end_question": "உங்களுக்கு பிடிச்ச character யாரு? Jason or Lucia?"},
                          ensure_ascii=False)
    if "policy reviewer" in s:
        return json.dumps({"pass": True, "score_1_to_10": 8, "problems": [], "fix_instructions": ""})
    if "seo expert" in s:
        return json.dumps({"title": "GTA 6 la யாருக்கும் தெரியாத 3 Secrets! | GTA 6 Tamil",
                           "description": "GTA 6 Tamil secrets! Vice City, Jason, Lucia பற்றி முக்கிய விஷயங்கள்.",
                           "tags": ["gta 6 tamil", "gta 6 secrets tamil", "gta vi tamil", "vice city tamil"],
                           "hashtags": ["#GTA6", "#GTA6Tamil", "#TamilGaming"]}, ensure_ascii=False)
    return json.dumps({"notes": "mock"})


def mock_trends():
    t = datetime.now(timezone.utc).isoformat()
    return [{"title": "GTA 6 launch trailer breaks records", "link": "https://example.com/a", "source": "google_news",
             "summary": "Rockstar's launch trailer hit record views.", "published": t, "pop": 1}]
