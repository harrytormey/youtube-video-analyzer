# 🎬 YouTube-to-Veo3 Scene Translator CLI

A powerful CLI tool that downloads YouTube videos, detects scenes using FFmpeg, analyzes them with Claude, and generates new video clips using Veo3 via fal.ai.

## ✨ Features

- 📥 **Download YouTube videos** or process local video files
- 🎬 **Automatic scene detection** using FFmpeg with configurable threshold
- 🤖 **AI-powered scene analysis** with Claude for generating Veo3-optimized prompts  
- 🎥 **Video generation** via Veo3 on fal.ai platform
- 🔗 **Smart video stitching** with multiple methods (concat/filter)
- 💰 **Cost estimation** and tracking for API usage
- 📊 **Progress tracking** with detailed logs and reports
- 🔄 **Resume capability** - skip existing clips and cache results

## 🚀 Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Setup environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys:
   # FAL_API_KEY=your_fal_api_key
   # ANTHROPIC_API_KEY=your_anthropic_api_key
   ```

3. **Check setup:**
   ```bash
   python cli.py setup
   ```

4. **Run complete workflow:**
   ```bash
   python cli.py workflow --url "https://youtu.be/your_video_id"
   ```

## 📋 Commands

### Download
```bash
# Download from YouTube
python cli.py download --url "https://youtu.be/abc123"

# Use local file
python cli.py download --input-file "my_video.mp4" --output "input.mp4"
```

### Analyze
```bash
# Analyze scenes and generate prompts
python cli.py analyze input.mp4 --output scene_prompts.json

# Just show cost estimate
python cli.py analyze input.mp4 --estimate-only

# Save markdown report too
python cli.py analyze input.mp4 --markdown
```

### Generate
```bash
# Generate all clips
python cli.py generate scene_prompts.json --output-dir ./clips/

# Dry run (preview what would be generated)
python cli.py generate scene_prompts.json --dry-run

# Limit to first 5 scenes
python cli.py generate scene_prompts.json --max-scenes 5
```

### Stitch
```bash
# Stitch all clips in directory
python cli.py stitch ./clips/ --output final_video.mp4

# Use glob pattern
python cli.py stitch "./clips/*.mp4" --output final_video.mp4

# Add intro and outro
python cli.py stitch ./clips/ --intro intro.mp4 --outro outro.mp4
```

### Workflow (All-in-One)
```bash
# Complete workflow from YouTube URL
python cli.py workflow --url "https://youtu.be/abc123"

# With custom settings
python cli.py workflow --url "https://youtu.be/abc123" \
  --threshold 0.3 \
  --max-scenes 10 \
  --output-dir ./my_project/
```

## 📁 Project Structure

```
yt-veo3-cli/
├── cli.py                  # Main CLI interface
├── download.py             # YouTube/local file handling  
├── analyze.py              # Scene detection + Claude analysis
├── generate.py             # Veo3 generation via fal.ai
├── stitch.py               # Video concatenation
├── requirements.txt        # Python dependencies
├── .env.example           # Environment template
├── prompts/               # Generated prompt files
├── clips/                 # Individual generated clips
├── cache/                 # Cached results
└── output/                # Workflow outputs
```

## ⚙️ Configuration

### Environment Variables
- `FAL_API_KEY` - Your fal.ai API key for Veo3 generation
- `ANTHROPIC_API_KEY` - Your Anthropic API key for Claude analysis

### Scene Detection Settings
- `--threshold` (0.0-1.0) - Scene change sensitivity (default: 0.4)
  - Higher = fewer, longer scenes
  - Lower = more, shorter scenes

### Generation Settings
- `--skip-existing` - Skip clips that already exist (default: true)
- `--max-scenes` - Limit number of scenes to process
- `--dry-run` - Preview without actually generating

## 💰 Cost Estimation

The tool provides detailed cost estimates before processing:

- **Claude costs:** Based on token usage for scene analysis
- **Veo3 costs:** Estimated per-second generation pricing
- **Total duration:** Sum of all scene durations
- **Scene count:** Number of detected scenes

Example output:
```
📊 Analysis Estimate:
Scenes detected: 12
Total duration: 45.3s
Estimated Claude tokens: 9,600
Estimated Claude cost: $0.029
Estimated Veo3 cost: $4.53
Total estimated cost: $4.56
```

## 🎯 Scene Analysis

Claude analyzes each scene and provides:

1. **Description:** Natural language description of scene content
2. **Veo3 Prompt:** Optimized prompt for video generation
3. **Diagnostics:** Flags for potential generation challenges:
   - `text_heavy` - Scene contains lots of text
   - `camera_motion` - Significant camera movement
   - `complex_characters` - Multiple or complex characters
   - `rapid_motion` - Fast-paced action
   - `duration_warning` - Scene exceeds 8-second limit

## 🔧 Advanced Usage

### Custom Thresholds
```bash
# Detect more scenes (lower threshold)
python cli.py analyze input.mp4 --threshold 0.2

# Detect fewer scenes (higher threshold)  
python cli.py analyze input.mp4 --threshold 0.6
```

### Batch Processing
```bash
# Process multiple videos
for video in *.mp4; do
  python cli.py workflow --input-file "$video" --output-dir "./output/$video/"
done
```

### Resume Failed Generations
```bash
# Skip existing clips and continue from where you left off
python cli.py generate scene_prompts.json --skip-existing
```

## ⚠️ Limitations

- **Video length:** Maximum 2 minutes (120 seconds)
- **Scene duration:** Veo3 clips capped at 8 seconds
- **File formats:** Outputs MP4 only
- **Quality:** Generated clips at 720p resolution

## 🐛 Troubleshooting

### Common Issues

1. **FFmpeg not found:**
   ```bash
   # Install FFmpeg first
   # macOS: brew install ffmpeg
   # Ubuntu: sudo apt install ffmpeg
   # Windows: Download from https://ffmpeg.org
   ```

2. **API key errors:**
   ```bash
   # Check your .env file
   python cli.py setup
   ```

3. **Scene detection issues:**
   ```bash
   # Try different threshold
   python cli.py analyze input.mp4 --threshold 0.3
   ```

4. **Generation failures:**
   ```bash
   # Check logs in clips/generation_log.json
   # Retry with --overwrite to regenerate failed clips
   ```

### Debug Mode
```bash
# Add verbose output for debugging
export DEBUG=1
python cli.py workflow --url "https://youtu.be/abc123"
```

## 🤝 Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- [FFmpeg](https://ffmpeg.org/) - Video processing
- [Anthropic Claude](https://anthropic.com/) - Scene analysis
- [fal.ai](https://fal.ai/) - Veo3 video generation
- [Typer](https://typer.tiangolo.com/) - CLI framework

---

**⚡ Pro Tip:** Use the `workflow` command for end-to-end processing, or run individual commands for more control over each step!