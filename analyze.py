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
        
        # Run ffmpeg scene detection with better parameters
        typer.echo("Running scene detection...")
        cmd = (
            ffmpeg.input(video_path)
            .filter('select', f'gt(scene,{threshold})')
            .filter('showinfo')
            .output('-', f='null')
        )
        
        # Also run motion detection to find action peaks
        motion_cmd = (
            ffmpeg.input(video_path)
            .filter('select', 'gt(scene,0.1)')  # Lower threshold for motion detection
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

def extract_motion_frames(video_path: str, start_time: float, end_time: float, output_dir: str, scene_id: str) -> List[str]:
    """Extract frames at moments of high motion/action within a scene using FFmpeg motion detection."""
    frame_paths = []
    duration = end_time - start_time
    
    try:
        # Use FFmpeg motion analysis to find high-motion moments
        import subprocess
        
        # First, detect motion vectors throughout the scene
        motion_cmd = [
            'ffmpeg', '-i', video_path, '-ss', str(start_time), '-t', str(duration),
            '-vf', 'select=gt(scene\\,0.01),showinfo', '-f', 'null', '-'
        ]
        
        result = subprocess.run(motion_cmd, capture_output=True, text=True)
        
        # Parse motion peaks from stderr
        motion_timestamps = []
        for line in result.stderr.split('\n'):
            if 'showinfo' in line and 'pts_time:' in line:
                try:
                    parts = line.split('pts_time:')
                    if len(parts) > 1:
                        rel_time = float(parts[1].split()[0])
                        abs_time = start_time + rel_time
                        if abs_time < end_time:
                            motion_timestamps.append(abs_time)
                except (ValueError, IndexError):
                    continue
        
        # Combine motion detection with strategic sampling to ensure we capture action
        key_times = []
        
        # Always include motion peaks if found
        if motion_timestamps:
            motion_times = sorted(set(motion_timestamps))[:3]  # Top 3 motion peaks
            key_times.extend(motion_times)
            typer.echo(f"  Found {len(motion_times)} motion peaks for frame extraction")
        
        # Add strategic sampling points to ensure we don't miss action
        if duration <= 3.0:
            # For short scenes, sample densely
            strategic_times = [start_time + 0.2, start_time + duration*0.5, start_time + duration - 0.2]
        elif duration <= 6.0:
            # For medium scenes like dog jumping, focus on later action (60%-90% of scene)
            strategic_times = [start_time + duration*0.2, start_time + duration*0.5, 
                             start_time + duration*0.7, start_time + duration*0.9]
        else:
            # For long scenes, sample throughout but emphasize action zones
            strategic_times = [start_time + 0.5, start_time + duration*0.3, 
                             start_time + duration*0.6, start_time + duration*0.8, 
                             start_time + duration - 0.5]
        
        # Add strategic points that aren't already covered by motion detection
        for stime in strategic_times:
            if not any(abs(stime - mtime) < 0.5 for mtime in key_times):  # Avoid duplicates within 0.5s
                key_times.append(stime)
        
        # Sort and limit to max 5 frames
        key_times = sorted(set(key_times))[:5]
        
        # Extract frames at these key moments
        for i, timestamp in enumerate(key_times):
            if timestamp < end_time:  # Ensure we don't exceed scene boundary
                frame_path = os.path.join(output_dir, f"{scene_id}_motion_frame_{i+1}.jpg")
                if extract_frame(video_path, timestamp, frame_path):
                    frame_paths.append(frame_path)
                    rel_time = timestamp - start_time
                    typer.echo(f"    Frame {i+1}: {rel_time:.1f}s into scene")
                    
        typer.echo(f"  Extracted {len(frame_paths)} motion-focused frames for analysis")
        return frame_paths
        
    except Exception as e:
        typer.echo(f"Error extracting motion frames: {e}", err=True)
        # Fallback to original method
        return extract_frames_original_method(video_path, start_time, end_time, output_dir, scene_id)

def extract_frames_original_method(video_path: str, start_time: float, end_time: float, output_dir: str, scene_id: str) -> List[str]:
    """Fallback frame extraction method."""
    frame_paths = []
    duration = end_time - start_time
    
    if duration <= 2.0:
        mid_time = (start_time + end_time) / 2
        frame_path = os.path.join(output_dir, f"{scene_id}_frame_1.jpg")
        if extract_frame(video_path, mid_time, frame_path):
            frame_paths.append(frame_path)
    elif duration <= 4.0:
        times = [start_time + 0.2, end_time - 0.2]
        for j, time in enumerate(times):
            frame_path = os.path.join(output_dir, f"{scene_id}_frame_{j+1}.jpg")
            if extract_frame(video_path, time, frame_path):
                frame_paths.append(frame_path)
    else:
        times = [start_time + 0.2, (start_time + end_time) / 2, end_time - 0.2]
        for j, time in enumerate(times):
            frame_path = os.path.join(output_dir, f"{scene_id}_frame_{j+1}.jpg")
            if extract_frame(video_path, time, frame_path):
                frame_paths.append(frame_path)
    
    return frame_paths

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
        # For short scenes, add dialogue directly to the scene
        scene_with_dialogue = scene.copy()
        scene_with_dialogue['dialogue'] = dialogue_data.get("text", "").strip()
        return [scene_with_dialogue]
    
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
            'original_duration': scene['duration'],  # Store original scene duration
            'is_chunk': True,
            'dialogue': "",  # Will be assigned later to avoid duplication
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
    
    # Split dialogue cleanly across chunks to avoid duplication
    chunks = split_dialogue_across_chunks(dialogue_data, chunks)
    
    typer.echo(f"Split {scene['id']} ({scene['duration']:.1f}s) into {len(chunks)} chunks")
    for chunk in chunks:
        if chunk['dialogue']:
            typer.echo(f"  {chunk['id']}: '{chunk['dialogue'][:50]}...'")
        else:
            typer.echo(f"  {chunk['id']}: [Visual action only]")
    
    return chunks

def split_dialogue_across_chunks(dialogue_data: Dict[str, Any], chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Split dialogue cleanly across chunks to avoid duplication."""
    if not dialogue_data.get("segments"):
        # No timestamped segments, just split text evenly
        full_text = dialogue_data.get("text", "")
        if not full_text:
            return chunks
        
        sentences = [s.strip() + "." for s in full_text.split(".") if s.strip()]
        sentences_per_chunk = max(1, len(sentences) // len(chunks))
        
        for i, chunk in enumerate(chunks):
            start_idx = i * sentences_per_chunk
            end_idx = start_idx + sentences_per_chunk if i < len(chunks) - 1 else len(sentences)
            chunk_sentences = sentences[start_idx:end_idx]
            chunk['dialogue'] = " ".join(chunk_sentences)
        
        return chunks
    
    # Assign each dialogue segment to the chunk where it primarily occurs
    for chunk in chunks:
        chunk['dialogue'] = ""
        chunk_start = chunk['start_seconds'] - chunks[0]['start_seconds']  # Relative to scene start
        chunk_end = chunk['end_seconds'] - chunks[0]['start_seconds']
        
        relevant_segments = []
        for segment in dialogue_data["segments"]:
            seg_start = segment.get("start", 0)
            seg_end = segment.get("end", 0)
            seg_midpoint = (seg_start + seg_end) / 2
            
            # Assign segment to chunk if its midpoint falls within chunk bounds
            # This prevents duplication - each segment goes to only one chunk
            if chunk_start <= seg_midpoint < chunk_end:
                relevant_segments.append(segment["text"].strip())
        
        chunk['dialogue'] = " ".join(relevant_segments).strip()
        
        # If no dialogue assigned to this chunk, add context from adjacent chunks
        if not chunk['dialogue'] and len(chunks) > 1:
            chunk['dialogue'] = "[Continuing scene with visual action]"
    
    return chunks

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

        chunk_context = ""
        if scene.get('is_chunk'):
            chunk_context = f"""
CHUNK CONTINUITY INFO:
This is chunk {scene['chunk_number']} of {scene['total_chunks']} from scene {scene['parent_scene_id']}.
Original scene duration: {scene.get('original_duration', 'unknown')}s

VISUAL CONSISTENCY REQUIREMENTS:
- Maintain consistent character appearance, clothing, and positioning
- Keep same lighting, color palette, and environmental details
- Ensure smooth visual flow from previous chunks
- Characters should maintain same age, ethnicity, and styling
- Location and camera setup should remain consistent
- This should feel like a continuous sequence, not separate clips

"""

        prompt = f"""You are a professional video analyst and Veo3 prompt engineer. You are analyzing a {scene['duration']:.1f}-second VIDEO SEQUENCE with {frame_count} frames captured at different moments.

CRITICAL INSTRUCTIONS:
- This is NOT a collection of static images - it's a TEMPORAL SEQUENCE showing motion over time
- Focus on WHAT HAPPENS between frames - the motion, action, and changes
- Describe the DYNAMIC ELEMENTS: character movement, object motion, progression of events
- Pay special attention to any jumping, falling, reaching, or rapid movements

Scene timing: {scene['start_time']} to {scene['end_time']}
Duration: {scene['duration']:.1f} seconds

{frame_analysis_text}{dialogue_section}{chunk_context}

ANALYZE THE TEMPORAL SEQUENCE USING THIS DETAILED TEMPLATE:

**A. KEY VISUALS & MAIN SUBJECTS:**
- Primary Focus: (The main subject/character of the scene)
- Objects/Elements of Note: (Detailed descriptions of props, machinery, graphics, natural elements)
- Character Details: (Age, gender, clothing, expressions, posture, ethnicity, hair, accessories)

**B. SETTING & ENVIRONMENT:**
- Location: (Specific environment - indoor/outdoor, urban/rural, specific room type)
- Time of Day/Atmosphere: (Morning, afternoon, night, weather conditions)
- Dominant Colors & Lighting: (Color palette, lighting direction, shadows, highlights)

**C. CAMERA WORK & COMPOSITION:**
- Angle(s): (Low, high, eye-level, POV, bird's-eye, Dutch angle)
- Shot Type(s): (Close-up, medium shot, long shot, establishing shot, extreme close-up)
- Movement: (Static, pan, tilt, zoom, dolly, tracking, handheld - and its emotional effect)

**D. TEMPORAL SEQUENCE & MOTION ANALYSIS:**
CRITICAL: This is a {scene['duration']:.1f}-second VIDEO SEQUENCE, not static images. Analyze the MOTION and CHANGES between frames.

- Frame-by-Frame Motion: What specific movements, actions, or changes occur between each frame
- Character Actions: Detailed description of what characters DO (walking, jumping, reaching, falling, etc.)
- Object Movement: How objects move, fall, or change position during the sequence
- Dynamic Events: Key moments of action, impact, or transformation within the scene
- Progression Arc: How the scene builds from beginning to climax to resolution

**E. AUDIO ELEMENTS:**
- Sound Effects: Environmental sounds, mechanical sounds, impact sounds
- Voiceover/Dialogue: Exact transcription and delivery style
- Music: Genre, tempo, emotional impact, when it swells/fades

**F. VISUAL STYLE & AESTHETICS:**
- Overall Look: (Realistic, stylized, cinematic, documentary, commercial, artistic)
- Film Stock/Quality: (Digital, film grain, high contrast, soft/sharp focus)
- Color Grading: (Warm/cool tones, saturation, contrast levels)

**G. NARRATIVE ROLE & EMOTIONAL IMPACT:**
- Scene Purpose: Why this scene exists in the video
- Mood: How this scene makes viewers feel
- Target Audience: Who this seems designed for

Create a COMPREHENSIVE Veo3 prompt that captures every visual detail for perfect recreation.

Return ONLY valid JSON:

```json
{{
    "description": "Brief 1-sentence summary of scene content",
    "detailed_analysis": "Comprehensive scene breakdown following the template above with specific details about subjects, setting, camera work, actions, audio, visual style, and narrative purpose - minimum 300 words",
    "veo3_prompt": "Complete Veo3 generation prompt in this format: 'CLIP #{scene.get('id', '1')}: [Scene Title] ({scene['duration']:.1f} seconds): Subject: [detailed subject description] Visual Style & Cinematography: [film style keywords] Shot & Camera: [detailed camera instructions] Lighting & Atmosphere: [lighting and mood] Audio: Soundscape: [sound effects] Music: [music style] Narration: [exact voiceover text if any] - ULTRA DETAILED 400+ word prompt ready for Veo3'",
    "technical_specs": "Camera specs, lens types, lighting setup, color grading approach, and audio design",
    "diagnostics": {{
        "text_heavy": {str('text' in str(scene).lower() or any('text' in str(f).lower() for f in frame_paths)).lower()},
        "camera_motion": true,
        "complex_characters": {str('character' in dialogue.lower() or len(frame_paths) > 1).lower()},
        "rapid_motion": {str(scene['duration'] < 3.0).lower()},
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
            
            # Validate required fields exist and map old field names to new ones
            if 'veo3_prompt' not in analysis and 'scene_prompt' not in analysis:
                raise ValueError("Missing required prompt field in JSON response")
            
            # Map new field names to old ones for backward compatibility
            if 'veo3_prompt' in analysis and 'scene_prompt' not in analysis:
                analysis['scene_prompt'] = analysis['veo3_prompt']
            if 'technical_specs' in analysis and 'cinematic_notes' not in analysis:
                analysis['cinematic_notes'] = analysis['technical_specs']
                
        except (json.JSONDecodeError, ValueError) as e:
            typer.echo(f"JSON parsing failed for {scene['id']}: {e}", err=True)
            typer.echo("Raw response:", err=True)
            typer.echo(response_text[:500] + "..." if len(response_text) > 500 else response_text, err=True)
            
            # Create detailed fallback using the raw response (no truncation)
            analysis = {
                "description": f"Scene analysis for {scene['duration']:.1f}s video segment",
                "detailed_analysis": response_text.strip()[:1000] + "..." if len(response_text) > 1000 else response_text.strip(),
                "scene_prompt": response_text.strip(),  # Keep full response, don't truncate
                "veo3_prompt": f"CLIP #{scene.get('id', '1')}: Scene ({scene['duration']:.1f} seconds): {response_text[:400]}...",
                "cinematic_notes": "Raw analysis provided - JSON parsing failed but full content preserved",
                "technical_specs": "Technical specifications not available due to parsing error",
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
            "detailed_analysis": f"Analysis failed due to error: {str(e)}",
            "scene_prompt": f"Generate a {scene['duration']:.1f}-second video scene",
            "veo3_prompt": f"CLIP #{scene.get('id', '1')}: Scene ({scene['duration']:.1f} seconds): Generate a video scene showing the content from the original frames.",
            "cinematic_notes": "Technical specifications not available due to analysis error",
            "technical_specs": "Analysis failed - technical specifications unavailable",
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
    # Claude 3.5 Sonnet pricing for scene analysis
    tokens_per_scene = 1200  # Higher estimate for detailed analysis with images
    cost_per_1k_tokens = 0.003  # Claude 3.5 Sonnet pricing
    
    total_tokens = len(scenes) * tokens_per_scene
    claude_cost = (total_tokens / 1000) * cost_per_1k_tokens
    
    # Veo3 cost estimation - all clips are 8s regardless of original duration
    total_clips = len(scenes)
    clip_duration = 8.0  # Fixed by API
    total_duration = total_clips * clip_duration
    
    # fal.ai Veo3 pricing: $0.75/second (standard) or $0.40/second (fast)
    veo3_standard_cost = total_duration * 0.75
    veo3_fast_cost = total_duration * 0.40
    
    return {
        'claude_tokens': total_tokens,
        'claude_cost_usd': claude_cost,
        'total_clips': total_clips,
        'total_duration_seconds': total_duration,
        'veo3_standard_cost_usd': veo3_standard_cost,
        'veo3_fast_cost_usd': veo3_fast_cost,
        'total_estimated_standard_usd': claude_cost + veo3_standard_cost,
        'total_estimated_fast_usd': claude_cost + veo3_fast_cost
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
    typer.echo(f"Video clips to generate: {cost_estimate['total_clips']}")
    typer.echo(f"Total clip duration: {cost_estimate['total_duration_seconds']:.1f}s (8s per clip)")
    typer.echo(f"Claude analysis cost: ${cost_estimate['claude_cost_usd']:.3f} ({cost_estimate['claude_tokens']:,} tokens)")
    typer.echo(f"Veo3 Standard cost: ${cost_estimate['veo3_standard_cost_usd']:.2f} ($0.75/second)")
    typer.echo(f"Veo3 Fast cost: ${cost_estimate['veo3_fast_cost_usd']:.2f} ($0.40/second)")
    typer.echo(f"Total (Standard): ${cost_estimate['total_estimated_standard_usd']:.2f}")
    typer.echo(f"Total (Fast): ${cost_estimate['total_estimated_fast_usd']:.2f}")
    typer.echo(f"💡 Tip: Use --fast flag in generation to save ${cost_estimate['veo3_standard_cost_usd'] - cost_estimate['veo3_fast_cost_usd']:.2f}!")
    
    if estimate_only:
        return
    
    # Initialize Claude client
    client = get_anthropic_client()
    
    # Analyze each scene
    analyzed_scenes = []
    
    with tempfile.TemporaryDirectory() as temp_dir:
        for i, scene in enumerate(scenes):
            typer.echo(f"Analyzing scene {i+1}/{len(scenes)}: {scene['id']}")
            
            # Extract frames using motion detection to capture dynamic action
            frame_paths = extract_motion_frames(video, scene['start_seconds'], scene['end_seconds'], temp_dir, scene['id'])
            
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
                    # Dialogue is already cleanly assigned to chunks to avoid duplication
                    chunk_dialogue = chunk.get('dialogue', "")
                    
                    # For chunks, we need to extract frames specific to the chunk timerange
                    if chunk.get('is_chunk'):
                        # Extract frames for this specific chunk using motion detection
                        chunk_frame_paths = extract_motion_frames(video, chunk['start_seconds'], chunk['end_seconds'], temp_dir, chunk['id'])
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