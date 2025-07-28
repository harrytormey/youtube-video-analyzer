# 🎬 YouTube-to-Veo3 Scene Translator CLI - Specification

## ✅ Overview

A CLI tool that:

1. Downloads a YouTube video or accepts a local file
2. Detects scenes using FFmpeg and analyzes them with Claude Code
3. Generates a detailed, prompt-friendly description of each scene for Veo3
4. Outputs prompts (with diagnostics) in an editable format
5. Supports prompt-to-video generation via Veo3 on fal.ai, with stitchable outputs
6. Tracks costs, supports dry runs, and caches generation results for reuse

## ⚙️ Command Structure

```bash
python cli.py download --url <youtube_url> --output input.mp4

python cli.py analyze --video input.mp4 --output scene_prompts.json --estimate-only

python cli.py generate --prompts scene_prompts.json --output-dir ./clips/

python cli.py stitch --inputs ./clips/*.mp4 --output final_video.mp4
```

## 📦 Dependencies

- `typer` - CLI framework
- `ffmpeg-python` - Scene detection and video manipulation
- `pytube` - YouTube download support
- `anthropic` - Claude Code SDK (Anthropic preferred)
- `python-dotenv` - For API key management
- `requests` - HTTP API interaction with fal.ai
- `uuid` - Clip ID generation

## 📁 File Structure

```
yt-veo3-cli/
├── cli.py                  # CLI entry point
├── download.py             # YouTube/local file handling
├── analyze.py              # FFmpeg scene detection + Claude Code
├── generate.py             # Veo3 prompt -> clip generation
├── stitch.py               # FFmpeg clip stitching
├── prompts/                # JSON or Markdown prompt files
├── clips/                  # Individual clip videos
├── cache/                  # Previously generated clips
├── requirements.txt
└── .env / .env.example     # FAL_API_KEY, CLAUDE_API_KEY
```

## 🎥 1. Downloading (download command)

**Function:** Downloads a YouTube video and transcribes it if needed.

**Key Features:**
- Supports YouTube links via `pytube`
- Optional `--input-file` flag for local video
- Warns and exits if duration > 2 minutes
- Saves video as `.mp4`

## 🎬 2. Scene Analysis & Prompt Generation (analyze command)

### Scene Detection:
- Uses FFmpeg scene thresholding (`ffmpeg -vf "select='gt(scene,0.4)',showinfo"`)
- Segments video into clips (~1–5 seconds typical)

### Claude Analysis:
- Claude Code analyzes each scene using screenshot & audio (if present)
- Uses deterministic prompt structure to generate:
  - Natural language prompt (action, mood, style)
  - Metadata (duration, hard-to-generate flags, diagnostics)

### Example Prompt Block (JSON):

```json
{
  "id": "scene_01",
  "start_time": "00:00:00.0",
  "end_time": "00:00:05.0",
  "description": "A man walks into a neon-lit alley, rain falling...",
  "prompt": "Generate a 5-second cinematic shot of a man walking into a neon-lit alley...",
  "diagnostics": {
    "text_heavy": false,
    "camera_motion": true,
    "complex_characters": false
  }
}
```

### Other Features:
- Adds timestamps
- Warns if token budget per scene > 1k
- Displays token and cost estimate (based on Claude SDK)
- Supports `--estimate-only` dry run
- Optionally saves Markdown version (if user prefers)

## 💸 Prompt Diagnostics

Each scene is checked for:
- Long or complex dialog
- Rapid motion / high cut rate
- Large character sets
- Excessive text overlay (from OCR if feasible)
- Long duration (warning if > 8s)

**Future Fix Strategy:**
Tool might suggest overlaying green screen blocks for later substitution — deferred for now.

## 🧠 Prompt File Structure

A JSON file with:
- Ordered list of scenes
- For each: ID, duration, start, description, diagnostics, Veo3 prompt
- Format: JSON (`scene_prompts.json`), optional `.md` export

## 🛠️ 3. Veo3 Generation (generate command)

**Function:** Uses fal.ai to generate a clip for each prompt.

**Key Details:**
- Uses `fal.run/fal-ai/veo3` endpoint
- Sends prompt and clip duration
- Duration must not exceed 8s
- Automatically skips previously generated clips (based on scene ID)
- Outputs video clip to `clips/scene_xx.mp4`
- Tracks estimated and actual credit usage via fal.ai responses
- Errors reported with clarity (e.g., prompt too long)

## 🔁 4. Clip Stitching (stitch command)

**Function:** Concatenates the generated clips into a final `.mp4`.

**Uses:**
- FFmpeg concat filter with timestamp and stream reindexing
- Outputs `final_video.mp4`
- Adds optional intro/outro via CLI flags (future)

## 🔐 API Integration

### .env Variables:
```
FAL_API_KEY=...
CLAUDE_API_KEY=...
```

### Authentication:
- fal.ai: `Authorization: Key {FAL_API_KEY}`
- Claude: via `anthropic` Python SDK or HTTP + streaming

## 📈 Cost Estimation & Caching

- Scene cost: estimated by token count in Claude prompts
- Video cost: estimated via Veo3 API usage guide
- Shows total estimate and per-scene breakdown
- Scene prompts saved and hashed for reuse
- Previously generated clips not re-requested

## 🛑 Warnings & Exit Criteria

- Exits if input video is > 2 minutes
- Exits if any scene exceeds 8s or generates 1000+ Claude tokens
- Shows summary report: scene count, token estimate, time range

## ✅ Future Feature Ideas (Backlogged)

- `--interactive` CLI mode to edit prompts in-place
- Color-overlay strategies for text prompts
- Claude vision model support (to analyze frames)
- Drag-and-drop GUI via Gradio

## 🧪 Example Workflow

```bash
# Step 1: Download from YouTube
python cli.py download --url "https://youtu.be/abc123"

# Step 2: Analyze and get prompts
python cli.py analyze --video input.mp4 --output scene_prompts.json

# Step 3: Dry run estimate
python cli.py analyze --video input.mp4 --output scene_prompts.json --estimate-only

# Step 4: Generate clips
python cli.py generate --prompts scene_prompts.json --output-dir ./clips/

# Step 5: Stitch clips into one
python cli.py stitch --inputs ./clips/*.mp4 --output final_video.mp4
```

## 🔧 Implementation Notes for Claude Code

### Key Technical Considerations:

1. **FFmpeg Integration**: Scene detection requires careful handling of FFmpeg output parsing and timestamp extraction
2. **Claude Vision API**: Will need to extract frames from video segments for visual analysis
3. **Error Handling**: Robust error handling for API failures, invalid video formats, and network issues
4. **Rate Limiting**: Implement proper rate limiting for both Claude and fal.ai API calls
5. **Caching Strategy**: Hash-based caching for both scene analysis and generated clips
6. **File Management**: Proper cleanup and organization of temporary files and outputs
7. **Progress Tracking**: CLI progress bars for long-running operations (download, analysis, generation)
8. **Configuration Management**: Flexible configuration system for API keys and default settings

### Security Considerations:

- API key validation and secure storage
- Input sanitization for YouTube URLs and file paths
- Proper handling of temporary files and cleanup
- Rate limiting to prevent API abuse

### Performance Optimizations:

- Parallel processing for scene analysis where possible
- Efficient video segment extraction
- Memory management for large video files
- Incremental processing with resume capability