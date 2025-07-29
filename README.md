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

### List Scenes
```bash
# List all available scenes with descriptions  
python cli.py list-scenes scene_prompts.json

💡 This shows scene IDs and descriptions to help you choose which ones to generate
```

### Generate
```bash
# Generate all clips (with automatic optimization)
python cli.py generate scene_prompts.json --output-dir ./clips/

# Use fast model for 46% cost savings
python cli.py generate scene_prompts.json --output-dir ./clips/ --fast

# Generate specific scenes by ID
python cli.py generate scene_prompts.json --scenes "scene_01,scene_05,scene_10"

# Dry run (preview what would be generated)
python cli.py generate scene_prompts.json --dry-run

# Limit to first 5 scenes
python cli.py generate scene_prompts.json --max-scenes 5

# Generate specific scenes with custom output directory
python cli.py generate scene_prompts.json --scenes "scene_03,scene_07" --output-dir ./custom_clips/
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
- `--fast` - Use Veo3 Fast model for 46% cost savings

## 💰 Cost Optimization & Estimation

The tool automatically optimizes costs through smart scene combining and provides accurate pricing:

### Automatic Cost Optimization
- **Scene Combining:** Groups short scenes (<7.5s) into single 8s clips
- **Smart Chunking:** Splits long scenes (>8s) into manageable pieces  
- **Auto-Splitting:** Extracts individual scenes from combined clips
- **Typical Savings:** 70-80% cost reduction for videos with many short scenes

### Accurate Pricing (2025)
- **Veo3 Standard:** $0.75/second with audio
- **Veo3 Fast:** $0.40/second with audio (46% cheaper)
- **Claude Analysis:** ~$0.003/1K tokens (very cheap)

Example output:
```
📊 Analysis Estimate:
Scenes detected: 15
Video clips to generate: 8 (optimized from 15)
Total clip duration: 64.0s (8s per clip)
Claude analysis cost: $0.036 (12,000 tokens)
Veo3 Standard cost: $48.00 ($0.75/second)
Veo3 Fast cost: $25.60 ($0.40/second)
Total (Standard): $48.04
Total (Fast): $25.64
💡 Tip: Use --fast flag in generation to save $22.40!

🎯 Optimizing scene combinations...
   Combined 3 scenes: scene_01, scene_02, scene_05 → combined_01_02_05 (5.7s)
   Combined 2 scenes: scene_06, scene_07 → combined_06_07 (4.0s)
   Original: 15 clips → Optimized: 8 clips
   Estimated savings: $52.50
```

## 🎯 Scene Selection & Analysis

### Selecting Specific Scenes

After running analysis, you can choose which scenes to generate:

1. **List all scenes** to see what's available:
   ```bash
   python cli.py list-scenes scene_prompts.json
   ```

2. **Select specific scenes** by their IDs:
   ```bash
   # Generate just the scenes you want
   python cli.py generate scene_prompts.json --scenes "scene_01,scene_05,scene_10"
   
   # Preview what would be generated
   python cli.py generate scene_prompts.json --scenes "scene_01,scene_05" --dry-run
   ```

3. **Alternative selection methods**:
   ```bash
   # First N scenes
   python cli.py generate scene_prompts.json --max-scenes 3
   
   # All scenes (default)
   python cli.py generate scene_prompts.json
   ```

### Scene Analysis Details

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

## ⚠️ Limitations & How We Handle Them

- **Scene duration:** Veo3 clips are fixed at 8 seconds
  - ✅ **Solution:** Auto-chunking for long scenes + stitching
  - ✅ **Solution:** Scene combining for short scenes + splitting
- **Video length:** Works best with videos under 5 minutes
- **File formats:** Outputs MP4 only
- **Quality:** Generated clips at 720p resolution (720p/1080p available)

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

## 🎯 Selective Scene Generation Examples

### Example 1: Preview and Select Best Scenes
```bash
# After analysis, browse all scenes
python cli.py list-scenes scene_prompts.json

# Preview specific interesting scenes
python cli.py generate scene_prompts.json --scenes "scene_03,scene_10,scene_15" --dry-run

# Generate only the best ones
python cli.py generate scene_prompts.json --scenes "scene_03,scene_10"
```

### Example 2: Generate Scenes by Content Type
```bash
# Looking at the scene list output, select by content:
# Character scenes: scene_03, scene_07, scene_18
python cli.py generate scene_prompts.json --scenes "scene_03,scene_07,scene_18"

# Action scenes: scene_06, scene_10  
python cli.py generate scene_prompts.json --scenes "scene_06,scene_10"

# Logo/branding: scene_19
python cli.py generate scene_prompts.json --scenes "scene_19"
```

### Example 3: Iterative Generation
```bash
# Start with just one scene to test quality
python cli.py generate scene_prompts.json --scenes "scene_01"

# Review the result, then generate more
python cli.py generate scene_prompts.json --scenes "scene_05,scene_07" 

# Add final scenes after reviewing
python cli.py generate scene_prompts.json --scenes "scene_12,scene_19"

# Stitch all generated clips
python cli.py stitch ./clips/ --output final_video.mp4
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