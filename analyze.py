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

def extract_audio_segment(video_path: str, start_time: float, end_time: float, output_path: str) -> bool:
    """Extract audio segment from video."""
    try:
        (
            ffmpeg
            .input(video_path, ss=start_time, t=end_time - start_time)
            .output(output_path, acodec='pcm_s16le', ac=1, ar='16000')
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True, quiet=True)
        )
        return True
    except Exception as e:
        typer.echo(f"Error extracting audio segment: {e}", err=True)
        return False

def transcribe_audio_whisper(audio_path: str) -> Dict[str, Any]:
    """Transcribe audio using OpenAI Whisper with timestamps."""
    try:
        import whisper
        model = whisper.load_model("base")
        result = model.transcribe(audio_path, word_timestamps=True)
        return {
            "text": result["text"].strip(),
            "segments": result.get("segments", [])
        }
    except ImportError:
        typer.echo("Whisper not available. Install with: pip install openai-whisper", err=True)
        return {"text": "", "segments": []}
    except Exception as e:
        typer.echo(f"Error transcribing audio: {e}", err=True)
        return {"text": "", "segments": []}

def split_long_scene(scene: Dict[str, Any], dialogue_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Split scenes longer than 8 seconds into manageable chunks."""
    if scene['duration'] <= 8.0:
        return [scene]
    
    chunk_length = 7.0  # 7 seconds per chunk
    overlap = 1.0       # 1 second overlap
    
    chunks = []
    start_time = scene['start_seconds']
    end_time = scene['end_seconds']
    chunk_num = 1
    
    current_start = start_time
    
    while current_start < end_time:
        # Calculate chunk end (but don't exceed scene end)
        current_end = min(current_start + chunk_length, end_time)
        
        # If this would be a very short final chunk, extend the previous chunk instead
        if end_time - current_end < 2.0 and len(chunks) > 0:
            chunks[-1]['end_seconds'] = end_time
            chunks[-1]['end_time'] = format_timestamp(end_time)
            chunks[-1]['duration'] = end_time - chunks[-1]['start_seconds']
            break
        
        # Extract dialogue for this chunk
        chunk_dialogue = extract_dialogue_for_timerange(
            dialogue_data, current_start - start_time, current_end - start_time
        )
        
        chunk = {
            'id': f"{scene['id']}_chunk_{chunk_num:02d}",
            'parent_scene_id': scene['id'],
            'chunk_number': chunk_num,
            'total_chunks': 0,  # Will be updated after all chunks are created
            'start_time': format_timestamp(current_start),
            'end_time': format_timestamp(current_end),
            'start_seconds': current_start,
            'end_seconds': current_end,
            'duration': current_end - current_start,
            'is_chunk': True,
            'dialogue': chunk_dialogue,
            'overlap_with_previous': overlap if chunk_num > 1 else 0,
            'overlap_with_next': overlap if current_end < end_time else 0
        }
        
        chunks.append(chunk)
        
        # Move to next chunk (with overlap)
        current_start = current_end - overlap
        chunk_num += 1
    
    # Update total_chunks for all chunks
    for chunk in chunks:
        chunk['total_chunks'] = len(chunks)
    
    typer.echo(f"Split {scene['id']} ({scene['duration']:.1f}s) into {len(chunks)} chunks")
    return chunks

def extract_dialogue_for_timerange(dialogue_data: Dict[str, Any], start_offset: float, end_offset: float) -> str:
    """Extract dialogue that occurs within a specific time range."""
    if not dialogue_data.get("segments"):
        return dialogue_data.get("text", "")
    
    relevant_segments = []
    for segment in dialogue_data["segments"]:
        seg_start = segment.get("start", 0)
        seg_end = segment.get("end", 0)
        
        # Include segment if it overlaps with our time range
        if seg_start < end_offset and seg_end > start_offset:
            relevant_segments.append(segment["text"].strip())
    
    return " ".join(relevant_segments).strip()

def image_to_base64(image_path: str) -> str:
    """Convert image to base64 string."""
    with open(image_path, 'rb') as img_file:
        return base64.b64encode(img_file.read()).decode('utf-8')

def analyze_scene_with_claude(client: Anthropic, scene: Dict[str, Any], frame_paths: List[str], dialogue: str = "") -> Dict[str, Any]:
    """Analyze a scene using Claude with multiple extracted frames."""
    try:
        # Convert images to base64
        frame_data = []
        for i, frame_path in enumerate(frame_paths):
            image_base64 = image_to_base64(frame_path)
            frame_data.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_base64
                }
            })
        
        frame_count = len(frame_paths)
        frame_desc = f"{frame_count} frames from different moments in this {scene['duration']:.1f}-second scene (beginning, middle, end)" if frame_count > 1 else f"frame from this {scene['duration']:.1f}-second scene"
        
        # Create frame descriptions for temporal analysis
        frame_labels = []
        if frame_count == 1:
            frame_labels = ["middle of scene"]
        elif frame_count == 2:
            frame_labels = ["beginning", "end"]
        else:
            frame_labels = ["beginning", "middle", "end"]
        
        frame_analysis_text = ""
        for i, label in enumerate(frame_labels):
            frame_analysis_text += f"Frame {i+1} ({label}): Analyze this frame's specific visual elements, character positions, lighting, and what's happening at this moment.\n"
        
        dialogue_section = ""
        if dialogue.strip():
            dialogue_section = f"""
DIALOGUE/AUDIO CONTENT:
"{dialogue}"

IMPORTANT: Include this dialogue/audio in your scene description. Describe when and how it's spoken/heard during the sequence.
"""

        prompt = f"""You are an expert cinematographer and director. Analyze these {frame_count} frames from a {scene['duration']:.1f}-second video scene and create an EXTREMELY DETAILED cinematic prompt for Veo3.

Scene timing: {scene['start_time']} to {scene['end_time']}
Duration: {scene['duration']:.1f} seconds

{frame_analysis_text}{dialogue_section}

CRITICAL: Describe this as a TEMPORAL SEQUENCE showing progression from beginning to end. Don't just describe static images - describe the MOTION, TRANSITIONS, and FLOW between moments.

ANALYZE FRAME-BY-FRAME PROGRESSION:
- What changes between frames (character movement, camera movement, lighting shifts)
- How elements transition from beginning to end
- Specific motion happening (walking, gesturing, objects moving)
- Camera movement (panning, zooming, tracking)
- Environmental changes (lighting shifts, background changes)

FOR EACH FRAME, DESCRIBE:
- Exact lighting (color temperature, shadows, highlights, reflections)
- Character details (clothing, expressions, posture, actions)
- Objects/props (materials, textures, positions)
- Environmental elements (location, weather, background)
- Camera angle and positioning

CREATE A TEMPORAL SCREENPLAY PROMPT:
"LOCATION – TIME OF DAY (special notes)
[Beginning] Detailed description of opening moment...
The camera [movement type] as [character/action] [specific motion]...
[Middle] Progression continues with [specific changes]...
[End] The sequence concludes with [final state/action]...
Throughout the scene, [lighting, atmosphere, mood elements]..."

MAKE IT 500+ WORDS describing the COMPLETE SEQUENCE, not just static moments.

Return ONLY valid JSON:

```json
{{
    "description": "Brief summary of the complete sequence and what progresses through the scene",
    "scene_prompt": "ULTRA-DETAILED temporal sequence description with location header, frame-by-frame progression, character movement, camera motion, environmental changes, and complete flow from beginning to end",
    "cinematic_notes": "Camera movement, lens type, lighting progression, color grading, composition changes, and mood evolution throughout the sequence",
    "diagnostics": {{
        "text_heavy": false,
        "camera_motion": true,
        "complex_characters": true,
        "rapid_motion": false,
        "duration_warning": {str(scene['duration'] > 8).lower()}
    }}
}}
```"""

        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        *frame_data,
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        )
        
        # Parse Claude's response and clean control characters
        response_text = response.content[0].text.strip()
        # Remove control characters that break JSON parsing
        import re
        response_text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', response_text)
        
        # Try to extract JSON from the response with multiple methods
        analysis = None
        json_str = ""
        
        try:
            # Method 1: Look for ```json blocks
            json_start = response_text.find('```json')
            if json_start != -1:
                json_start = response_text.find('{', json_start)
                json_end = response_text.find('```', json_start)
                if json_end != -1:
                    json_str = response_text[json_start:json_end].strip()
                else:
                    json_str = response_text[json_start:].strip()
                    # Find the last complete brace
                    brace_count = 0
                    last_complete = len(json_str)
                    for i, char in enumerate(json_str):
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                last_complete = i + 1
                    json_str = json_str[:last_complete]
            else:
                # Method 2: Find first complete JSON object
                start_idx = response_text.find('{')
                if start_idx == -1:
                    raise ValueError("No JSON found in response")
                
                # Count braces to find complete JSON
                brace_count = 0
                end_idx = start_idx
                for i, char in enumerate(response_text[start_idx:], start_idx):
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            end_idx = i + 1
                            break
                
                json_str = response_text[start_idx:end_idx]
            
            # Try to parse the JSON
            analysis = json.loads(json_str)
            
            # Validate required fields exist
            if 'scene_prompt' not in analysis or 'cinematic_notes' not in analysis:
                raise ValueError("Missing required fields in JSON response")
                
        except (json.JSONDecodeError, ValueError) as e:
            typer.echo(f"JSON parsing failed for {scene['id']}: {e}", err=True)
            typer.echo("Raw response:", err=True)
            typer.echo(response_text[:500] + "..." if len(response_text) > 500 else response_text, err=True)
            
            # Create detailed fallback using the raw response (no truncation)
            analysis = {
                "description": f"Scene analysis for {scene['duration']:.1f}s video segment",
                "scene_prompt": response_text.strip(),  # Keep full response, don't truncate
                "cinematic_notes": "Raw analysis provided - JSON parsing failed but full content preserved",
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
            "scene_prompt": f"Generate a {scene['duration']:.1f}-second video scene",
            "cinematic_notes": "Technical specifications not available due to analysis error",
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
            
            # Extract 2-3 frames from scene (beginning, middle, end if long enough)
            frame_paths = []
            duration = scene['duration']
            
            if duration <= 2.0:
                # Short scene: extract 1 frame from middle
                mid_time = (scene['start_seconds'] + scene['end_seconds']) / 2
                frame_path = os.path.join(temp_dir, f"{scene['id']}_frame_1.jpg")
                if extract_frame(video, mid_time, frame_path):
                    frame_paths.append(frame_path)
            elif duration <= 4.0:
                # Medium scene: extract 2 frames (beginning and end)
                times = [
                    scene['start_seconds'] + 0.2,  # Beginning (slightly offset)
                    scene['end_seconds'] - 0.2     # End (slightly offset)
                ]
                for j, time in enumerate(times):
                    frame_path = os.path.join(temp_dir, f"{scene['id']}_frame_{j+1}.jpg")
                    if extract_frame(video, time, frame_path):
                        frame_paths.append(frame_path)
            else:
                # Long scene: extract 3 frames (beginning, middle, end)
                times = [
                    scene['start_seconds'] + 0.2,  # Beginning
                    (scene['start_seconds'] + scene['end_seconds']) / 2,  # Middle
                    scene['end_seconds'] - 0.2     # End
                ]
                for j, time in enumerate(times):
                    frame_path = os.path.join(temp_dir, f"{scene['id']}_frame_{j+1}.jpg")
                    if extract_frame(video, time, frame_path):
                        frame_paths.append(frame_path)
            
            if frame_paths:
                typer.echo(f"  Extracted {len(frame_paths)} frames for analysis")
                
                # Extract audio for dialogue/sound analysis
                audio_path = os.path.join(temp_dir, f"{scene['id']}_audio.wav")
                dialogue_data = {"text": "", "segments": []}
                if extract_audio_segment(video, scene['start_seconds'], scene['end_seconds'], audio_path):
                    typer.echo(f"  Extracting audio/dialogue...")
                    dialogue_data = transcribe_audio_whisper(audio_path)
                    if dialogue_data["text"]:
                        typer.echo(f"  Found dialogue: {dialogue_data['text'][:50]}...")
                
                # Split long scenes into chunks
                scene_chunks = split_long_scene(scene, dialogue_data)
                
                # Analyze each chunk
                for chunk in scene_chunks:
                    chunk_dialogue = chunk.get('dialogue', dialogue_data["text"])
                    
                    # For chunks, we need to extract frames specific to the chunk timerange
                    if chunk.get('is_chunk'):
                        # Extract frames for this specific chunk
                        chunk_frame_paths = []
                        chunk_duration = chunk['duration']
                        
                        if chunk_duration <= 2.0:
                            # Short chunk: 1 frame from middle
                            mid_time = (chunk['start_seconds'] + chunk['end_seconds']) / 2
                            frame_path = os.path.join(temp_dir, f"{chunk['id']}_frame_1.jpg")
                            if extract_frame(video, mid_time, frame_path):
                                chunk_frame_paths.append(frame_path)
                        elif chunk_duration <= 4.0:
                            # Medium chunk: 2 frames
                            times = [
                                chunk['start_seconds'] + 0.2,
                                chunk['end_seconds'] - 0.2
                            ]
                            for j, time in enumerate(times):
                                frame_path = os.path.join(temp_dir, f"{chunk['id']}_frame_{j+1}.jpg")
                                if extract_frame(video, time, frame_path):
                                    chunk_frame_paths.append(frame_path)
                        else:
                            # Long chunk: 3 frames
                            times = [
                                chunk['start_seconds'] + 0.2,
                                (chunk['start_seconds'] + chunk['end_seconds']) / 2,
                                chunk['end_seconds'] - 0.2
                            ]
                            for j, time in enumerate(times):
                                frame_path = os.path.join(temp_dir, f"{chunk['id']}_frame_{j+1}.jpg")
                                if extract_frame(video, time, frame_path):
                                    chunk_frame_paths.append(frame_path)
                        
                        analysis = analyze_scene_with_claude(client, chunk, chunk_frame_paths, chunk_dialogue)
                    else:
                        # Regular scene, use existing frames
                        analysis = analyze_scene_with_claude(client, chunk, frame_paths, chunk_dialogue)
                    
                    # Combine chunk info with analysis
                    analyzed_scene = {
                        **chunk,
                        **analysis
                    }
                    if chunk_dialogue:
                        analyzed_scene['dialogue'] = chunk_dialogue
                    analyzed_scenes.append(analyzed_scene)
            else:
                typer.echo(f"Warning: Could not extract any frames for {scene['id']}", err=True)
    
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

**Scene Prompt:**
```
{scene['scene_prompt']}
```

**Cinematic Notes:**
```
{scene['cinematic_notes']}
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