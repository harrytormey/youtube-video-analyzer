#!/usr/bin/env python3

"""
🎬 YouTube-to-Veo3 Scene Translator CLI

A CLI tool that downloads YouTube videos, detects scenes, generates Veo3 prompts
using Claude, and creates video clips via fal.ai.

Usage:
    python cli.py download --url "https://youtu.be/abc123"
    python cli.py analyze --video input.mp4 --output scene_prompts.json
    python cli.py generate --prompts scene_prompts.json --output-dir ./clips/
    python cli.py stitch --inputs "./clips/*.mp4" --output final_video.mp4
"""

import sys
import os
from pathlib import Path

import typer
from typing import Optional

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from download import download_command
from analyze import analyze_command  
from generate import generate_command
from stitch import stitch_command

# Create the main CLI app
app = typer.Typer(
    name="yt-veo3-cli",
    help="🎬 YouTube-to-Veo3 Scene Translator CLI",
    epilog="For more information, see: https://github.com/yourusername/yt-veo3-cli",
    no_args_is_help=True
)

@app.command("download")
def download(
    url: Optional[str] = typer.Option(None, "--url", help="YouTube URL to download"),
    input_file: Optional[str] = typer.Option(None, "--input-file", help="Local video file to use"),
    output: str = typer.Option("input.mp4", "--output", help="Output MP4 file path")
):
    """📥 Download YouTube video or process local video file."""
    download_command(url=url, input_file=input_file, output=output)

@app.command("analyze") 
def analyze(
    video: str = typer.Argument(..., help="Input video file"),
    output: str = typer.Option("scene_prompts.json", "--output", help="Output JSON file"),
    threshold: float = typer.Option(0.4, "--threshold", help="Scene detection threshold (0.0-1.0)"),
    estimate_only: bool = typer.Option(False, "--estimate-only", help="Only show cost estimate"),
    markdown: bool = typer.Option(False, "--markdown", help="Also save as markdown")
):
    """🎬 Analyze video scenes and generate Veo3 prompts using Claude."""
    analyze_command(video=video, output=output, threshold=threshold, estimate_only=estimate_only, markdown=markdown)

@app.command("generate")
def generate(
    prompts: str = typer.Argument(..., help="JSON file with scene prompts"),
    output_dir: str = typer.Option("./clips/", "--output-dir", help="Output directory for clips"),
    skip_existing: bool = typer.Option(True, "--skip-existing/--overwrite", help="Skip existing clips"),
    max_scenes: Optional[int] = typer.Option(None, "--max-scenes", help="Limit number of scenes to generate"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be generated without actually doing it")
):
    """🎥 Generate video clips from scene prompts using Veo3 via fal.ai."""
    generate_command(prompts=prompts, output_dir=output_dir, skip_existing=skip_existing, max_scenes=max_scenes, dry_run=dry_run)

@app.command("stitch")
def stitch(
    inputs: str = typer.Argument(..., help="Input pattern (e.g., './clips/*.mp4') or directory"),
    output: str = typer.Option("final_video.mp4", "--output", help="Output video file"),
    intro: Optional[str] = typer.Option(None, "--intro", help="Intro video file"),
    outro: Optional[str] = typer.Option(None, "--outro", help="Outro video file"),
    method: str = typer.Option("auto", "--method", help="Stitching method: auto, concat, filter"),
    sort: bool = typer.Option(True, "--sort/--no-sort", help="Sort files naturally")
):
    """🔗 Stitch video clips into a single video."""
    stitch_command(inputs=inputs, output=output, intro=intro, outro=outro, method=method, sort=sort)

@app.command("workflow")
def workflow(
    url: Optional[str] = typer.Option(None, "--url", help="YouTube URL to download"),
    input_file: Optional[str] = typer.Option(None, "--input-file", help="Local video file to use"),
    threshold: float = typer.Option(0.4, "--threshold", help="Scene detection threshold"),
    max_scenes: Optional[int] = typer.Option(None, "--max-scenes", help="Limit number of scenes"),
    output_dir: str = typer.Option("./output/", "--output-dir", help="Base output directory"),
    skip_existing: bool = typer.Option(True, "--skip-existing/--overwrite", help="Skip existing files"),
    estimate_only: bool = typer.Option(False, "--estimate-only", help="Only show cost estimates")
):
    """🚀 Run complete workflow: download → analyze → generate → stitch."""
    
    # Create output directory structure
    os.makedirs(output_dir, exist_ok=True)
    clips_dir = os.path.join(output_dir, "clips")
    os.makedirs(clips_dir, exist_ok=True)
    
    # Step 1: Download
    video_path = os.path.join(output_dir, "input.mp4")
    typer.echo("📥 Step 1: Downloading video...")
    
    if not skip_existing or not os.path.exists(video_path):
        download_command(url=url, input_file=input_file, output=video_path)
    else:
        typer.echo(f"✅ Using existing video: {video_path}")
    
    # Step 2: Analyze
    prompts_path = os.path.join(output_dir, "scene_prompts.json")
    typer.echo("\n🎬 Step 2: Analyzing scenes...")
    
    if not skip_existing or not os.path.exists(prompts_path):
        analyze_command(video=video_path, output=prompts_path, threshold=threshold, estimate_only=estimate_only, markdown=True)
    else:
        typer.echo(f"✅ Using existing analysis: {prompts_path}")
    
    if estimate_only:
        typer.echo("🔍 Workflow stopped at estimation phase")
        return
    
    # Step 3: Generate
    typer.echo("\n🎥 Step 3: Generating clips...")
    generate_command(prompts=prompts_path, output_dir=clips_dir, skip_existing=skip_existing, max_scenes=max_scenes, dry_run=False)
    
    # Step 4: Stitch
    final_output = os.path.join(output_dir, "final_video.mp4")
    typer.echo(f"\n🔗 Step 4: Stitching clips...")
    stitch_command(inputs=clips_dir, output=final_output, sort=True)
    
    typer.echo(f"\n🎉 Workflow complete! Final video: {final_output}")

@app.command("version")
def version():
    """Show version information."""
    typer.echo("🎬 YouTube-to-Veo3 Scene Translator CLI v1.0.0")
    typer.echo("Built with ❤️  using Typer, FFmpeg, Claude, and fal.ai")

@app.command("setup")
def setup():
    """🔧 Setup assistant - check dependencies and configuration."""
    typer.echo("🔧 Checking setup...")
    
    issues = []
    
    # Check Python packages
    try:
        import ffmpeg
        typer.echo("✅ ffmpeg-python installed")
    except ImportError:
        issues.append("ffmpeg-python not installed")
    
    try:
        import pytube
        typer.echo("✅ pytube installed")
    except ImportError:
        issues.append("pytube not installed")
    
    try:
        import anthropic
        typer.echo("✅ anthropic installed")
    except ImportError:
        issues.append("anthropic not installed")
    
    # Check FFmpeg binary
    try:
        import subprocess
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        if result.returncode == 0:
            typer.echo("✅ FFmpeg binary available")
        else:
            issues.append("FFmpeg binary not working")
    except FileNotFoundError:
        issues.append("FFmpeg binary not found in PATH")
    
    # Check environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    if os.getenv("ANTHROPIC_API_KEY"):
        typer.echo("✅ ANTHROPIC_API_KEY configured")
    else:
        issues.append("ANTHROPIC_API_KEY not set")
    
    if os.getenv("FAL_API_KEY"):
        typer.echo("✅ FAL_API_KEY configured")
    else:
        issues.append("FAL_API_KEY not set")
    
    # Check directories
    for dirname in ["prompts", "clips", "cache"]:
        if os.path.exists(dirname):
            typer.echo(f"✅ {dirname}/ directory exists")
        else:
            os.makedirs(dirname, exist_ok=True)
            typer.echo(f"📁 Created {dirname}/ directory")
    
    # Report issues
    if issues:
        typer.echo(f"\n❌ Found {len(issues)} issues:")
        for issue in issues:
            typer.echo(f"  - {issue}")
        
        typer.echo(f"\n💡 To fix:")
        typer.echo("1. Install dependencies: pip install -r requirements.txt")
        typer.echo("2. Install FFmpeg: https://ffmpeg.org/download.html")
        typer.echo("3. Copy .env.example to .env and add your API keys")
    else:
        typer.echo("\n🎉 Setup looks good! You're ready to use the CLI.")

if __name__ == "__main__":
    app()