#!/usr/bin/env python3

import os
import sys
import glob
import tempfile
from pathlib import Path
from typing import List, Optional
import ffmpeg
import typer

def get_video_info(video_path: str) -> dict:
    """Get video information using ffmpeg probe."""
    try:
        probe = ffmpeg.probe(video_path)
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        audio_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'audio'), None)
        
        return {
            'duration': float(probe['format']['duration']),
            'width': int(video_stream['width']) if video_stream else 0,
            'height': int(video_stream['height']) if video_stream else 0,
            'fps': eval(video_stream['r_frame_rate']) if video_stream else 0,
            'has_audio': audio_stream is not None,
            'codec': video_stream['codec_name'] if video_stream else None
        }
    except Exception as e:
        typer.echo(f"Error getting video info for {video_path}: {e}", err=True)
        return {}

def validate_clips(clip_paths: List[str]) -> List[str]:
    """Validate and filter clip files."""
    valid_clips = []
    
    for clip_path in clip_paths:
        if not os.path.exists(clip_path):
            typer.echo(f"Warning: File not found: {clip_path}", err=True)
            continue
        
        if os.path.getsize(clip_path) == 0:
            typer.echo(f"Warning: Empty file: {clip_path}", err=True)
            continue
        
        # Check if it's a valid video file
        info = get_video_info(clip_path)
        if not info or info.get('duration', 0) == 0:
            typer.echo(f"Warning: Invalid or corrupt video: {clip_path}", err=True)
            continue
        
        valid_clips.append(clip_path)
    
    return valid_clips

def natural_sort_key(text: str) -> List:
    """Natural sort key for proper ordering of scene files."""
    import re
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', text)]

def create_concat_file(clip_paths: List[str], concat_file: str):
    """Create FFmpeg concat demuxer file."""
    with open(concat_file, 'w') as f:
        for clip_path in clip_paths:
            # Use absolute paths and escape special characters
            abs_path = os.path.abspath(clip_path)
            # Escape single quotes for FFmpeg
            escaped_path = abs_path.replace("'", "'\"'\"'")
            f.write(f"file '{escaped_path}'\n")

def stitch_videos_concat(clip_paths: List[str], output_path: str) -> bool:
    """Stitch videos using FFmpeg concat demuxer (fastest, no re-encoding)."""
    try:
        # Check if all videos have the same properties
        first_info = get_video_info(clip_paths[0])
        compatible = True
        
        for clip_path in clip_paths[1:]:
            info = get_video_info(clip_path)
            if (info.get('width') != first_info.get('width') or 
                info.get('height') != first_info.get('height') or
                info.get('codec') != first_info.get('codec')):
                compatible = False
                break
        
        if not compatible:
            typer.echo("Videos have different properties, using filter concat method...")
            return stitch_videos_filter(clip_paths, output_path)
        
        # Create temporary concat file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as temp_file:
            create_concat_file(clip_paths, temp_file.name)
            concat_file = temp_file.name
        
        try:
            # Use concat demuxer
            (
                ffmpeg
                .input(concat_file, format='concat', safe=0)
                .output(output_path, c='copy')  # Copy streams without re-encoding
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True, quiet=True)
            )
            
        finally:
            # Clean up temp file
            os.unlink(concat_file)
        
        return True
        
    except Exception as e:
        typer.echo(f"Error with concat demuxer: {e}", err=True)
        typer.echo("Falling back to filter concat method...")
        return stitch_videos_filter(clip_paths, output_path)

def stitch_videos_filter(clip_paths: List[str], output_path: str) -> bool:
    """Stitch videos using FFmpeg filter concat (re-encodes, slower but more compatible)."""
    try:
        # Get info for the first video to determine output properties
        first_info = get_video_info(clip_paths[0])
        width = first_info.get('width', 1280)
        height = first_info.get('height', 720)
        
        # Build ffmpeg inputs
        inputs = []
        for clip_path in clip_paths:
            inputs.append(ffmpeg.input(clip_path))
        
        # Create filter concat
        if len(inputs) == 1:
            # Single input, just copy
            stream = inputs[0]
        else:
            # Multiple inputs, use concat filter
            video_streams = []
            audio_streams = []
            
            for inp in inputs:
                # Scale all videos to same resolution
                video = inp.video.filter('scale', width, height)
                video_streams.append(video)
                
                # Add audio if available
                try:
                    audio = inp.audio
                    audio_streams.append(audio)
                except:
                    # Create silent audio if no audio stream
                    audio = ffmpeg.input('anullsrc=channel_layout=stereo:sample_rate=44100', f='lavfi', t=get_video_info(clip_paths[video_streams.index(video)])['duration'])
                    audio_streams.append(audio)
            
            # Concat video streams
            video_concat = ffmpeg.concat(*video_streams, v=1, a=0)
            
            # Concat audio streams  
            if audio_streams:
                audio_concat = ffmpeg.concat(*audio_streams, v=0, a=1)
                stream = ffmpeg.output(video_concat, audio_concat, output_path)
            else:
                stream = ffmpeg.output(video_concat, output_path)
        
        # Run ffmpeg
        stream.overwrite_output().run(capture_stdout=True, capture_stderr=True, quiet=True)
        
        return True
        
    except Exception as e:
        typer.echo(f"Error with filter concat: {e}", err=True)
        return False

def add_intro_outro(input_path: str, output_path: str, intro_path: Optional[str] = None, outro_path: Optional[str] = None) -> bool:
    """Add intro and/or outro to the stitched video."""
    try:
        clips = []
        
        if intro_path and os.path.exists(intro_path):
            clips.append(intro_path)
            typer.echo(f"Adding intro: {intro_path}")
        
        clips.append(input_path)
        
        if outro_path and os.path.exists(outro_path):
            clips.append(outro_path)
            typer.echo(f"Adding outro: {outro_path}")
        
        if len(clips) == 1:
            # No intro/outro, just copy
            import shutil
            shutil.copy2(input_path, output_path)
            return True
        
        # Stitch with intro/outro
        return stitch_videos_concat(clips, output_path)
        
    except Exception as e:
        typer.echo(f"Error adding intro/outro: {e}", err=True)
        return False

def stitch_command(
    inputs: str = typer.Argument(..., help="Input pattern (e.g., './clips/*.mp4') or directory"),
    output: str = typer.Option("final_video.mp4", "--output", help="Output video file"),
    intro: Optional[str] = typer.Option(None, "--intro", help="Intro video file"),
    outro: Optional[str] = typer.Option(None, "--outro", help="Outro video file"),
    method: str = typer.Option("auto", "--method", help="Stitching method: auto, concat, filter"),
    sort: bool = typer.Option(True, "--sort/--no-sort", help="Sort files naturally")
):
    """Stitch video clips into a single video."""
    
    # Find input files
    if os.path.isdir(inputs):
        # Directory provided, find all video files
        clip_paths = []
        for ext in ['*.mp4', '*.avi', '*.mov', '*.mkv']:
            clip_paths.extend(glob.glob(os.path.join(inputs, ext)))
    else:
        # Pattern provided
        clip_paths = glob.glob(inputs)
    
    if not clip_paths:
        typer.echo(f"Error: No video files found matching: {inputs}", err=True)
        raise typer.Exit(1)
    
    # Sort files naturally (scene_01.mp4, scene_02.mp4, etc.)
    if sort:
        clip_paths.sort(key=natural_sort_key)
    
    typer.echo(f"Found {len(clip_paths)} video files:")
    for i, clip_path in enumerate(clip_paths, 1):
        info = get_video_info(clip_path)
        duration = info.get('duration', 0)
        typer.echo(f"  {i:2d}. {os.path.basename(clip_path)} ({duration:.1f}s)")
    
    # Validate clips
    valid_clips = validate_clips(clip_paths)
    if not valid_clips:
        typer.echo("Error: No valid video clips found", err=True)
        raise typer.Exit(1)
    
    if len(valid_clips) != len(clip_paths):
        typer.echo(f"Warning: {len(clip_paths) - len(valid_clips)} clips were invalid and skipped", err=True)
    
    # Calculate total duration
    total_duration = sum(get_video_info(clip).get('duration', 0) for clip in valid_clips)
    typer.echo(f"\nTotal duration: {total_duration:.1f}s ({total_duration/60:.1f} minutes)")
    
    # Create output directory if needed
    output_dir = os.path.dirname(output)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Determine stitching method
    if method == "auto":
        # Use concat demuxer for speed if possible, otherwise filter
        typer.echo("Using automatic method selection...")
        success = stitch_videos_concat(valid_clips, output)
    elif method == "concat":
        typer.echo("Using concat demuxer method...")
        success = stitch_videos_concat(valid_clips, output)
    elif method == "filter":
        typer.echo("Using filter concat method...")
        success = stitch_videos_filter(valid_clips, output)
    else:
        typer.echo(f"Error: Unknown method '{method}'. Use: auto, concat, or filter", err=True)
        raise typer.Exit(1)
    
    if not success:
        typer.echo("Error: Failed to stitch videos", err=True)
        raise typer.Exit(1)
    
    # Add intro/outro if specified
    if intro or outro:
        temp_output = output + ".temp.mp4"
        os.rename(output, temp_output)
        
        if add_intro_outro(temp_output, output, intro, outro):
            os.remove(temp_output)
            typer.echo("✅ Added intro/outro")
        else:
            os.rename(temp_output, output)
            typer.echo("Warning: Failed to add intro/outro, using original stitched video")
    
    # Verify output
    if os.path.exists(output):
        output_info = get_video_info(output)
        output_duration = output_info.get('duration', 0)
        typer.echo(f"✅ Stitching complete: {output}")
        typer.echo(f"Output duration: {output_duration:.1f}s")
        
        # Check if duration roughly matches expected
        expected_duration = total_duration
        if intro and os.path.exists(intro):
            expected_duration += get_video_info(intro).get('duration', 0)
        if outro and os.path.exists(outro):
            expected_duration += get_video_info(outro).get('duration', 0)
        
        if abs(output_duration - expected_duration) > 1.0:  # Allow 1 second difference
            typer.echo(f"⚠️  Warning: Duration mismatch. Expected ~{expected_duration:.1f}s, got {output_duration:.1f}s")
    else:
        typer.echo("Error: Output file was not created", err=True)
        raise typer.Exit(1)

if __name__ == "__main__":
    typer.run(stitch_command)