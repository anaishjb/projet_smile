# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SMILE (Social Memory Integrated Learning Environment) is a conversational AI system for social robotics. It combines real-time face recognition (MTCNN + FaceNet), offline French speech-to-text (Vosk), local LLM inference (Ollama/llama3:8b), and persistent per-user memory to enable personalized interactions. The system runs entirely locally (no cloud dependencies) and converses in French.

## Setup

```bash
python -m venv facenet
facenet\Scripts\activate          # Windows
pip install --upgrade pip
pip install -r requirements.txt
copy src\config_example.py src\config.py   # then edit paths inside
```

**`src/config.py` is gitignored** — you must create it from `config_example.py`. Note: `config_example.py` uses `EMBEDDINGS_PATH` but the actual codebase imports `EMBEDDINGS_FILE`; rename accordingly when copying.

**Python 3.13 extra dependencies** (not in requirements.txt, install manually):
```bash
pip install audioop-lts comtypes cffi
```

**PyTorch CPU-only** (if no CUDA GPU):
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

**External dependencies (not in repo):**
- Ollama: `ollama pull llama3:8b`
- Vosk French model: `vosk-model-fr-0.22` (~1.4 Go) or `vosk-model-small-fr-0.22` (~40 Mo) from `https://alphacephei.com/vosk/models` — set `VOSK_MODEL_PATH` in `config.py`. The installed model may be nested one extra level (`vosk-model-fr-0.22/vosk-model-fr-0.22/`) — set the path to the inner folder.

## Running

Two terminals are required:

```bash
# Terminal 1 — start Ollama (must be running before SMILE)
ollama serve

# Terminal 2 — run SMILE
facenet\Scripts\activate
python -m src.recognize_live       # press Q to quit
```

Or use the convenience script (activates venv + launches):
```powershell
.\start.ps1
```

No build step, no test suite, no linter configured.

**Windows-only:** the Q-key listener uses `msvcrt`, not available on Linux/Mac.

## Architecture

The system is built around a multi-threaded pipeline. All threads share global queues and events defined in `src/utils/async_core.py`.

**Perception pipeline** (`src/utils/async_core.py`):
- `detection_worker` — MTCNN face detection, consumes `detect_request_q`, outputs to `detect_result_q`; filters results to min 80×80px, confidence >0.9
- `embedding_worker` — InceptionResnetV1 embedding (512-float), consumes `embed_request_q`, outputs to `embed_result_q`; adds 10px margin around face crop before normalizing to 160×160
- Both workers perform GPU warm-up on startup (`worker_ready_event` / `embedding_ready_event`)
- `_tts_executor` and `_ollama_executor` — single-worker `ThreadPoolExecutor`s for async TTS and LLM calls
- `embed_semaphore` prevents concurrent embedding; `exit_event` (Q key) signals global shutdown

**Main loop** (`src/recognize_live.py`):
- Reads detection/embedding results from queues and maintains per-face CSRT trackers
- Matches trackers via IoU; re-embedding throttled by `EMBED_INTERVAL` per tracker
- Per-recognized-person state machine: `GREETING → FREE_TALK → FAREWELL`
- Spawns `handle_interaction_threadsafe()` in a thread, guarded by `conversation_lock` (one conversation at a time)
- After 5 consecutive silent STT responses (`max_silence_rounds`), ends the conversation

**Dialogue layer** (`src/utils/dialog_manager.py`):
- `build_llm_prompt()` — assembles system prompt from profile fields + `notes_summary` + last **7** conversation turns + current input; prompt instructions differ per state
- `summarize_conversation()` — end-of-session Ollama call over the last **10** turns that extracts/infers age, gender, occupation, interests, personality, goals and merges them back into the profile JSON (only empty fields are overwritten; list fields are merged without duplicates)

**Memory layer**:
- `profile_manager.py` — `data/profiles/<name>.json` with fields: `name`, `known_since`, `age`, `gender`, `occupation`, `interests`, `personality`, `goals`, `notes_summary`, `recent_conversations`, `last_update`
- `memory_manager.py` — appends turns to `data/conversations/<name>.json`; persists new face embeddings to `data/embeddings.pkl` (`{name: np.array(512,)}`)
- `facenet_utils.py` — `compare_embeddings()` computes cosine distance; `SIMILARITY_THRESHOLD = 0.7` means a match requires `distance < 0.3`

**Speech** (`src/utils/speech_utils.py`):
- STT: Vosk (French), `find_working_mic()` auto-detects a working mic by trying rates [16000, 48000] and channels [1, 2]
- TTS: pyttsx3 via `_tts_executor` to stay non-blocking (rate=160, volume=1.0)
- `extract_name_from_text()` — regex-based name extraction; falls back to first non-blacklisted word, then `Utilisateur_{timestamp}`

**Post-processing** (`src/utils/text_post.py`):
- `clean_llm_reply(raw, state, is_first_turn)` — strips leading "Bonjour"/"Salut" on non-first turns, removes sentences ending with `?` during FAREWELL, removes repeated consecutive phrases

## Configuration (`src/config.py`)

```python
BASE_DIR            # absolute path to project root
VOSK_MODEL_PATH     # absolute path to vosk-model-fr-0.22 (inner folder if nested)
OLLAMA_URL          # http://localhost:11434/api/generate
MODEL_NAME          # "llama3:8b"
MIC_INDEX           # set to your mic device index (e.g. 20 for FrontMic on this machine)
MIC_SAMPLE_RATE     # 48000 (hardware-dependent; speech_utils also tries 16000)
SILENCE_LIMIT       # 3.2 s of silence before STT stops
SILENCE_HANGOVER    # 2.5 s hangover after speech detected
SPEECH_MAX_DURATION # 20 s max recording time
VOICE_RATE          # 160 (TTS speech rate)
VOICE_VOLUME        # 1.0
DEFAULT_VOICE_INDEX # 0
DEBUG_MODE          # False — enable for verbose logging
```

**Known audio issue:** some mic indices raise `[Errno -9999] Unanticipated host error`. Use `MIC_INDEX = 20` (FrontMic - Realtek HD Audio) as baseline, or find valid indices:
```bash
facenet\Scripts\python.exe -c "import pyaudio; p=pyaudio.PyAudio(); [print(i, p.get_device_info_by_index(i)['name']) for i in range(p.get_device_count())]"
```

**Webcam inaccessible:** `can't grab frame (-1072875772)` means the camera is in use by another app (Teams, browser, OBS). Close those apps first.

**Test TTS independently:**
```bash
facenet\Scripts\python.exe -c "import pyttsx3; e=pyttsx3.init(); e.say('Bonjour, je suis SMILE'); e.runAndWait()"
```

## Key Tuning Constants (`src/recognize_live.py`)

| Constant | Default | Effect |
|---|---|---|
| `TRACKER_MAX_LOST` | 15 | Frames before a tracker is dropped |
| `EMBED_INTERVAL` | 20.0 | Seconds between re-embeddings of same face |
| `RESEEN_THRESHOLD` | 30 | Seconds before re-greeting the same person |
| `IOU_THRESHOLD` | 0.3 | Face box overlap for tracker matching |
| `max_silence_rounds` | 5 | Consecutive empty STT results before ending conversation |

MTCNN is initialized with stricter thresholds than default (`[0.6, 0.7, 0.8]` vs `[0.5, 0.6, 0.7]`) and `min_face_size=60` to reduce false detections.

## Data Layout

```
data/
  embeddings.pkl             # {name: np.array(512,)} face database
  profiles/<name>.json       # per-user profile + episodic notes_summary
  conversations/<name>.json  # full turn-by-turn conversation log
```

`data/` is gitignored. `notes_summary` accumulates long-term episodic memory across sessions via end-of-conversation LLM summarization.

## Unused Dependencies

`deepface`, `tensorflow`, `keras`, `flask`, and `flask-cors` are in `requirements.txt` but not used in the current codebase. They are legacy remnants and can be ignored.
