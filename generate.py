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

def submit_veo3_request(prompt: str, duration: float) -> Dict[str, Any]:
    """Submit generation request to Veo3 via fal.ai."""
    headers = get_fal_headers()
    
    # Ensure duration doesn't exceed 8 seconds and format as required string
    duration_capped = min(duration, 8.0)
    
    # Veo3 API currently only accepts "8s" as duration
    # According to the API error, only "8s" is permitted
    duration_str = "8s"
    
    payload = {
        "prompt": prompt,
        "duration": duration_str,
        "resolution": "720p",  # Options: 720p, 1080p
        "quality": "medium"    # Options: low, medium, high
    }
    
    try:
        response = requests.post(
            FAL_API_BASE,
            headers=headers,
            json=payload,
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            return result
        else:
            typer.echo(f"API Error {response.status_code}: {response.text}", err=True)
            return {"error": f"HTTP {response.status_code}: {response.text}"}
            
    except requests.exceptions.RequestException as e:
        typer.echo(f"Request failed: {e}", err=True)
        return {"error": str(e)}

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

def generate_single_scene(scene: Dict[str, Any], output_dir: str, skip_existing: bool = True) -> Dict[str, Any]:
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
    
    # Validate prompt length
    prompt = scene['prompt']
    if len(prompt) > 1000:
        typer.echo(f"⚠️  {scene_id}: Prompt too long ({len(prompt)} chars), truncating")
        prompt = prompt[:997] + "..."
    
    typer.echo(f"🎬 Generating {scene_id} (8s - fixed by API)...")
    
    # Submit generation request (duration parameter is ignored since API only accepts 8s)
    result = submit_veo3_request(prompt, 8.0)
    
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
        # All Veo3 clips are 8 seconds (API limitation)
        actual_duration = 8.0
        estimated_cost = actual_duration * 0.10  # $0.10 per second estimate
        actual_cost = result.get("cost", estimated_cost)  # Use original result, not final_result
        
        typer.echo(f"✅ Generated {scene_id}: {output_path} (8s)")
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
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be generated without actually doing it")
):
    """Generate video clips from scene prompts using Veo3."""
    
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
    
    scenes = data.get('scenes', [])
    if not scenes:
        typer.echo("Error: No scenes found in prompts file", err=True)
        raise typer.Exit(1)
    
    # Limit scenes if requested
    if max_scenes:
        scenes = scenes[:max_scenes]
        typer.echo(f"Limited to first {max_scenes} scenes")
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Show generation plan - all clips will be 8 seconds due to API limitation
    total_duration = len(scenes) * 8.0  # All clips are 8 seconds
    estimated_cost = total_duration * 0.10  # $0.10 per second estimate
    
    typer.echo(f"\n🎬 Generation Plan:")
    typer.echo(f"Scenes to generate: {len(scenes)}")
    typer.echo(f"Total duration: {total_duration:.1f}s (all clips will be 8s due to Veo3 API)")
    typer.echo(f"Estimated cost: ${estimated_cost:.2f}")
    typer.echo(f"Output directory: {output_dir}")
    
    if dry_run:
        typer.echo("\n📋 Dry run - scenes that would be generated:")
        for scene in scenes:
            existing = check_existing_clip(scene['id'], output_dir)
            status = "EXISTS" if existing else "GENERATE"
            typer.echo(f"  {scene['id']}: {status} (8s - API fixed duration)")
        return
    
    # Confirm before proceeding
    if not typer.confirm("\nProceed with generation?"):
        typer.echo("Generation cancelled")
        return
    
    # Generate clips
    results = []
    total_cost = 0
    
    typer.echo(f"\n🚀 Starting generation...")
    
    for i, scene in enumerate(scenes, 1):
        typer.echo(f"\n[{i}/{len(scenes)}] Processing {scene['id']}...")
        
        result = generate_single_scene(scene, output_dir, skip_existing)
        results.append(result)
        total_cost += result.get('cost', 0)
        
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