# Ambient Watcher - Technical Specification

> This document is the authoritative technical reference for the Ambient Watcher system.
> It is designed to be read by both humans and AI agents (e.g., OpenClaw) who need to
> understand, modify, or extend the codebase.

## 1. Overview

Ambient Watcher is a 7x24 AI-powered environment sensing system for macOS. It continuously
observes through the Mac's camera and microphone, builds an understanding of the environment,
learns personalized patterns, and proactively alerts the user to anomalies.

**Core loop:** Capture → Analyze → Remember → Reason → Alert

## 2. Architecture

### 2.1 System Layers

```
┌─────────────────────────────────────────────────────┐
│                    CLI (main.py)                     │
│  start / status / query / learn / baseline / history │
├─────────────────────────────────────────────────────┤
│              Orchestrator (watcher.py)                │
│  Manages threads: vision, hearing, analysis,         │
│  anomaly detection, continuous vision                │
├──────────┬──────────┬───────────┬───────────────────┤
│ Capture  │ Perceive │  Reason   │     Learn         │
│ camera   │ vision   │ analyzer  │     learner       │
│ micro-   │ hearing  │ notifier  │  (baseline,       │
│ phone    │          │           │   entities,       │
│          │          │           │   activity)       │
├──────────┴──────────┴───────────┴───────────────────┤
│                  Memory (memory.py)                   │
│  Observations (append-only log) + Keyframes          │
├─────────────────────────────────────────────────────┤
│               Persistence (data/*.json)              │
│  observations.json / keyframes.json / learner.json   │
└─────────────────────────────────────────────────────┘
```

### 2.2 Thread Model

`AmbientWatcher.start()` spawns 5 daemon threads:

| Thread | Function | Interval | Purpose |
|--------|----------|----------|---------|
| `_vision_loop` | Camera capture + change detection | 5s (configurable) | Capture frames, trigger VLM on >15% change |
| `_hearing_loop` | Microphone monitoring | Continuous (callback) | Volume tracking, audio description |
| `_analysis_loop` | Periodic status reports | 30s (configurable) | Multimodal fusion, AI status generation |
| `_anomaly_check_loop` | Fast anomaly scan | 10s (configurable) | Audio spikes, scene changes, learner checks |
| `_continuous_vision_loop` | Forced VLM analysis | 120s (configurable) | Prevents "blind spots" when scene is static |

All threads are daemon threads — they die when the main process exits.

### 2.3 Data Flow

```
Camera ──5s──→ detect_changes() ──>15%──→ VLM API ──→ Memory (observations)
                                                    ├──→ Learner (baseline)
                                                    └──→ Analyzer (anomalies)

Continuous ──120s──→ (skip if VLM ran recently) ──→ VLM API ──→ same as above

Microphone ──callback──→ volume_history[] ──→ Memory (observations)
                                           ├──→ Learner (activity)
                                           └──→ Analyzer (audio anomalies)

Analysis ──30s──→ fuse_observations(vision, audio)
               ──→ generate_status_report(memory + learner context)
               ──→ Memory (fused + report tags)

Anomaly ──10s──→ detect_anomalies(recent observations)
              ──→ Notifier (macOS + terminal) if threshold met
```

## 3. Module Reference

### 3.1 Capture Layer

#### `src/camera.py`
- Wraps ffmpeg via subprocess pipe for JPEG byte stream capture
- Uses avfoundation input on macOS
- Integrates with `mac_camera_control.py` for hardware settings

#### `src/mac_camera_control.py`
- PyObjC/AVFoundation native API for hardware control
- Disables Center Stage (Apple's auto-crop tracking)
- Sets `videoZoomFactor = 1.0` for maximum FOV
- Filters out iPhone/iPad continuity cameras

**Why ffmpeg, not OpenCV?** On macOS, `cv2.VideoCapture` triggers a permission popup
on every new process. ffmpeg inherits the terminal's existing camera permission.

#### `src/microphone.py`
- PyAudio polling mode with callback
- Auto-detects device native sample rate (MacBook Pro = 44100Hz)
- Filters by `device_keyword` to select correct mic (avoids iPhone)

### 3.2 Perception Layer

#### `src/vision.py` — `VisionAnalyzer`

Two analysis paths:

| Path | API | When Used | Output |
|------|-----|-----------|--------|
| VLM | `POST /v1/coding_plan/vlm` (MiniMax) | API key present | Natural language scene description |
| Local | OpenCV (Haar cascades, edge/color) | Fallback | Structured description (brightness, faces, edges) |

Key methods:
- `analyze(image_bytes, prompt) -> dict` — Primary entry point
- `detect_changes(img1, img2) -> float` — Pixel diff score (0-1), used for the 15% threshold
- `quick_check(image_bytes) -> str` — One-line description

**VLM API details:**
- Endpoint: `https://api.minimaxi.com/v1/coding_plan/vlm`
- Auth: `Authorization: Bearer {MINIMAX_API_KEY}`
- Payload: `{ "prompt": str, "image_url": "data:image/jpeg;base64,..." }`
- Response: `{ "base_resp": { "status_code": 0 }, "content": "description" }`

#### `src/hearing.py` — `HearingAnalyzer`

- `describe_ambient(volume) -> str` — Maps volume float to Chinese description
- `analyze_volume_change(volumes) -> dict` — Peak detection via mean + 2*std
- `detect_sound_type(audio_data) -> str` — "silence" / "ambient" / "loud"

### 3.3 Memory Layer

#### `src/memory.py` — `Memory`

Dual-layer persistence:

**Layer 1: Observations** (`data/observations.json`)
- Append-only log of all observations
- Fields: `timestamp` (ISO), `modality` ("vision"/"hearing"), `content`, `importance` (1-5), `tags`
- Saved on every `add()` call (real-time persistence)
- Queryable by time range, modality, limit

**Layer 2: Keyframes** (`data/keyframes.json`)
- Important moments, auto-marked when `importance >= 4`
- Fields: `id`, `timestamp`, `modality`, `title`, `description`, `tags`, `auto` (bool)
- Searchable by keyword

Key data classes:
```python
@dataclass
class Observation:
    timestamp: str      # ISO format, Beijing timezone (UTC+8)
    modality: str       # "vision" or "hearing"
    content: str        # Description text
    raw_data: dict      # Optional
    importance: int     # 1-5
    tags: List[str]

@dataclass
class Keyframe:
    id: str             # UUID[:8]
    timestamp: str
    modality: str       # "vision" / "hearing" / "event"
    title: str
    description: str
    tags: List[str]
    auto: bool
```

### 3.4 Intelligence Layer

#### `src/analyzer.py` — `Analyzer`

The reasoning engine. Uses MiniMax-M2.5 chat API (Anthropic-compatible endpoint).

**Text API details:**
- Endpoint: `https://api.minimaxi.com/anthropic/v1/messages`
- Auth: `x-api-key: {MINIMAX_API_KEY}`, `anthropic-version: 2023-06-01`
- Model: `MiniMax-M2.5`
- Payload: Standard Anthropic messages format (`system`, `messages[]`)
- Response: Anthropic format (`content[].type=="text"` blocks; skip `type=="thinking"` blocks)

**Anomaly detection (`detect_anomalies`):**

| Check | Source | Trigger |
|-------|--------|---------|
| Scene change | vision observations | AI or keyword heuristic diff |
| Audio spike | volume_history | volume > mean + 3*std |
| Sudden silence | volume_history | active → silent transition |
| Novel scene | learner baseline | Keyword overlap < 50% |
| Unusual activity | learner histogram | Activity level < 10% frequency at this hour |

**Multimodal fusion (`fuse_observations`):**

Cross-modal pattern matching:

| Vision | Audio | Inference |
|--------|-------|-----------|
| Person visible | Quiet | Reading/working (normal) |
| No person | Loud noise | Suspicious — needs attention |
| Person visible | Active sound | Normal activity |

Also injects learner entity matching (e.g., "识别到: Seiya").

**Alert flow:**
1. `detect_anomalies()` returns anomaly list
2. `should_alert()` checks cooldown (default 60s)
3. `generate_alert()` uses AI for natural language summary (or concatenates descriptions)
4. `send_alert()` → Notifier (macOS notification + terminal)

#### `src/learner.py` — `Learner`

Personalized learning engine. Persists to `data/learner.json`.

**Three subsystems:**

1. **Scene Baseline** — Sliding window of last N (default 50) scene descriptions
   - `update_baseline(description)` — Feed new observation
   - `is_novel(description) -> bool` — Keyword overlap < `novelty_threshold` (0.5)
   - `get_baseline_summary() -> str` — Top keywords with frequency
   - `get_baseline_context() -> str` — Compact string for AI prompts

2. **Known Entities** — Name → description mapping
   - `learn_entity(name, description)` — Store
   - `match_entity(description) -> str|None` — Keyword matching (score >= 0.3)
   - `forget_entity(name)` — Remove
   - `get_entity_context() -> str` — For AI prompt injection

3. **Activity Patterns** — Hour-of-day histogram of activity levels
   - `record_activity(hour, level)` — Level: "quiet"/"normal"/"active"/"loud"
   - `is_unusual_activity(hour, level) -> bool` — < 10% frequency = unusual
   - `get_activity_summary() -> str` — Readable pattern dump

**Storage format (`data/learner.json`):**
```json
{
  "baseline": ["desc1", "desc2", ...],
  "entities": { "Seiya": "戴眼镜，黑头发，开发者" },
  "activity_histogram": {
    "14": { "normal": 25, "active": 3 },
    "3": { "quiet": 18 }
  }
}
```

#### `src/notifier.py` — `Notifier`

Dual-channel notification:
- **macOS Notification Center** — via `osascript`, for warning/alert levels
- **Terminal** — Colored output with icons, all levels
- Rate limiting: `min_interval` (default 5s), alerts bypass

### 3.5 Orchestration

#### `src/watcher.py` — `AmbientWatcher`

The main class. Initializes all components, manages threads, exposes public API.

**Component initialization order:**
1. `load_config()` → merged config dict
2. `VisionAnalyzer`, `HearingAnalyzer` — perception
3. `Memory` — persistence
4. `Notifier` — alerts
5. `Learner` — personalization (shares `data_dir` with Memory)
6. `Analyzer` — intelligence (receives memory, notifier, learner)

**Public interface:**
- `start()` / `stop()` — Lifecycle
- `get_status() -> dict` — Running state, memory stats, entity count
- `query(question) -> str` — Delegates to `Analyzer.answer_query()`
- `describe_now() -> str` — Current state from memory
- `get_memory_summary() -> str` — Statistics
- `learner` — Direct access to Learner instance (used by CLI)

**VLM cost optimization:**
- Change-triggered VLM: Only on >15% pixel diff (avoids API cost for static scenes)
- Continuous VLM: Every 120s, but skips if change-trigger already ran within 60s
- Text API (M2.5): Used freely for reasoning — much cheaper than VLM

### 3.6 CLI

#### `main.py`

| Command | Description | Example |
|---------|-------------|---------|
| `start` | Launch the watcher (blocks main thread) | `python main.py start -l DEBUG` |
| `status` | Show memory stats + summary | `python main.py status` |
| `query` | Ask a question about the environment | `python main.py query "有人在吗？"` |
| `learn` | Teach system about a known entity | `python main.py learn "这个人是Seiya"` |
| `baseline` | Show scene profile + entities + activity | `python main.py baseline` |
| `history` | Show recent observations with timestamps | `python main.py history -m 60 -n 50` |

All commands accept `--config / -c` for custom config path.

## 4. Configuration

Config is loaded from `config/default.json`, merged with `DEFAULT_SETTINGS` in `src/config.py`.
User config values override defaults. Nested dicts are shallow-merged.

```json
{
  "vision": {
    "enabled": true,
    "capture_interval": 5,
    "device_name": "0",
    "width": 1920, "height": 1080, "framerate": 30,
    "jpeg_quality": 5
  },
  "hearing": {
    "enabled": true,
    "sample_rate": 44100,
    "chunk_duration": 1,
    "silence_threshold": 0.01,
    "device_keyword": "MacBook"
  },
  "memory": {
    "duration_minutes": 15,
    "max_events": 1000,
    "data_dir": "data",
    "auto_keyframe_threshold": 4
  },
  "watcher": {
    "log_level": "INFO",
    "analysis_interval": 30,
    "anomaly_check_interval": 10,
    "continuous_vision_interval": 120
  },
  "analyzer": {
    "anomaly_cooldown": 60,
    "scene_change_threshold": 0.3,
    "volume_spike_threshold": 0.1
  },
  "notifier": {
    "macos_notification": true,
    "sound_on_alert": true,
    "min_interval": 5
  },
  "learner": {
    "baseline_window": 50,
    "novelty_threshold": 0.5
  }
}
```

### Key Configuration Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `vision.device_name` | str | "0" | avfoundation device index |
| `vision.capture_interval` | int | 5 | Seconds between captures |
| `vision.jpeg_quality` | int | 5 | ffmpeg mjpeg quality (2-31, lower=better) |
| `hearing.device_keyword` | str | "MacBook" | Substring match for mic selection |
| `hearing.silence_threshold` | float | 0.01 | Volume below this = silence |
| `memory.data_dir` | str | "data" | Persistence directory |
| `memory.auto_keyframe_threshold` | int | 4 | importance >= this → auto keyframe |
| `watcher.analysis_interval` | int | 30 | Seconds between status reports |
| `watcher.anomaly_check_interval` | int | 10 | Seconds between anomaly scans |
| `watcher.continuous_vision_interval` | int | 120 | Seconds between forced VLM calls |
| `analyzer.anomaly_cooldown` | int | 60 | Min seconds between alerts |
| `analyzer.scene_change_threshold` | float | 0.3 | Scene diff threshold (0-1) |
| `analyzer.volume_spike_threshold` | float | 0.1 | Audio spike threshold |
| `learner.baseline_window` | int | 50 | Scene descriptions kept for baseline |
| `learner.novelty_threshold` | float | 0.5 | Keyword overlap below this = novel |

## 5. External APIs

| API | Endpoint | Auth | Purpose |
|-----|----------|------|---------|
| MiniMax VLM | `https://api.minimaxi.com/v1/coding_plan/vlm` | Bearer token | Image understanding |
| MiniMax M2.5 | `https://api.minimaxi.com/anthropic/v1/messages` | x-api-key header | Text reasoning (Anthropic-compat) |

Both APIs use `MINIMAX_API_KEY` environment variable. System degrades gracefully
without API key — falls back to OpenCV for vision, keyword heuristics for reasoning.

## 6. Directory Structure

```
ambient-watcher/
├── src/
│   ├── __init__.py
│   ├── camera.py              # ffmpeg capture + hardware control integration
│   ├── mac_camera_control.py  # AVFoundation native hardware control
│   ├── microphone.py          # PyAudio mic (polling mode)
│   ├── microphone_debug.py    # Mic debugging utility
│   ├── config.py              # Config loading/merging
│   ├── vision.py              # VLM API + OpenCV fallback
│   ├── hearing.py             # Audio analysis + volume description
│   ├── memory.py              # Dual-layer memory (observations + keyframes)
│   ├── analyzer.py            # AI reasoning + multimodal fusion
│   ├── learner.py             # Personalized learning (baseline/entities/activity)
│   ├── watcher.py             # Main orchestrator (thread management)
│   └── notifier.py            # macOS + terminal notifications
├── config/
│   └── default.json           # Default configuration
├── data/                      # Runtime data (gitignored)
│   ├── observations.json      # Append-only observation log
│   ├── keyframes.json         # Important moments
│   └── learner.json           # Learned patterns, entities, activity
├── camera_debug.py            # Live debug panel (http://localhost:8765)
├── diagnose.py                # Device diagnostic script
├── main.py                    # CLI entry point
├── requirements.txt           # Python dependencies
└── README.md                  # User-facing documentation
```

## 7. Development Milestones

### Phase 1: Basic Sensing [COMPLETE]
- [x] Camera capture (ffmpeg avfoundation)
- [x] Hardware-level wide-angle control (AVFoundation zoom + Center Stage)
- [x] Microphone recording (PyAudio polling)
- [x] Device filtering (auto-exclude iPhone/iPad)
- [x] Basic image understanding (OpenCV)
- [x] Dual-layer memory system
- [x] Live debug panel (camera_debug.py)
- [x] Device diagnostic tool (diagnose.py)

### Phase 2: Intelligent Analysis [COMPLETE]
- [x] Anomaly detection (visual scene change + audio spikes)
- [x] Proactive alerting (macOS notifications + colored terminal)
- [x] Status reports (AI summary + periodic generation)
- [x] MiniMax API integration (Anthropic-compat endpoint, MiniMax-M2.5)
- [x] CLI entry point (main.py: start/status/query)

### Phase 3: Advanced Features [COMPLETE]
- [x] Continuous observation mode (periodic VLM, independent of scene change)
- [x] Personalized learning (scene baseline, entity memory, activity patterns)
- [x] Multimodal fusion (vision + audio cross-modal reasoning)
- [x] CLI: learn / baseline / history commands

### Phase 4: Future Ideas
- [ ] Voice interaction (wake word + speech-to-text)
- [ ] Web dashboard (real-time status, history browser)
- [ ] Multi-room support (multiple camera/mic sources)
- [ ] LLM-powered natural language control ("只在晚上10点后提醒我")

## 8. Design Principles

1. **No raw data storage** — Only analyzed "information" is persisted, never raw images/audio
2. **Local-first** — Sensitive content stays on device; API calls send only base64 images
3. **User control** — Start/stop anytime; all features configurable
4. **Transparent** — User can see exactly what the system observes (`status`, `history`)
5. **Graceful degradation** — Works without API key (OpenCV + heuristics)
6. **VLM cost awareness** — VLM only on change or timed interval; text API used freely

---

*Built with claude-internal — Yiyang's midnight AI*
