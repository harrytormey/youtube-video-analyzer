#!/usr/bin/env python3

import os
import sys
import json
import hashlib
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional
import ffmpeg
from PIL import Image
import typer
from anthropic import Anthropic
from dotenv import load_dotenv
import base64
from io import BytesIO

load_dotenv()

def get_anthropic_client() -> Anthropic:
    """Initialize Anthropic client."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        typer.echo("Error: ANTHROPIC_API_KEY not found in environment", err=True)
        raise typer.Exit(1)
    return Anthropic(api_key=api_key)

def detect_scenes(video_path: str, threshold: float = 0.4) -> List[Dict[str, Any]]:
    """Detect scene changes using FFmpeg."""
    try:
        typer.echo(f"Detecting scenes with threshold {threshold}...")
        
        # Get video duration
        probe = ffmpeg.probe(video_path)
        duration = float(probe['streams'][0]['duration'])
        typer.echo(f"Video duration: {duration:.1f}s")
        
        # Run ffmpeg scene detection
        typer.echo("Running scene detection...")
        cmd = (
            ffmpeg.input(video_path)
            .filter('select', f'gt(scene,{threshold})')
            .filter('showinfo')
            .output('-', f='null')
        )
        
        # Run with subprocess to get proper output
        import subprocess
        args = ffmpeg.compile(cmd)
        result = subprocess.run(args, capture_output=True, text=True)
        
        # Parse stderr for scene timestamps
        stderr_output = result.stderr
        scene_times = [0.0]  # Always start with 0
        
        # Look for showinfo output with timestamps
        for line in stderr_output.split('\n'):
            if 'pts_time:' in line and 'showinfo' in line:
                try:
                    # Extract timestamp from showinfo output
                    parts = line.split('pts_time:')
                    if len(parts) > 1:
                        time_part = parts[1].split()[0]
                        timestamp = float(time_part)
                        scene_times.append(timestamp)
                except (IndexError, ValueError) as e:
                    continue
        
        # If no scene changes detected, create one scene for the whole video
        if len(scene_times) <= 1:
            typer.echo("No scene changes detected, treating as single scene")
            scene_times = [0.0, duration]
        
        # Add final timestamp if not already there
        if scene_times[-1] != duration:
            scene_times.append(duration)
        
        scene_times = sorted(list(set(scene_times)))  # Remove duplicates and sort
        typer.echo(f"Scene boundaries at: {[f'{t:.1f}s' for t in scene_times]}")
        
        # Create scene segments
        scenes = []
        for i in range(len(scene_times) - 1):
            start_time = scene_times[i]
            end_time = scene_times[i + 1]
            scene_duration = end_time - start_time
            
            # Skip very short scenes (< 0.5 seconds)
            if scene_duration < 0.5:
                typer.echo(f"Skipping short scene: {scene_duration:.1f}s")
                continue
            
            # Warn about long scenes (> 8 seconds)
            if scene_duration > 8:
                typer.echo(f"Warning: Scene {i+1} is {scene_duration:.1f}s (exceeds 8s limit)", err=True)
            
            scenes.append({
                'id': f'scene_{i+1:02d}',
                'start_time': format_timestamp(start_time),
                'end_time': format_timestamp(end_time),
                'start_seconds': start_time,
                'end_seconds': end_time,
                'duration': scene_duration
            })
        
        typer.echo(f"✅ Detected {len(scenes)} valid scenes")
        return scenes
        
    except Exception as e:
        typer.echo(f"Error detecting scenes: {e}", err=True)
        return []

def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS.mmm format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"

def extract_frame(video_path: str, timestamp: float, output_path: str) -> bool:
    """Extract a frame from video at given timestamp."""
    try:
        (
            ffmpeg
            .input(video_path, ss=timestamp)
            .filter('scale', 1280, 720)  # Resize to reasonable resolution
            .output(output_path, vframes=1, format='image2')
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True, quiet=True)
        )
        return True
    except Exception as e:
        typer.echo(f"Error extracting frame at {timestamp}s: {e}", err=True)
        return False

def image_to_base64(image_path: str) -> str:
    """Convert image to base64 string."""
    with open(image_path, 'rb') as img_file:
        return base64.b64encode(img_file.read()).decode('utf-8')

def analyze_scene_with_claude(client: Anthropic, scene: Dict[str, Any], frame_path: str) -> Dict[str, Any]:
    """Analyze a scene using Claude with the extracted frame."""
    try:
        # Convert image to base64
        image_base64 = image_to_base64(frame_path)
        
        prompt = f"""Analyze this video frame from a {scene['duration']:.1f}-second scene and create a detailed prompt for Veo3 video generation.

Scene timing: {scene['start_time']} to {scene['end_time']}

Please provide:
1. A detailed description of what's happening in the scene
2. A Veo3-optimized prompt for generating this scene (focus on visual elements, camera movement, lighting, mood)
3. Diagnostic flags for potential generation challenges

Format your response as JSON with this structure:
{{
    "description": "Detailed description of the scene",
    "prompt": "Veo3 generation prompt (be specific about camera angles, lighting, movement, style)",
    "diagnostics": {{
        "text_heavy": boolean,
        "camera_motion": boolean,
        "complex_characters": boolean,
        "rapid_motion": boolean,
        "duration_warning": boolean
    }}
}}

Keep the Veo3 prompt under 500 characters and focus on visual storytelling elements."""

        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_base64
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        )
        
        # Parse Claude's response
        response_text = response.content[0].text.strip()
        
        # Try to extract JSON from the response
        try:
            # Find JSON in the response
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}') + 1
            if start_idx != -1 and end_idx != -1:
                json_str = response_text[start_idx:end_idx]
                analysis = json.loads(json_str)
            else:
                raise ValueError("No JSON found in response")
        except (json.JSONDecodeError, ValueError):
            # Fallback: create a basic structure
            analysis = {
                "description": response_text[:200] + "..." if len(response_text) > 200 else response_text,
                "prompt": f"Generate a {scene['duration']:.1f}-second video scene",
                "diagnostics": {
                    "text_heavy": False,
                    "camera_motion": False,
                    "complex_characters": False,
                    "rapid_motion": False,
                    "duration_warning": scene['duration'] > 8
                }
            }
        
        # Add duration warning if needed
        analysis['diagnostics']['duration_warning'] = scene['duration'] > 8
        
        return analysis
        
    except Exception as e:
        typer.echo(f"Error analyzing scene {scene['id']}: {e}", err=True)
        return {
            "description": f"Scene analysis failed: {str(e)}",
            "prompt": f"Generate a {scene['duration']:.1f}-second video scene",
            "diagnostics": {
                "text_heavy": False,
                "camera_motion": False,
                "complex_characters": False,
                "rapid_motion": False,
                "duration_warning": scene['duration'] > 8
            }
        }

def estimate_costs(scenes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Estimate processing costs."""
    # Rough estimates based on Claude pricing
    tokens_per_scene = 800  # Estimated tokens for image + prompt + response
    cost_per_1k_tokens = 0.003  # Claude 3.5 Sonnet pricing (approximate)
    
    total_tokens = len(scenes) * tokens_per_scene
    claude_cost = (total_tokens / 1000) * cost_per_1k_tokens
    
    # Veo3 cost estimation (placeholder - actual pricing varies)
    total_duration = sum(scene['duration'] for scene in scenes)
    veo3_cost_per_second = 0.10  # Estimated cost per second
    veo3_cost = total_duration * veo3_cost_per_second
    
    return {
        'claude_tokens': total_tokens,
        'claude_cost_usd': claude_cost,
        'total_duration_seconds': total_duration,
        'estimated_veo3_cost_usd': veo3_cost,
        'total_estimated_cost_usd': claude_cost + veo3_cost
    }

def analyze_command(
    video: str = typer.Argument(..., help="Input video file"),
    output: str = typer.Option("scene_prompts.json", "--output", help="Output JSON file"),
    threshold: float = typer.Option(0.4, "--threshold", help="Scene detection threshold (0.0-1.0)"),
    estimate_only: bool = typer.Option(False, "--estimate-only", help="Only show cost estimate"),
    markdown: bool = typer.Option(False, "--markdown", help="Also save as markdown")
):
    """Analyze video scenes and generate Veo3 prompts."""
    
    if not os.path.exists(video):
        typer.echo(f"Error: Video file not found: {video}", err=True)
        raise typer.Exit(1)
    
    # Detect scenes
    scenes = detect_scenes(video, threshold)
    if not scenes:
        typer.echo("Error: No scenes detected", err=True)
        raise typer.Exit(1)
    
    # Show cost estimate
    cost_estimate = estimate_costs(scenes)
    typer.echo(f"\n📊 Analysis Estimate:")
    typer.echo(f"Scenes detected: {len(scenes)}")
    typer.echo(f"Total duration: {cost_estimate['total_duration_seconds']:.1f}s")
    typer.echo(f"Estimated Claude tokens: {cost_estimate['claude_tokens']:,}")
    typer.echo(f"Estimated Claude cost: ${cost_estimate['claude_cost_usd']:.3f}")
    typer.echo(f"Estimated Veo3 cost: ${cost_estimate['estimated_veo3_cost_usd']:.2f}")
    typer.echo(f"Total estimated cost: ${cost_estimate['total_estimated_cost_usd']:.2f}")
    
    if estimate_only:
        return
    
    # Initialize Claude client
    client = get_anthropic_client()
    
    # Analyze each scene
    analyzed_scenes = []
    
    with tempfile.TemporaryDirectory() as temp_dir:
        for i, scene in enumerate(scenes):
            typer.echo(f"Analyzing scene {i+1}/{len(scenes)}: {scene['id']}")
            
            # Extract frame from middle of scene
            mid_time = (scene['start_seconds'] + scene['end_seconds']) / 2
            frame_path = os.path.join(temp_dir, f"{scene['id']}_frame.jpg")
            
            if extract_frame(video, mid_time, frame_path):
                analysis = analyze_scene_with_claude(client, scene, frame_path)
                
                # Combine scene info with analysis
                analyzed_scene = {
                    **scene,
                    **analysis
                }
                analyzed_scenes.append(analyzed_scene)
            else:
                typer.echo(f"Warning: Could not extract frame for {scene['id']}", err=True)
    
    # Create final output
    output_data = {
        'video_path': video,
        'detection_threshold': threshold,
        'total_scenes': len(analyzed_scenes),
        'total_duration': sum(s['duration'] for s in analyzed_scenes),
        'cost_estimate': cost_estimate,
        'scenes': analyzed_scenes
    }
    
    # Save JSON output
    with open(output, 'w') as f:
        json.dump(output_data, f, indent=2)
    
    typer.echo(f"✅ Analysis complete: {output}")
    
    # Save markdown version if requested
    if markdown:
        md_path = output.replace('.json', '.md')
        save_markdown_report(output_data, md_path)
        typer.echo(f"📝 Markdown report: {md_path}")

def save_markdown_report(data: Dict[str, Any], output_path: str):
    """Save analysis results as markdown."""
    md_content = f"""# Video Scene Analysis Report

**Video:** {data['video_path']}  
**Detection Threshold:** {data['detection_threshold']}  
**Total Scenes:** {data['total_scenes']}  
**Total Duration:** {data['total_duration']:.1f}s  

## Cost Estimate
- Claude tokens: {data['cost_estimate']['claude_tokens']:,}
- Claude cost: ${data['cost_estimate']['claude_cost_usd']:.3f}
- Estimated Veo3 cost: ${data['cost_estimate']['estimated_veo3_cost_usd']:.2f}
- **Total estimated cost: ${data['cost_estimate']['total_estimated_cost_usd']:.2f}**

## Scenes

"""
    
    for scene in data['scenes']:
        md_content += f"""### {scene['id']} ({scene['start_time']} - {scene['end_time']})

**Duration:** {scene['duration']:.1f}s

**Description:** {scene['description']}

**Veo3 Prompt:**
```
{scene['prompt']}
```

**Diagnostics:**
- Text heavy: {'⚠️' if scene['diagnostics']['text_heavy'] else '✅'}
- Camera motion: {'⚠️' if scene['diagnostics']['camera_motion'] else '✅'}
- Complex characters: {'⚠️' if scene['diagnostics']['complex_characters'] else '✅'}
- Rapid motion: {'⚠️' if scene['diagnostics']['rapid_motion'] else '✅'}
- Duration warning: {'⚠️' if scene['diagnostics']['duration_warning'] else '✅'}

---

"""
    
    with open(output_path, 'w') as f:
        f.write(md_content)

if __name__ == "__main__":
    typer.run(analyze_command)