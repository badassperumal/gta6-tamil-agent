# 🎮 GTA 6 Tamil — Autonomous YouTube Agent

This is a self-running Tamil YouTube channel about GTA 6. It is built from 14 sub-agents and runs 24/7 on **GitHub Actions** using **only free services**. It needs no server and no paid APIs.

```
                         ┌──────────────── ORCHESTRATOR (channel manager) ────────────────┐
 every 3h  📡 SCOUT ─────┤ Google News + Reddit → scored stories → breaking? → fire a Short │
 11:00 / 18:00 / 21:00 IST│                                                                 │
   🎬 PRODUCE:  STRATEGIST → SCRIPTWRITER ⇄ REVIEWER (≤3 drafts) → VOICE → FOOTAGE →        │
                EDITOR → THUMBNAIL → SEO → PUBLISHER → MARKETING                             │
 every 2h  💬 COMMUNITY ── Tamil replies · hold spam · viewer requests → idea queue ─────────┤
 daily     📊 ANALYST ──── YouTube Analytics → re-weights pillars → weekly report (Issue) ──┤
 on error  🚨 MONITOR ──── opens a GitHub Issue → you get an email/phone alert ──────────────┘
                 memory: state/*.json (committed after every run — the agents learn over time)
```

| Agent | File | What it does |
|---|---|---|
| Orchestrator | `orchestrator.py` | Runs the pipeline, keeps the history and handles failures |
| Trend Scout | `agents/trend_scout.py` | Google News + r/GTA6 RSS, dedupes stories, detects breaking news |
| Strategist | `agents/strategist.py` | Picks the topic and angle from trends, viewer requests and analytics |
| Scriptwriter | `agents/scriptwriter.py` | Writes the spoken Tamil (Tanglish) script with a scene-by-scene visual plan |
| Reviewer | `agents/reviewer.py` | Fact, policy and hook gate. Rejects a draft and sends it back for a rewrite |
| Voice | `agents/voice.py` | Free Tamil TTS (Edge neural `ta-IN-ValluvarNeural`, gTTS fallback) |
| Footage | `agents/footage.py` | Matches your tagged GTA 6 clips to each scene (Pexels / neon fallback) |
| Editor | `agents/editor.py` | FFmpeg cuts, Tamil subtitles, captions, watermark, music, loudness |
| Thumbnail | `agents/thumbnail.py` | Picks the most vivid frame, adds bold Tamil/English text and a TAMIL badge |
| SEO | `agents/seo.py` | Title, description, chapters, Tamil/Tanglish tags |
| Publisher | `agents/publisher.py` | Upload, thumbnail, playlists, AI disclosure |
| Marketing | `agents/marketing.py` | Engagement comment, Telegram channel post, Discord post |
| Community | `agents/community.py` | Replies to comments in Tamil, moderates spam, turns requests into ideas |
| Analyst | `agents/analyst.py` | Learns what works, scans competitors, writes the weekly report |
| Footage Ingest | `agents/ingest.py` | Your YouTube gameplay links → ownership check → scene-cut, AI-tagged clips |

Output each day: **1 long video (6–9 min, 16:9) + 2 Shorts (9:16)**, plus up to 2 extra breaking-news Shorts.

---

## Setup (about 45 minutes, one time)

### 1. Create the repo
Create a GitHub repo (see *Minutes* below for public vs private) and push this folder to it.

### 2. Free AI keys (add at least one; two is safer)
| Secret | Where | Notes |
|---|---|---|
| `GEMINI_API_KEY` | aistudio.google.com → Get API key | Best Tamil quality. No card needed |
| `GROQ_API_KEY` | console.groq.com → API Keys | Open-weight models (gpt-oss, Llama) |
| `OPENROUTER_API_KEY` | openrouter.ai → Keys | Optional extra fallback (`:free` models) |
| `PEXELS_API_KEY` | pexels.com/api | Optional free b-roll when you have no clips |

The router tries the providers in the order of `llm.chain` in `config.yaml` and skips any that fail.

### 3. YouTube access
1. Go to console.cloud.google.com and create a project. Enable **YouTube Data API v3** and **YouTube Analytics API**.
2. Set up the **OAuth consent screen**: External, add yourself as a user, then click **"Publish app" → In production**. *If you skip this, the token dies after 7 days.*
3. Create **Credentials → OAuth client ID → Desktop app** and download `client_secret.json`.
4. On your PC run:
   ```bash
   pip install google-auth-oauthlib
   python scripts/get_refresh_token.py client_secret.json
   ```
   Log in with the channel's Google account. Add the printed `YT_CLIENT_ID`, `YT_CLIENT_SECRET` and `YT_REFRESH_TOKEN` as repo secrets.
5. **⚠️ Apply for the YouTube API compliance audit right away.** It is free and uses the "YouTube API Services – Audit and Quota Extension Form". Until it is approved, YouTube **locks every API upload as private, permanently** (locked videos can't be made public). So until then, set the repo variable `MANUAL_UPLOAD=true`: the agents render everything and you upload the artifact (video + thumbnail + `metadata.txt`) in YouTube Studio. After approval, delete the variable and it publishes on its own.
6. Verify the channel by phone (youtube.com/verify). Custom thumbnails need this.

### 4. Optional promotion
`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (create a bot with @BotFather and add it to your channel as an admin), and `DISCORD_WEBHOOK_URL`.

### 5. Footage
GTA 6 is console-only at launch, so the agent **cannot record gameplay itself**. Record clips on PS5/Xbox, name them with tags, and upload them to the `footage` release. See `assets/footage/README.md`. Until you do, videos use free Pexels Miami/neon b-roll, or generated Vice-City neon backgrounds.

#### Easiest: paste YouTube links of your own gameplay
1. On PS5/Xbox, share your capture to **your** YouTube channel as **Unlisted**.
2. In your repo go to **Issues → New issue → 🎮 Add gameplay footage**, paste the links (one per line) and submit. This works from the GitHub phone app.
3. The 🎮 Ingest agent then:
   - checks each link really belongs to your channel and rejects other creators' videos;
   - downloads it and splits it at scene changes into 6–30 second clips;
   - names every clip with AI-made tags (`car_chase_police_night_…`) using free Gemini vision;
   - uploads the clips to the `footage` release, comments the results on the issue and closes it.

You can also run it from **Actions → 🎮 Ingest gameplay footage → Run workflow**, or on your PC with
`python orchestrator.py ingest --urls "https://youtu.be/…"` (this needs `gh auth login`, ffmpeg and deno).

> YouTube sometimes blocks downloads from cloud servers ("Sign in to confirm you're not a bot"). When that happens, either
> add a `YTDLP_COOKIES` secret (export `cookies.txt` of **your** YouTube login with a "Get cookies.txt LOCALLY" browser extension, ideally from a spare browser profile) or run the ingest command on your PC. The issue comment tells you when this has happened.
> If you keep raw gameplay on a second channel, add its ID to `footage.allowed_channel_ids` in `config.yaml`.

### 6. Turn it on
Go to Actions → enable workflows → **🎬 Produce & publish video → Run workflow** with `dry_run = true`. Download the artifact and watch the result. Then run **📡 Trend scout** once. From then on, everything runs on schedule.

---

## Running cost: ₹0
- **GitHub Actions:** unlimited minutes for **public** repos. Secrets stay private even in a public repo. A **private** repo gets 2,000 free minutes a month, and this setup uses about 1,600–1,900. If you go private, cut `engage` to every 4h.
- **YouTube API:** the quota tracker (`state/quota.json`) keeps daily spend under the 10,000-unit limit.
- **LLMs / TTS / FFmpeg:** free tiers and open-source tools.

## Tuning
Everything is in `config.yaml`: persona, content pillars, voice (`ta-IN-PallaviNeural` for a female voice), resolution, video length, banned phrases, reply limits and playlists. Schedule times are the `cron:` lines in `.github/workflows/*.yml` (UTC = IST − 5:30).

## Test locally (no keys, no network)
```bash
pip install -r requirements.txt   # + ffmpeg and fonts-noto-core
MOCK=1 DRY_RUN=1 python orchestrator.py produce --format short
# → output/latest/final_short.mp4 + thumbnail.jpg
```

## Rules this system follows (to keep the channel safe)
- It narrates only over **your own gameplay** or free stock footage. It never re-uploads trailers or other creators' videos.
- The reviewer blocks invented leaks or dates, piracy/"free download"/mod-menu content, and story spoilers without a warning.
- Every upload declares the AI voice (`containsSyntheticMedia`) and carries a Rockstar fan-channel disclaimer.
- YouTube can demonetise mass-produced, repetitive channels ("inauthentic content"). Fresh footage, varied topics and the reviewer's quality bar are what protect monetisation. Watch the weekly report and keep adding clips.
