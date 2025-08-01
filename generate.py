#!/usr/bin/env python3

import os
import sys
import json
import time
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional
import requests
import typer
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

FAL_API_BASE = "https://fal.run/fal-ai/veo3"
WAN_API_BASE = "https://fal.run/fal-ai/wan/v2.2-a14b/text-to-video"

def get_fal_headers() -> Dict[str, str]:
    """Get headers for fal.ai API requests."""
    api_key = os.getenv("FAL_API_KEY")
    if not api_key:
        typer.echo("Error: FAL_API_KEY not found in environment", err=True)
        raise typer.Exit(1)
    
    return {
        "Authorization": f"Key {api_key}",
        "Content-Type": "application/json"
    }

def generate_scene_hash(scene: Dict[str, Any]) -> str:
    """Generate a hash for scene to check if already generated."""
    content = f"{scene['id']}_{scene['prompt']}_{scene['duration']}"
    return hashlib.md5(content.encode()).hexdigest()[:8]

def check_existing_clip(scene_id: str, output_dir: str) -> Optional[str]:
    """Check if clip already exists for this scene."""
    possible_paths = [
        os.path.join(output_dir, f"{scene_id}.mp4"),
        os.path.join(output_dir, f"{scene_id}_generated.mp4")
    ]
    
    for path in possible_paths:
        if os.path.exists(path):
            return path
    
    return None

def optimize_scene_combinations(scenes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Combine short scenes together to maximize 8-second clip usage and reduce costs."""
    optimized_scenes = []
    current_group = []
    current_duration = 0.0
    max_duration = 7.5  # Leave 0.5s buffer
    
    typer.echo(f"\n🎯 Optimizing scene combinations...")
    
    for scene in scenes:
        duration = scene['duration']
        
        # Skip already-chunked scenes (they're handled separately)
        if scene.get('is_chunk'):
            if current_group:
                # Finalize current group before adding chunk
                optimized_scenes.append(create_combined_scene(current_group))
                current_group = []
                current_duration = 0.0
            optimized_scenes.append(scene)
            continue
        
        # If scene is >8s, it needs chunking (handle separately)
        if duration > 8.0:
            if current_group:
                # Finalize current group before long scene
                optimized_scenes.append(create_combined_scene(current_group))
                current_group = []
                current_duration = 0.0
            optimized_scenes.append(scene)
            continue
        
        # Try to add scene to current group
        if current_duration + duration <= max_duration:
            current_group.append(scene)
            current_duration += duration
        else:
            # Current group is full, finalize it and start new group
            if current_group:
                optimized_scenes.append(create_combined_scene(current_group))
            current_group = [scene]
            current_duration = duration
    
    # Finalize any remaining group
    if current_group:
        optimized_scenes.append(create_combined_scene(current_group))
    
    # Show optimization results
    original_clips = len(scenes)
    optimized_clips = len(optimized_scenes)
    savings = (original_clips - optimized_clips) * 6.0  # Assume $6 per clip
    
    typer.echo(f"   Original: {original_clips} clips → Optimized: {optimized_clips} clips")
    typer.echo(f"   Estimated savings: ${savings:.2f}")
    
    return optimized_scenes

def create_combined_scene(scenes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create a combined scene from multiple short scenes."""
    if len(scenes) == 1:
        return scenes[0]  # No combination needed
    
    # Create combined scene metadata
    combined_id = "_".join([s['id'] for s in scenes])
    total_duration = sum(s['duration'] for s in scenes)
    start_time = scenes[0]['start_time']
    end_time = scenes[-1]['end_time']
    
    # Combine scene prompts
    combined_prompt = create_multi_scene_prompt(scenes)
    
    combined_scene = {
        'id': f"combined_{combined_id}",
        'original_scenes': [s['id'] for s in scenes],
        'scene_count': len(scenes),
        'start_time': start_time,
        'end_time': end_time,
        'start_seconds': scenes[0]['start_seconds'],
        'end_seconds': scenes[-1]['end_seconds'],
        'duration': total_duration,
        'is_combined': True,
        'scene_prompt': combined_prompt,
        'cinematic_notes': combine_cinematic_notes(scenes),
        'individual_scenes': scenes,  # Store original scenes for splitting later
        'diagnostics': {
            'text_heavy': any(s.get('diagnostics', {}).get('text_heavy', False) for s in scenes),
            'camera_motion': True,  # Multi-scene will have motion
            'complex_characters': any(s.get('diagnostics', {}).get('complex_characters', False) for s in scenes),
            'rapid_motion': True,  # Scene transitions create rapid motion
            'duration_warning': False  # Combined scenes are <8s
        }
    }
    
    typer.echo(f"   Combined {len(scenes)} scenes: {', '.join([s['id'] for s in scenes])} → {combined_scene['id']} ({total_duration:.1f}s)")
    
    return combined_scene

def create_multi_scene_prompt(scenes: List[Dict[str, Any]]) -> str:
    """Create a combined prompt for multiple sequential scenes."""
    scene_descriptions = []
    
    for i, scene in enumerate(scenes):
        duration = scene['duration']
        prompt = scene.get('scene_prompt', scene.get('prompt', ''))
        dialogue = scene.get('dialogue', '')
        
        timing = f"[{duration:.1f}s]"
        scene_desc = f"Scene {i+1} {timing}: {prompt[:200]}..."
        if dialogue:
            scene_desc += f" Dialogue: \"{dialogue}\""
        scene_descriptions.append(scene_desc)
    
    total_duration = sum(s['duration'] for s in scenes)
    
    combined_prompt = f"""MULTI-SCENE SEQUENCE - {total_duration:.1f} seconds total

This is a continuous sequence combining {len(scenes)} sequential scenes with smooth transitions:

{chr(10).join(scene_descriptions)}

TRANSITION REQUIREMENTS:
- Seamless flow between scenes with natural camera movements
- Maintain visual continuity in lighting and color palette
- Characters should move naturally between scenes
- Audio/dialogue should flow naturally across scene boundaries
- Each scene transition should feel cinematic, not abrupt

Create a cohesive {total_duration:.1f}-second sequence that captures all these moments as one continuous shot."""
    
    return combined_prompt

def combine_cinematic_notes(scenes: List[Dict[str, Any]]) -> str:
    """Combine cinematic notes from multiple scenes."""
    notes = []
    for scene in scenes:
        if scene.get('cinematic_notes'):
            notes.append(f"{scene['id']}: {scene['cinematic_notes'][:100]}...")
    
    return "Combined scenes: " + " | ".join(notes) if notes else "Multi-scene sequence with smooth transitions"

def split_combined_clip(combined_scene: Dict[str, Any], clip_path: str, output_dir: str) -> List[Dict[str, Any]]:
    """Split a combined clip back into individual scene clips."""
    if not combined_scene.get('is_combined'):
        return []  # Not a combined scene
    
    individual_scenes = combined_scene.get('individual_scenes', [])
    if not individual_scenes:
        return []
    
    results = []
    current_offset = 0.0
    
    try:
        import ffmpeg
        
        for scene in individual_scenes:
            scene_duration = scene['duration']
            output_path = os.path.join(output_dir, f"{scene['id']}.mp4")
            
            # Extract segment from combined clip
            (
                ffmpeg
                .input(clip_path, ss=current_offset, t=scene_duration)
                .output(output_path, vcodec='libx264', acodec='aac')
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True, quiet=True)
            )
            
            if os.path.exists(output_path):
                results.append({
                    'scene_id': scene['id'],
                    'output_path': output_path,
                    'success': True,
                    'duration': scene_duration,
                    'source': 'split_from_combined'
                })
                typer.echo(f"   Split → {scene['id']}.mp4 ({scene_duration:.1f}s)")
            else:
                results.append({
                    'scene_id': scene['id'],
                    'success': False,
                    'error': 'Failed to split segment'
                })
            
            current_offset += scene_duration
        
    except Exception as e:
        typer.echo(f"Error splitting combined clip: {e}", err=True)
        for scene in individual_scenes:
            results.append({
                'scene_id': scene['id'],
                'success': False,
                'error': f'Split failed: {str(e)}'
            })
    
    return results

def stitch_scene_chunks(chunk_paths: List[str], output_path: str, overlap_duration: float = 1.0) -> bool:
    """Stitch multiple scene chunks together with crossfade transitions."""
    try:
        import ffmpeg
        
        if len(chunk_paths) < 2:
            return False
        
        # Build ffmpeg command for crossfade stitching
        inputs = []
        
        # Load all input videos
        for i, path in enumerate(chunk_paths):
            inputs.append(ffmpeg.input(path))
        
        # Create crossfade between each pair of videos
        current = inputs[0]
        
        for i in range(1, len(inputs)):
            next_input = inputs[i]
            
            # Crossfade transition
            current = ffmpeg.filter(
                [current, next_input],
                'xfade',
                transition='fade',
                duration=overlap_duration,
                offset=7.0 - overlap_duration  # Start fade before end of previous clip
            )
        
        # Output final stitched video
        out = ffmpeg.output(current, output_path, vcodec='libx264', acodec='aac')
        ffmpeg.run(out, overwrite_output=True, capture_stdout=True, capture_stderr=True, quiet=True)
        
        return os.path.exists(output_path)
        
    except Exception as e:
        typer.echo(f"Error stitching chunks: {e}", err=True)
        return False

def submit_veo3_request(prompt: str, duration: float, use_fast: bool = False, reference_image_path: str = None, max_retries: int = 3) -> Dict[str, Any]:
    """Submit generation request to Veo3 via fal.ai with retry logic."""
    headers = get_fal_headers()
    
    # Ensure duration doesn't exceed 8 seconds and format as required string
    duration_capped = min(duration, 8.0)
    
    # Veo3 API currently only accepts "8s" as duration
    # According to the API error, only "8s" is permitted
    duration_str = "8s"
    
    # Check prompt length (some APIs have limits)
    if len(prompt) > 4000:
        typer.echo(f"⚠️ Warning: Prompt is {len(prompt)} chars, might be too long for API")
    
    payload = {
        "prompt": prompt,
        "duration": duration_str,
        "resolution": "720p",  # Options: 720p, 1080p
        "quality": "medium",   # Options: low, medium, high
        "generate_audio": True,  # Enable audio generation including narration/dialogue
        # Add consistency parameters if supported
        "seed": 42,  # Fixed seed for consistent style
    }
    
    # Handle image-to-video vs text-to-video
    if reference_image_path:
        # Convert reference image to data URI and use image-to-video endpoint
        image_url = upload_reference_image(reference_image_path)
        if not image_url:
            return {"error": "Failed to convert reference image"}
        payload["image_url"] = image_url
    
    last_error = None
    
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                typer.echo(f"   Retry {attempt}/{max_retries - 1}...")
                time.sleep(5 * attempt)  # Exponential backoff
            
            # Choose endpoint based on fast flag and image-to-video mode
            if reference_image_path:
                if use_fast:
                    endpoint = f"{FAL_API_BASE}/fast/image-to-video"
                else:
                    endpoint = f"{FAL_API_BASE}/image-to-video"
            else:
                endpoint = f"{FAL_API_BASE}/fast" if use_fast else FAL_API_BASE
            
            
            response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=180  # Increased to 3 minutes
            )
            
            if response.status_code == 200:
                result = response.json()
                return result
            else:
                error_details = response.text
                last_error = {
                    "error": f"API request failed with status {response.status_code}",
                    "details": error_details
                }
                typer.echo(f"   API Error {response.status_code} on attempt {attempt + 1}", err=True)
                if response.status_code == 422:
                    typer.echo(f"   Validation Error: {error_details[:200]}...", err=True)
                if attempt == max_retries - 1:  # Last attempt
                    return last_error
                    
        except requests.exceptions.Timeout as e:
            last_error = {"error": f"Request timed out: {str(e)}"}
            typer.echo(f"   ⏱️  Timeout on attempt {attempt + 1}")
            if attempt == max_retries - 1:
                return last_error
                
        except requests.exceptions.RequestException as e:
            last_error = {"error": f"Request failed: {str(e)}"}
            typer.echo(f"   🔌 Network error on attempt {attempt + 1}: {str(e)}")
            if attempt == max_retries - 1:
                return last_error
    
    return last_error or {"error": "All retry attempts exhausted"}

def submit_wan_request(prompt: str, duration: float, max_retries: int = 3) -> Dict[str, Any]:
    """Submit generation request to Wan 2.2 A14B via fal.ai with retry logic."""
    headers = get_fal_headers()
    
    # Wan 2.2 supports flexible duration up to 6 seconds
    duration_capped = min(duration, 6.0)
    
    # Calculate frames based on duration (24 fps default)
    # 81 frames = ~3.4s, 121 frames = ~5s at 24fps
    target_frames = int(duration_capped * 24)
    num_frames = max(81, min(121, target_frames))  # Clamp between 81-121
    
    payload = {
        "prompt": prompt,
        "num_frames": num_frames,
        "frames_per_second": 24,
        "resolution": "720p",  # Options: 480p, 580p, 720p
        "aspect_ratio": "16:9",  # Options: 16:9, 9:16, 1:1
        "num_inference_steps": 40,  # Default quality
        "guidance_scale": 3.5,
        "interpolator_model": "film",  # For smooth motion
        "seed": 42,  # Fixed seed for consistent style
    }
    
    last_error = None
    
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                typer.echo(f"   Retry {attempt}/{max_retries - 1}...")
                time.sleep(5 * attempt)  # Exponential backoff
            
            response = requests.post(
                WAN_API_BASE,
                headers=headers,
                json=payload,
                timeout=180  # 3 minutes timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                return result
            else:
                last_error = {
                    "error": f"API request failed with status {response.status_code}",
                    "details": response.text
                }
                typer.echo(f"   API Error {response.status_code} on attempt {attempt + 1}", err=True)
                if attempt == max_retries - 1:
                    return last_error
                    
        except requests.exceptions.Timeout as e:
            last_error = {"error": f"Request timed out: {str(e)}"}
            typer.echo(f"   ⏱️  Timeout on attempt {attempt + 1}")
            if attempt == max_retries - 1:
                return last_error
                
        except requests.exceptions.RequestException as e:
            last_error = {"error": f"Request failed: {str(e)}"}
            typer.echo(f"   🔌 Network error on attempt {attempt + 1}: {str(e)}")
            if attempt == max_retries - 1:
                return last_error
    
    return last_error or {"error": "All retry attempts exhausted"}

def poll_generation_status(request_id: str, max_wait_time: int = 300) -> Dict[str, Any]:
    """Poll fal.ai for generation completion."""
    headers = get_fal_headers()
    status_url = f"{FAL_API_BASE}/requests/{request_id}"
    
    start_time = time.time()
    
    with tqdm(desc=f"Generating clip", unit="s") as pbar:
        while time.time() - start_time < max_wait_time:
            try:
                response = requests.get(status_url, headers=headers, timeout=30)
                
                if response.status_code == 200:
                    result = response.json()
                    
                    if result.get("status") == "completed":
                        return result
                    elif result.get("status") == "failed":
                        return {"error": result.get("error", "Generation failed")}
                    
                    # Still processing
                    elapsed = int(time.time() - start_time)
                    pbar.update(1)
                    pbar.set_description(f"Generating clip ({elapsed}s)")
                    
                else:
                    typer.echo(f"Status check failed: {response.status_code}", err=True)
                
            except requests.exceptions.RequestException as e:
                typer.echo(f"Status check error: {e}", err=True)
            
            time.sleep(5)  # Poll every 5 seconds
    
    return {"error": "Generation timeout"}

def upload_reference_image(image_path: str) -> str:
    """Convert reference image to data URI for fal.ai API."""
    import base64
    import mimetypes
    
    try:
        # Get the MIME type
        mime_type, _ = mimetypes.guess_type(image_path)
        if not mime_type or not mime_type.startswith('image/'):
            mime_type = 'image/jpeg'  # Default fallback
        
        # Read and encode the image
        with open(image_path, 'rb') as f:
            image_data = f.read()
            encoded_data = base64.b64encode(image_data).decode('utf-8')
            
        # Check image size limits (fal.ai has 8MB limit)
        image_size_mb = len(image_data) / (1024 * 1024)
        if image_size_mb > 7:  # Leave buffer
            typer.echo(f"⚠️ Warning: Image is {image_size_mb:.1f}MB, might be too large for API")
        
        # Create data URI
        data_uri = f"data:{mime_type};base64,{encoded_data}"
        
        typer.echo(f"   📸 Converted image to data URI ({len(encoded_data)} chars, {image_size_mb:.1f}MB)")
        return data_uri
            
    except Exception as e:
        typer.echo(f"Error converting reference image: {e}", err=True)
        return None

def extract_reference_frame_for_scene(scene: Dict[str, Any], output_dir: str) -> Optional[str]:
    """Extract a reference frame for a scene on-demand."""
    try:
        import subprocess
        
        # Get scene timing info
        start_seconds = scene.get('start_seconds', 0)
        end_seconds = scene.get('end_seconds', start_seconds + scene.get('duration', 3))
        duration = scene.get('duration', 3)
        
        # Choose frame timestamp (70% through the scene for action)
        frame_time = start_seconds + (duration * 0.7)
        
        # Create reference frame filename
        scene_id = scene['id']
        frame_filename = f"{scene_id}_reference.jpg" 
        frame_path = os.path.join(output_dir, frame_filename)
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        # Extract frame using ffmpeg (assuming input.mp4 is available)
        video_path = "input.mp4"  # This should ideally come from scene metadata
        if not os.path.exists(video_path):
            typer.echo(f"⚠️ Source video not found: {video_path}")
            return None
            
        cmd = [
            'ffmpeg', '-i', video_path,
            '-ss', str(frame_time),
            '-vframes', '1',
            '-q:v', '2',
            '-s', '1280x720',  # Ensure 720p+ resolution
            frame_path,
            '-y'  # Overwrite if exists
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0 and os.path.exists(frame_path):
            return frame_path
        else:
            typer.echo(f"⚠️ Frame extraction failed: {result.stderr[:100]}")
            return None
            
    except Exception as e:
        typer.echo(f"⚠️ Error extracting reference frame: {e}")
        return None

def download_generated_video(video_url: str, output_path: str) -> bool:
    """Download the generated video from fal.ai."""
    try:
        response = requests.get(video_url, stream=True, timeout=120)
        response.raise_for_status()
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        # Verify file was downloaded
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return True
        else:
            typer.echo(f"Error: Downloaded file is empty or missing", err=True)
            return False
            
    except Exception as e:
        typer.echo(f"Error downloading video: {e}", err=True)
        return False

def generate_single_scene(scene: Dict[str, Any], output_dir: str, skip_existing: bool = True, use_fast: bool = False, model: str = "veo3", use_reference_image: bool = False) -> Dict[str, Any]:
    """Generate a single scene clip."""
    scene_id = scene['id']
    output_path = os.path.join(output_dir, f"{scene_id}.mp4")
    
    # Check if already exists
    if skip_existing:
        existing_path = check_existing_clip(scene_id, output_dir)
        if existing_path:
            typer.echo(f"✅ Skipping {scene_id} (already exists: {existing_path})")
            return {
                "scene_id": scene_id,
                "status": "skipped",
                "output_path": existing_path,
                "cost": 0
            }
    
    # Get the detailed prompt (no length limit now for better quality)
    # Handle both old and new field names for backward compatibility
    prompt = scene.get('scene_prompt', scene.get('prompt', 'Generate video scene'))
    if len(prompt) > 2000:
        typer.echo(f"📝 {scene_id}: Long detailed prompt ({len(prompt)} chars)")
    else:
        typer.echo(f"📝 {scene_id}: Detailed prompt ({len(prompt)} chars)")
    
    # Get reference image path if using image-to-video
    reference_image_path = None
    if use_reference_image and model == "veo3":
        # Look for extracted frames for this scene
        frame_paths = scene.get('frame_paths', [])
        if frame_paths:
            # Use the best motion frame (typically the last one in our extraction logic)
            reference_image_path = frame_paths[-1] if isinstance(frame_paths, list) else frame_paths
            typer.echo(f"📸 Using reference image: {os.path.basename(reference_image_path)}")
        else:
            # Extract frame on-demand if not stored in JSON
            typer.echo(f"📸 Extracting reference frame for {scene_id}...")
            reference_image_path = extract_reference_frame_for_scene(scene, output_dir)
            if reference_image_path:
                typer.echo(f"📸 Using reference image: {os.path.basename(reference_image_path)}")
            else:
                typer.echo(f"⚠️ Failed to extract reference frame for {scene_id}, falling back to text-to-video")
    
    # Choose API and duration based on model
    if model == "wan2.2":
        actual_duration = min(scene.get('duration', 3.0), 6.0)  # Wan 2.2 max 6s
        typer.echo(f"🎬 Generating {scene_id} ({actual_duration:.1f}s - Wan 2.2)...")
        result = submit_wan_request(prompt, actual_duration, max_retries=2)
    else:
        # Veo3 model (default)
        actual_duration = 8.0  # Veo3 fixed duration
        generation_mode = "Image-to-Video" if reference_image_path else "Text-to-Video"
        typer.echo(f"🎬 Generating {scene_id} ({actual_duration:.1f}s - Veo3 {generation_mode})...")
        result = submit_veo3_request(prompt, actual_duration, use_fast, reference_image_path, max_retries=2)
    
    if "error" in result:
        return {
            "scene_id": scene_id,
            "status": "failed",
            "error": result["error"],
            "cost": 0
        }
    
    # Check if this is a direct response (synchronous) or needs polling (asynchronous)
    if "video" in result and "url" in result["video"]:
        # Direct/synchronous response - video is ready immediately
        video_url = result["video"]["url"]
        typer.echo(f"✅ Video generated synchronously")
    elif "request_id" in result:
        # Asynchronous response - need to poll for completion
        request_id = result["request_id"]
        typer.echo(f"Polling for completion (request ID: {request_id})")
        
        final_result = poll_generation_status(request_id)
        
        if "error" in final_result:
            return {
                "scene_id": scene_id,
                "status": "failed",
                "error": final_result["error"],
                "cost": 0
            }
        
        video_url = final_result.get("video_url")
        if not video_url:
            return {
                "scene_id": scene_id,
                "status": "failed",
                "error": "No video URL in polling response",
                "cost": 0
            }
    else:
        return {
            "scene_id": scene_id,
            "status": "failed",
            "error": "Unexpected API response format",
            "cost": 0
        }
    
    if download_generated_video(video_url, output_path):
        # Calculate cost based on model
        if model == "wan2.2":
            estimated_cost = actual_duration * 0.08  # $0.08 per second for Wan 2.2
            duration_display = f"{actual_duration:.1f}s"
        else:
            # Veo3 pricing
            cost_per_second = 0.40 if use_fast else 0.75
            estimated_cost = actual_duration * cost_per_second
            duration_display = f"{actual_duration:.1f}s"
        
        actual_cost = result.get("cost", estimated_cost)  # Use API result if available
        
        typer.echo(f"✅ Generated {scene_id}: {output_path} ({duration_display})")
        return {
            "scene_id": scene_id,
            "status": "completed",
            "output_path": output_path,
            "cost": actual_cost,
            "duration": actual_duration
        }
    else:
        return {
            "scene_id": scene_id,
            "status": "failed",
            "error": "Failed to download video",
            "cost": 0
        }

def save_generation_log(results: List[Dict[str, Any]], log_path: str):
    """Save generation results to log file."""
    log_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_scenes": len(results),
        "completed": len([r for r in results if r["status"] == "completed"]),
        "failed": len([r for r in results if r["status"] == "failed"]),
        "skipped": len([r for r in results if r["status"] == "skipped"]),
        "total_cost": sum(r.get("cost", 0) for r in results),
        "results": results
    }
    
    with open(log_path, 'w') as f:
        json.dump(log_data, f, indent=2)

def generate_command(
    prompts: str = typer.Argument(..., help="JSON file with scene prompts"),
    output_dir: str = typer.Option("./clips/", "--output-dir", help="Output directory for clips"),
    skip_existing: bool = typer.Option(True, "--skip-existing/--overwrite", help="Skip existing clips"),
    max_scenes: Optional[int] = typer.Option(None, "--max-scenes", help="Limit number of scenes to generate"),
    scenes: Optional[str] = typer.Option(None, "--scenes", help="Specific scene IDs to generate (comma-separated, e.g., 'scene_01,scene_03,scene_05')"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be generated without actually doing it"),
    fast: bool = typer.Option(False, "--fast", help="Use Veo3 Fast model (cheaper: $0.40/s vs $0.75/s)"),
    model: str = typer.Option("veo3", "--model", help="Generation model: 'veo3' or 'wan2.2'"),
    use_reference_image: bool = typer.Option(False, "--use-reference-image", help="Use extracted frames as reference images for better consistency (Veo3 only)")
):
    """Generate video clips from scene prompts using AI video generation."""
    
    # Validate model selection
    supported_models = ["veo3", "wan2.2"]
    if model not in supported_models:
        typer.echo(f"Error: Unsupported model '{model}'. Supported models: {', '.join(supported_models)}", err=True)
        raise typer.Exit(1)
    
    if not os.path.exists(prompts):
        typer.echo(f"Error: Prompts file not found: {prompts}", err=True)
        raise typer.Exit(1)
    
    # Load prompts
    try:
        with open(prompts, 'r') as f:
            data = json.load(f)
    except Exception as e:
        typer.echo(f"Error loading prompts file: {e}", err=True)
        raise typer.Exit(1)
    
    all_scenes = data.get('scenes', [])
    if not all_scenes:
        typer.echo("Error: No scenes found in prompts file", err=True)
        raise typer.Exit(1)
    
    # Filter scenes based on parameters
    if scenes:
        # Parse specific scene IDs
        requested_scene_ids = [s.strip() for s in scenes.split(',')]
        filtered_scenes = []
        
        for scene_id in requested_scene_ids:
            scene = next((s for s in all_scenes if s['id'] == scene_id), None)
            if scene:
                filtered_scenes.append(scene)
            else:
                typer.echo(f"Warning: Scene '{scene_id}' not found in prompts file", err=True)
        
        if not filtered_scenes:
            typer.echo("Error: No valid scenes found from the specified scene IDs", err=True)
            raise typer.Exit(1)
        
        scenes = filtered_scenes
        typer.echo(f"Selected specific scenes: {', '.join(s['id'] for s in scenes)}")
        
    elif max_scenes:
        # Limit to first N scenes
        scenes = all_scenes[:max_scenes]
        typer.echo(f"Limited to first {max_scenes} scenes")
    else:
        # Use all scenes
        scenes = all_scenes
    
    # Optimize scene combinations to reduce costs
    scenes = optimize_scene_combinations(scenes)
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Show generation plan - calculate actual costs based on model
    if model == "wan2.2":
        # Wan 2.2: Flexible duration, $0.08/second, visual only
        total_duration = sum(min(scene['duration'], 6.0) for scene in scenes)  # Max 6s per clip
        cost_per_second = 0.08
        model_name = "Wan 2.2 A14B"
        audio_note = "visual only"
        tip_message = f"💡 Wan 2.2 is 90% cheaper than Veo3 but doesn't generate audio"
    else:
        # Veo3: Fixed 8-second clips, with audio
        total_duration = len(scenes) * 8.0  # All clips are 8 seconds (API fixed)
        cost_per_second = 0.40 if fast else 0.75
        model_name = "Veo3 Fast" if fast else "Standard Veo3"
        audio_note = "with audio"
        tip_message = f"💡 Use --fast flag for cheaper generation (${0.40:.2f}/s vs ${0.75:.2f}/s)" if not fast else f"💡 Use --model wan2.2 for 90% cost savings (visual only)"
    
    estimated_cost = total_duration * cost_per_second
    
    typer.echo(f"\n🎬 Generation Plan:")
    typer.echo(f"Scenes to generate: {len(scenes)}")
    if model == "wan2.2":
        typer.echo(f"Total duration: {total_duration:.1f}s (flexible duration, max 6s per clip)")
    else:
        typer.echo(f"Total duration: {total_duration:.1f}s (all clips are 8s - API fixed)")
    typer.echo(f"Estimated cost: ${estimated_cost:.2f} (${cost_per_second:.2f}/second {audio_note})")
    typer.echo(f"Model: {model_name}")
    typer.echo(tip_message)
    typer.echo(f"Output directory: {output_dir}")
    
    if dry_run:
        typer.echo("\n📋 Dry run - scenes that would be generated:")
        for scene in scenes:
            existing = check_existing_clip(scene['id'], output_dir)
            status = "EXISTS" if existing else "GENERATE"
            
            if model == "wan2.2":
                scene_duration = min(scene.get('duration', 3.0), 6.0)
                duration_desc = f"{scene_duration:.1f}s - flexible duration"
            else:
                duration_desc = "8s - API fixed duration"
            
            typer.echo(f"  {scene['id']}: {status} ({duration_desc})")
        return
    
    # Confirm before proceeding
    if not typer.confirm("\nProceed with generation?"):
        typer.echo("Generation cancelled")
        return
    
    # Generate clips
    results = []
    total_cost = 0
    
    typer.echo(f"\n🚀 Starting generation...")
    
    # Group scenes by parent (for chunk stitching)
    scene_groups = {}
    for scene in scenes:
        parent_id = scene.get('parent_scene_id', scene['id'])
        if parent_id not in scene_groups:
            scene_groups[parent_id] = []
        scene_groups[parent_id].append(scene)
    
    for i, scene in enumerate(scenes, 1):
        typer.echo(f"\n[{i}/{len(scenes)}] Processing {scene['id']}...")
        
        result = generate_single_scene(scene, output_dir, skip_existing, fast, model, use_reference_image)
        results.append(result)
        total_cost += result.get('cost', 0)
        
        # If this was a combined scene, split it back into individual clips
        if scene.get('is_combined') and result.get('success') and result.get('output_path'):
            typer.echo(f"🔗 Splitting combined clip into {scene['scene_count']} individual scenes...")
            split_results = split_combined_clip(scene, result['output_path'], output_dir)
            results.extend(split_results)
    
    # Auto-stitch chunks for scenes that were split
    typer.echo(f"\n🎬 Checking for scenes to stitch...")
    stitched_results = []
    
    for parent_id, group in scene_groups.items():
        if len(group) > 1 and all(s.get('is_chunk') for s in group):
            # This is a split scene with multiple chunks
            typer.echo(f"🔗 Stitching {len(group)} chunks for {parent_id}...")
            
            # Sort chunks by chunk number
            group.sort(key=lambda x: x.get('chunk_number', 0))
            
            # Get paths of generated clips
            chunk_paths = []
            for chunk in group:
                result = next((r for r in results if r['scene_id'] == chunk['id']), None)
                if result and result.get('success') and result.get('output_path'):
                    chunk_paths.append(result['output_path'])
            
            if len(chunk_paths) == len(group):
                # All chunks generated successfully, stitch them
                stitched_path = os.path.join(output_dir, f"{parent_id}_stitched.mp4")
                if stitch_scene_chunks(chunk_paths, stitched_path, overlap_duration=1.0):
                    stitched_results.append({
                        'parent_scene_id': parent_id,
                        'chunks_used': len(chunk_paths),
                        'output_path': stitched_path,
                        'success': True
                    })
                    typer.echo(f"✅ Stitched {parent_id} -> {stitched_path}")
                else:
                    typer.echo(f"❌ Failed to stitch {parent_id}")
            else:
                typer.echo(f"⚠️ Cannot stitch {parent_id} - some chunks failed to generate")
        
        # Brief pause between requests to be nice to the API
        if i < len(scenes):
            time.sleep(2)
    
    # Save generation log
    log_path = os.path.join(output_dir, "generation_log.json")
    save_generation_log(results, log_path)
    
    # Summary
    completed = len([r for r in results if r["status"] == "completed"])
    failed = len([r for r in results if r["status"] == "failed"])
    skipped = len([r for r in results if r["status"] == "skipped"])
    
    typer.echo(f"\n📊 Generation Complete:")
    typer.echo(f"✅ Completed: {completed}")
    typer.echo(f"⏭️  Skipped: {skipped}")
    typer.echo(f"❌ Failed: {failed}")
    typer.echo(f"💰 Total cost: ${total_cost:.2f}")
    typer.echo(f"📝 Log saved: {log_path}")
    
    if failed > 0:
        typer.echo(f"\n❌ Failed scenes:")
        for result in results:
            if result["status"] == "failed":
                typer.echo(f"  {result['scene_id']}: {result.get('error', 'Unknown error')}")

if __name__ == "__main__":
    typer.run(generate_command)