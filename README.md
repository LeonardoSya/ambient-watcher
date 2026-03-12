# Ambient Watcher

7x24 AI-powered environment sensing system for macOS.
Watches through your camera, listens through your microphone, learns your patterns, and alerts you to anomalies.

## What It Does

- **Sees** — Captures camera frames via ffmpeg, analyzes with MiniMax VLM (or OpenCV fallback)
- **Hears** — Monitors ambient sound via PyAudio, detects volume spikes and sudden silence
- **Remembers** — Dual-layer memory: all observations + highlighted keyframes, persisted to JSON
- **Thinks** — Multimodal fusion (vision + audio cross-reasoning), AI-powered status reports
- **Learns** — Builds a scene baseline, remembers known people, tracks activity patterns by hour
- **Alerts** — macOS notifications + colored terminal output when anomalies are detected

## Requirements

- macOS (AVFoundation required)
- ffmpeg (`brew install ffmpeg`)
- Python 3.10+

## Quick Start

```bash
# Setup
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# API key (optional — falls back to OpenCV without it)
export MINIMAX_API_KEY="sk-xxx"

# Diagnose devices
python diagnose.py

# Start watching
python main.py start
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `python main.py start` | Launch the watcher |
| `python main.py status` | Show memory stats |
| `python main.py query "问题"` | Ask about the environment |
| `python main.py learn "这个人是Seiya"` | Teach an entity |
| `python main.py baseline` | Show scene profile + learned patterns |
| `python main.py history` | Recent observations with timestamps |
| `python main.py history -m 60 -n 50` | Last 60 min, max 50 entries |

## How It Works

```
Camera ──5s──→ change detection ──>15%──→ VLM API ──→ Memory
                                                    ├→ Learner (baseline)
         ──120s──→ continuous VLM (even if static) ──┘

Microphone ──→ volume tracking ──→ Memory + Learner (activity)

Every 30s:  fuse(vision, audio) → AI status report
Every 10s:  anomaly scan → Notifier (macOS + terminal)
```

**VLM cost optimization:** VLM only fires on scene change (>15% diff) or every 120s.
The text API (MiniMax-M2.5) is used freely for reasoning — much cheaper.

## MiniMax API

Two endpoints, one API key:

| API | Endpoint | Purpose |
|-----|----------|---------|
| VLM | `/v1/coding_plan/vlm` | Image understanding |
| M2.5 | `/anthropic/v1/messages` | Text reasoning (Anthropic-compatible) |

Without API key, the system still works using OpenCV + keyword heuristics.

## Personalized Learning

The system gets smarter over time:

- **Scene baseline** — Learns what "normal" looks like (last 50 observations). Flags novel scenes.
- **Known entities** — Teach it people/objects: `learn "Seiya: 戴眼镜, 黑头发"`. Matches against future observations.
- **Activity patterns** — Builds an hour-by-hour histogram. "深夜3点有人出现" triggers higher-severity alerts than daytime activity.

All learned data persists in `data/learner.json`.

## Configuration

Edit `config/default.json`. Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `vision.capture_interval` | 5 | Seconds between camera captures |
| `watcher.continuous_vision_interval` | 120 | Forced VLM analysis interval (s) |
| `watcher.analysis_interval` | 30 | Status report interval (s) |
| `analyzer.anomaly_cooldown` | 60 | Min seconds between alerts |
| `learner.baseline_window` | 50 | Scene descriptions kept for baseline |
| `learner.novelty_threshold` | 0.5 | Below this keyword overlap = novel |

Full configuration reference: [SPEC.md](SPEC.md)

## Debug Tools

- **`camera_debug.py`** — Live camera preview at `http://localhost:8765` with zoom/Center Stage controls
- **`diagnose.py`** — Device detection, resolution testing, hardware status

## Device Strategy

| Strategy | Detail |
|----------|--------|
| MacBook only | Auto-filters iPhone/iPad continuity cameras |
| Widest FOV | Disables Center Stage + sets zoom=1.0 at startup |
| Native sample rate | Mic auto-adapts (MacBook Pro = 44100Hz) |

## Permissions

First run requires granting Terminal/iTerm camera + microphone access in System Settings.

## Technical Reference

See [SPEC.md](SPEC.md) for complete architecture docs, module reference, data flow diagrams,
API contracts, and storage formats. Designed for AI agent consumption.

---

*Built with claude-internal*
