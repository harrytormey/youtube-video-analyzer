#!/usr/bin/env python3

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional
import ffmpeg
from pytube import YouTube
from pytube.exceptions import VideoUnavailable, RegexMatchError
import typer

def get_video_duration(video_path: str) -> float:
    """Get video duration in seconds using ffmpeg."""
    try:
        probe = ffmpeg.probe(video_path)
        duration = float(probe['streams'][0]['duration'])
        return duration
    except Exception as e:
        typer.echo(f"Error getting video duration: {e}", err=True)
        return 0

def download_youtube_video(url: str, output_path: str) -> bool:
    """Download YouTube video and save to output_path."""
    try:
        typer.echo(f"Downloading video from: {url}")
        
        # Clean URL - remove tracking parameters
        clean_url = url.split('&')[0].split('?si=')[0]
        typer.echo(f"Using clean URL: {clean_url}")
        
        # Initialize YouTube object with additional options
        yt = YouTube(
            clean_url,
            use_oauth=False,
            allow_oauth_cache=True
        )
        
        typer.echo(f"Title: {yt.title}")
        typer.echo(f"Duration: {yt.length} seconds")
        
        # Check duration limit (2 minutes = 120 seconds)
        if yt.length > 120:
            typer.echo(f"Error: Video duration ({yt.length}s) exceeds 2 minute limit", err=True)
            return False
        
        typer.echo("Available streams:")
        streams = yt.streams.filter(file_extension='mp4')
        for i, stream in enumerate(streams):
            typer.echo(f"  {i+1}: {stream.resolution or 'audio'} - {stream.mime_type} - {'progressive' if stream.is_progressive else 'adaptive'}")
        
        # Try multiple stream selection strategies
        stream = None
        
        # Strategy 1: Progressive MP4 streams (video + audio)
        progressive_streams = yt.streams.filter(progressive=True, file_extension='mp4')
        if progressive_streams:
            stream = progressive_streams.order_by('resolution').desc().first()
            typer.echo(f"Selected progressive stream: {stream.resolution}")
        
        # Strategy 2: Adaptive video streams if no progressive
        if not stream:
            video_streams = yt.streams.filter(adaptive=True, file_extension='mp4', only_video=True)
            if video_streams:
                stream = video_streams.order_by('resolution').desc().first()
                typer.echo(f"Selected adaptive video stream: {stream.resolution}")
                typer.echo("Note: This will be video-only. Audio merging not implemented yet.")
        
        # Strategy 3: Any MP4 stream
        if not stream:
            all_mp4 = yt.streams.filter(file_extension='mp4')
            if all_mp4:
                stream = all_mp4.first()
                typer.echo(f"Selected fallback stream: {stream}")
        
        if not stream:
            typer.echo("Error: No suitable MP4 streams found", err=True)
            typer.echo("Available streams:")
            for s in yt.streams:
                typer.echo(f"  {s}")
            return False
        
        # Download the video
        typer.echo(f"Downloading stream: {stream}")
        temp_path = stream.download(output_path=os.path.dirname(output_path))
        
        # Rename to desired output path
        if temp_path != output_path:
            os.rename(temp_path, output_path)
        
        typer.echo(f"Successfully downloaded: {output_path}")
        return True
        
    except VideoUnavailable as e:
        typer.echo(f"Error: Video is unavailable: {e}", err=True)
        return False
    except RegexMatchError as e:
        typer.echo(f"Error: Invalid YouTube URL: {e}", err=True) 
        return False
    except Exception as e:
        typer.echo(f"Error downloading video: {e}", err=True)
        typer.echo("This might be due to YouTube changes. Try:")
        typer.echo("1. pip install --upgrade pytube")
        typer.echo("2. Use a different video URL")
        typer.echo("3. Use --input-file with a local video instead")
        return False

def download_with_ytdlp(url: str, output_path: str) -> bool:
    """Download YouTube video using yt-dlp as fallback."""
    try:
        typer.echo("Trying yt-dlp as fallback...")
        
        # Clean URL
        clean_url = url.split('&')[0].split('?si=')[0]
        
        # Check if yt-dlp is installed
        try:
            subprocess.run(['yt-dlp', '--version'], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            typer.echo("Error: yt-dlp not found. Install with: pip install yt-dlp", err=True)
            return False
        
        # Get video info first
        info_cmd = [
            'yt-dlp',
            '--print', 'title',
            '--print', 'duration',
            '--no-download',
            clean_url
        ]
        
        result = subprocess.run(info_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            typer.echo(f"Error getting video info: {result.stderr}", err=True)
            return False
        
        lines = result.stdout.strip().split('\n')
        title = lines[0] if len(lines) > 0 else "Unknown"
        duration = float(lines[1]) if len(lines) > 1 and lines[1].replace('.', '').isdigit() else 0
        
        typer.echo(f"Title: {title}")
        typer.echo(f"Duration: {duration} seconds")
        
        # Check duration limit
        if duration > 120:
            typer.echo(f"Error: Video duration ({duration}s) exceeds 2 minute limit", err=True)
            return False
        
        # Download video
        download_cmd = [
            'yt-dlp',
            '-f', 'best[ext=mp4]/best',
            '--output', output_path,
            clean_url
        ]
        
        typer.echo("Downloading with yt-dlp...")
        result = subprocess.run(download_cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            typer.echo(f"Successfully downloaded: {output_path}")
            return True
        else:
            typer.echo(f"yt-dlp error: {result.stderr}", err=True)
            return False
            
    except Exception as e:
        typer.echo(f"Error with yt-dlp: {e}", err=True)
        return False

def validate_local_video(input_path: str) -> bool:
    """Validate local video file and check duration."""
    if not os.path.exists(input_path):
        typer.echo(f"Error: File not found: {input_path}", err=True)
        return False
    
    # Check if it's a video file
    video_extensions = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm'}
    if Path(input_path).suffix.lower() not in video_extensions:
        typer.echo(f"Error: Unsupported file format. Supported: {', '.join(video_extensions)}", err=True)
        return False
    
    # Check duration
    duration = get_video_duration(input_path)
    if duration == 0:
        typer.echo("Error: Could not determine video duration", err=True)
        return False
    
    if duration > 120:  # 2 minutes
        typer.echo(f"Error: Video duration ({duration:.1f}s) exceeds 2 minute limit", err=True)
        return False
    
    typer.echo(f"Video validated: {input_path} ({duration:.1f}s)")
    return True

def convert_to_mp4(input_path: str, output_path: str) -> bool:
    """Convert video to MP4 format if needed."""
    try:
        if input_path.lower().endswith('.mp4') and input_path != output_path:
            # Just copy if already MP4
            import shutil
            shutil.copy2(input_path, output_path)
            typer.echo(f"Copied MP4 file to: {output_path}")
            return True
        elif input_path == output_path and input_path.lower().endswith('.mp4'):
            # Already in correct format and location
            return True
        else:
            # Convert to MP4
            typer.echo(f"Converting {input_path} to MP4...")
            (
                ffmpeg
                .input(input_path)
                .output(output_path, vcodec='libx264', acodec='aac')
                .overwrite_output()
                .run(quiet=True)
            )
            typer.echo(f"Converted video to: {output_path}")
            return True
    except Exception as e:
        typer.echo(f"Error converting video: {e}", err=True)
        return False

def download_command(
    url: Optional[str] = typer.Option(None, "--url", help="YouTube URL to download"),
    input_file: Optional[str] = typer.Option(None, "--input-file", help="Local video file to use"),
    output: str = typer.Option("input.mp4", "--output", help="Output MP4 file path")
):
    """Download YouTube video or process local video file."""
    
    if not url and not input_file:
        typer.echo("Error: Must specify either --url or --input-file", err=True)
        raise typer.Exit(1)
    
    if url and input_file:
        typer.echo("Error: Cannot specify both --url and --input-file", err=True)
        raise typer.Exit(1)
    
    # Create output directory if it doesn't exist
    output_dir = os.path.dirname(output)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    if url:
        # Download from YouTube - try pytube first, then yt-dlp fallback
        success = download_youtube_video(url, output)
        if not success:
            typer.echo("Pytube failed, trying yt-dlp fallback...")
            success = download_with_ytdlp(url, output)
            if not success:
                raise typer.Exit(1)
    else:
        # Process local file
        if not validate_local_video(input_file):
            raise typer.Exit(1)
        
        # Convert to MP4 if needed
        if not convert_to_mp4(input_file, output):
            raise typer.Exit(1)
    
    # Final validation
    if not validate_local_video(output):
        typer.echo("Error: Output video validation failed", err=True)
        raise typer.Exit(1)
    
    typer.echo(f"✅ Video ready: {output}")

if __name__ == "__main__":
    typer.run(download_command)