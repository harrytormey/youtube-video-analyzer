# 🏗️ YouTube-to-Veo3 Architecture Documentation

## 📋 Table of Contents
- [System Overview](#-system-overview)
- [Core Architecture](#-core-architecture) 
- [Data Flow](#-data-flow)
- [Component Details](#-component-details)
- [AI Integration](#-ai-integration)
- [Technical Decisions](#-technical-decisions)
- [Limitations & Trade-offs](#-limitations--trade-offs)
- [Performance Considerations](#-performance-considerations)

## 🎯 System Overview

The YouTube-to-Veo3 Scene Translator is a sophisticated pipeline that transforms existing videos into AI-generated recreations with enhanced quality, audio, and visual effects. The system leverages multiple AI services and video processing techniques to achieve high-fidelity video recreation.

### Primary Use Cases:
1. **Content Recreation**: Transform low-quality videos into high-definition AI-generated versions
2. **Style Transfer**: Recreate videos with different visual styles or cinematography
3. **Audio Enhancement**: Add professional narration and sound effects to silent clips
4. **Scene Analysis**: Deep understanding of video content for creative applications
5. **NEW: Visual Consistency**: Maintain character and scene consistency using image-to-video generation

### Key Technologies:
- **Video Analysis**: FFmpeg + OpenCV motion detection
- **AI Vision**: Claude 3.5 Sonnet multimodal understanding
- **Audio Processing**: OpenAI Whisper speech recognition
- **Video Generation**: Google Veo3 (text-to-video + image-to-video) and Wan 2.2 A14B via fal.ai API
- **Image Processing**: Reference frame extraction and base64 conversion for image-to-video
- **Orchestration**: Python + Typer CLI framework

## 🏛️ Core Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   INPUT STAGE   │    │  ANALYSIS STAGE │    │ GENERATION STAGE│    │  OUTPUT STAGE   │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ • YouTube DL    │───▶│ • Scene Detection│───▶│ • Scene Optimization│───▶│ • Clip Stitching│
│ • Local Files   │    │ • Frame Extraction│   │ • Veo3 Generation │    │ • Final Assembly│
│ • Validation    │    │ • Audio Analysis │    │ • Image-to-Video  │    │ • Metadata Export│
└─────────────────┘    │ • Claude Analysis │    │ • Multi-Model API │    └─────────────────┘
                       │ • Reference Frames│    │ • Progress Tracking│    
                       └─────────────────┘    └─────────────────┘
```

### Layer Architecture:

#### 1. **Presentation Layer** (`cli.py`)
- Command-line interface using Typer
- User interaction and parameter validation
- Progress reporting and error handling
- Workflow orchestration

#### 2. **Service Layer** (`download.py`, `analyze.py`, `generate.py`, `stitch.py`)
- Business logic implementation
- External API integration
- Data transformation and processing
- Error handling and recovery

#### 3. **Integration Layer**
- **Video Processing**: FFmpeg wrapper functions
- **AI Services**: Claude API, Whisper, fal.ai Veo3
- **File System**: Temporary file management, caching
- **Configuration**: Environment variables, API keys

#### 4. **Data Layer**
- **Scene Metadata**: JSON structure for scene descriptions
- **Media Files**: Video segments, frames, audio clips
- **Cache System**: Generated content and analysis results
- **Logs**: Generation logs, error tracking

## 🌊 Data Flow

### 1. Input Processing
```python
# download.py
input_video = download_youtube(url) or validate_local_file(path)
video_metadata = extract_video_info(input_video)
```

### 2. Scene Detection & Analysis
```python
# analyze.py
scenes = detect_scenes_with_motion(video, threshold=0.4)
for scene in scenes:
    frames = extract_motion_frames(video, scene.start, scene.end)
    audio = extract_audio_segment(video, scene.start, scene.end) 
    dialogue = transcribe_with_whisper(audio)
    analysis = analyze_with_claude(frames, dialogue, scene_context)
    scene_chunks = split_long_scenes(scene, dialogue) if scene.duration > 8
```

### 3. Generation Optimization
```python
# generate.py
optimized_scenes = optimize_scene_combinations(scenes)
for scene_group in optimized_scenes:
    if len(scene_group) > 1:
        combined_prompt = create_multi_scene_prompt(scene_group)
    
    # NEW: Image-to-video support with reference frames
    reference_image_path = None
    if use_reference_image:
        reference_image_path = extract_reference_frame_for_scene(scene, output_dir)
    
    # Multi-model generation support
    if model == "wan2.2":
        result = generate_wan_video(prompt)  # Visual only, 90% cheaper
    else:
        result = generate_veo3_video(prompt, reference_image_path, generate_audio=True)
    
    if scene_group.is_combined:
        individual_clips = split_combined_clip(result, scene_group)
```

### 4. Final Assembly
```python
# stitch.py  
final_video = stitch_clips(clip_paths, method="filter")
add_metadata(final_video, scene_info)
```

## 🔧 Component Details

### Video Processing (`analyze.py`)

#### Scene Detection Algorithm:
```python
def detect_scenes(video_path: str, threshold: float = 0.4) -> List[Scene]:
    # 1. FFmpeg scene change detection
    cmd = ffmpeg.input(video_path).filter('select', f'gt(scene,{threshold})')
    
    # 2. Motion vector analysis for refinement
    motion_cmd = ffmpeg.input(video_path).filter('select', 'gt(scene,0.1)')
    
    # 3. Combine results and filter short scenes
    scene_boundaries = parse_ffmpeg_timestamps(cmd_output)
    return create_scene_objects(scene_boundaries)
```

#### Motion-Based Frame Extraction:
```python
def extract_motion_frames(video_path: str, start: float, end: float) -> List[str]:
    # 1. Detect motion peaks within scene
    motion_timestamps = detect_motion_vectors(video_path, start, end)
    
    # 2. Strategic sampling based on scene duration  
    if duration <= 6.0:
        strategic_times = [start + duration*0.2, start + duration*0.7, start + duration*0.9]
    
    # 3. Combine motion peaks with strategic sampling
    key_times = merge_timestamps(motion_timestamps, strategic_times)
    
    # 4. Extract frames at optimal moments
    return [extract_frame(video_path, t) for t in key_times]
```

### AI Integration

#### Claude 3.5 Sonnet Analysis:
```python
def analyze_scene_with_claude(frames: List[str], dialogue: str, scene: Dict) -> Dict:
    # Multi-modal prompt with temporal emphasis
    prompt = f"""
    CRITICAL INSTRUCTIONS:
    - This is a {scene['duration']:.1f}-second VIDEO SEQUENCE, not static images
    - Focus on MOTION and CHANGES between frames
    - Describe DYNAMIC ELEMENTS: character movement, object motion
    
    DIALOGUE: "{dialogue}"
    
    Analyze using comprehensive template:
    A. KEY VISUALS & MAIN SUBJECTS
    B. SETTING & ENVIRONMENT  
    C. CAMERA WORK & COMPOSITION
    D. TEMPORAL SEQUENCE & MOTION ANALYSIS  # Key improvement
    E. AUDIO ELEMENTS
    F. VISUAL STYLE & AESTHETICS
    G. NARRATIVE ROLE & EMOTIONAL IMPACT
    """
    
    # Convert frames to base64 for vision analysis
    frame_data = [{"type": "image", "source": {"type": "base64", "data": image_to_base64(f)}} 
                  for f in frames]
    
    response = claude_client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=4000,
        messages=[{"role": "user", "content": frame_data + [{"type": "text", "text": prompt}]}]
    )
    
    return parse_json_response(response.content[0].text)
```

#### Veo3 Video Generation:
```python
def submit_veo3_request(prompt: str, use_fast: bool = False, reference_image_path: str = None) -> Dict:
    # Choose endpoint based on generation mode
    if reference_image_path:
        endpoint = f"https://fal.run/fal-ai/veo3/{'fast/' if use_fast else ''}image-to-video"
    else:
        endpoint = f"https://fal.run/fal-ai/veo3{'/fast' if use_fast else ''}"
    
    payload = {
        "prompt": prompt,
        "duration": "8s",  # API-fixed duration
        "resolution": "720p",
        "quality": "medium", 
        "generate_audio": True,  # Critical for narration
        "seed": 42  # Consistency across generations
    }
    
    # Add reference image for image-to-video generation
    if reference_image_path:
        image_url = convert_image_to_data_uri(reference_image_path)
        payload["image_url"] = image_url
    
    response = requests.post(endpoint, json=payload, headers=get_fal_headers())
    return handle_async_or_sync_response(response.json())

def convert_image_to_data_uri(image_path: str) -> str:
    """Convert reference image to base64 data URI for API transmission."""
    with open(image_path, 'rb') as f:
        image_data = f.read()
        encoded_data = base64.b64encode(image_data).decode('utf-8')
        mime_type = mimetypes.guess_type(image_path)[0] or 'image/jpeg'
        return f"data:{mime_type};base64,{encoded_data}"

def extract_reference_frame_for_scene(scene: Dict, output_dir: str) -> Optional[str]:
    """Extract reference frame at optimal timestamp (70% through scene)."""
    start_seconds = scene.get('start_seconds', 0)
    duration = scene.get('duration', 3)
    frame_time = start_seconds + (duration * 0.7)  # Action moment
    
    frame_path = os.path.join(output_dir, f"{scene['id']}_reference.jpg")
    
    # Extract frame using FFmpeg at 720p+ resolution
    cmd = ['ffmpeg', '-i', 'input.mp4', '-ss', str(frame_time), 
           '-vframes', '1', '-q:v', '2', '-s', '1280x720', frame_path, '-y']
    
    result = subprocess.run(cmd, capture_output=True)
    return frame_path if result.returncode == 0 else None
```

### Cost Optimization System

#### Scene Combination Algorithm:
```python
def optimize_scene_combinations(scenes: List[Dict]) -> List[List[Dict]]:
    """Groups short scenes to maximize 8-second clip usage."""
    optimized_groups = []
    current_group = []
    current_duration = 0
    
    for scene in scenes:
        # Can this scene fit in current group?
        if current_duration + scene['duration'] <= 7.5:  # Leave buffer
            current_group.append(scene)
            current_duration += scene['duration']
        else:
            # Start new group
            if current_group:
                optimized_groups.append(current_group)
            current_group = [scene]
            current_duration = scene['duration']
    
    # Handle remaining scenes
    if current_group:
        optimized_groups.append(current_group)
    
    return optimized_groups
```

## 🖼️ Image-to-Video Architecture (NEW!)

### System Overview:
The image-to-video system enhances the traditional text-to-video pipeline by incorporating visual reference frames extracted from the original video, providing AI generation with concrete visual guidance for improved consistency.

### Architecture Flow:
```
Original Video Input
    ↓
┌────────────────┐
│ Scene Detection│ ──→ Scene Boundaries + Timestamps
└────────────────┘
    ↓
┌────────────────┐
│ Reference Frame│ ──→ Extract Frame at 70% Through Scene
│ Extraction     │     (Optimal Action Moment)
└────────────────┘
    ↓
┌────────────────┐
│ Image Processing│ ──→ 720p+ Resize + Base64 Encoding
└────────────────┘     
    ↓
┌────────────────┐
│ Veo3 I2V API  │ ──→ Generate Video Using Image + Prompt
└────────────────┘
    ↓
Generated Video with Improved Consistency
```

### Key Components:

#### 1. **Reference Frame Extraction**:
```python
def extract_reference_frame_for_scene(scene: Dict, output_dir: str) -> Optional[str]:
    """Strategic frame extraction at action moments."""
    # Calculate optimal timestamp (70% through scene)
    start_seconds = scene['start_seconds']
    duration = scene['duration']
    frame_time = start_seconds + (duration * 0.7)  # Peak action timing
    
    # High-quality extraction with FFmpeg
    frame_path = os.path.join(output_dir, f"{scene['id']}_reference.jpg")
    extract_cmd = [
        'ffmpeg', '-i', 'input.mp4',
        '-ss', str(frame_time),           # Precise timestamp
        '-vframes', '1',                  # Single frame
        '-q:v', '2',                      # High quality
        '-s', '1280x720',                 # 720p+ required by Veo3
        frame_path, '-y'
    ]
    
    return frame_path if extraction_successful else None
```

#### 2. **Image Processing Pipeline**:
```python
def convert_image_to_data_uri(image_path: str) -> str:
    """Optimize image for API transmission."""
    with open(image_path, 'rb') as f:
        image_data = f.read()
        
        # Validate size constraints (<8MB for fal.ai)
        image_size_mb = len(image_data) / (1024 * 1024)
        if image_size_mb > 7:
            raise ValueError(f"Image too large: {image_size_mb:.1f}MB")
        
        # Convert to base64 data URI
        encoded_data = base64.b64encode(image_data).decode('utf-8')
        mime_type = mimetypes.guess_type(image_path)[0] or 'image/jpeg'
        
        return f"data:{mime_type};base64,{encoded_data}"
```

#### 3. **Smart Endpoint Selection**:
```python
def choose_generation_endpoint(use_fast: bool, reference_image_path: str) -> str:
    """Dynamic endpoint selection based on generation mode."""
    base_url = "https://fal.run/fal-ai/veo3"
    
    if reference_image_path:
        # Image-to-video endpoints
        return f"{base_url}/{'fast/' if use_fast else ''}image-to-video"
    else:
        # Text-to-video endpoints  
        return f"{base_url}{'/fast' if use_fast else ''}"
```

### Performance Optimizations:

#### 1. **On-Demand Processing**:
- Frames extracted only when `--use-reference-image` flag is used
- No preprocessing overhead for text-to-video workflows
- Automatic cleanup of temporary reference frames

#### 2. **Intelligent Fallback**:
- If frame extraction fails → automatic fallback to text-to-video
- If image is too large → warning + fallback option
- Graceful degradation maintains workflow continuity

#### 3. **Caching Strategy**:
- Reference frames cached in output directory
- Reuse frames for multiple generation attempts
- Automatic cleanup after successful generation

### Quality Enhancements:

#### 1. **Timestamp Optimization**:
- **70% Rule**: Extract frames at 70% through scene duration
- **Action Focus**: Captures peak motion/action moments
- **Composition Quality**: Avoids transition frames and motion blur

#### 2. **Resolution Standards**:
- **Minimum 720p**: Meets Veo3 API requirements
- **Aspect Ratio**: Maintains original video proportions
- **Quality Settings**: High-quality JPEG compression (q:v 2)

## 🤖 AI Integration Architecture

### Enhanced Multi-Modal AI Pipeline:
```
Video Input
    ↓
┌────────────────┐
│ FFmpeg Analysis│ ──→ Scene Boundaries + Motion Vectors + Reference Frames
└────────────────┘
    ↓
┌────────────────┐  
│ Frame Extraction│ ──→ 2-5 Frames per Scene + 1 Reference Frame (70% timestamp)
└────────────────┘
    ↓
┌────────────────┐
│ Audio Analysis │ ──→ Whisper Transcription + Timestamps  
└────────────────┘
    ↓
┌────────────────┐
│ Claude 3.5     │ ──→ Ultra-Detailed Scene Analysis + Motion Understanding  
│ Sonnet Vision  │     (300+ words, temporal understanding)
└────────────────┘
    ↓
┌────────────────┐
│ Veo3 Generation│ ──→ Text-to-Video OR Image-to-Video + H.264 + AAC Audio
│ (Multi-Modal)  │     
└────────────────┘
```

### Multi-Modal AI Pipeline:
```
Video Input
    ↓
┌────────────────┐
│ FFmpeg Analysis│ ──→ Scene Boundaries + Motion Vectors
└────────────────┘
    ↓
┌────────────────┐  
│ Frame Extraction│ ──→ 2-5 Frames per Scene (Motion-Focused)
└────────────────┘
    ↓
┌────────────────┐
│ Audio Analysis │ ──→ Whisper Transcription + Timestamps  
└────────────────┘
    ↓
┌────────────────┐
│ Claude 3.5     │ ──→ Ultra-Detailed Scene Analysis
│ Sonnet Vision  │     (300+ words, temporal understanding)
└────────────────┘
    ↓
┌────────────────┐
│ Veo3 Generation│ ──→ H.264 Video + AAC Audio
└────────────────┘
```

### API Integration Patterns:

#### Error Handling & Retries:
```python
def with_retries(api_call, max_retries=3, backoff_factor=2):
    """Exponential backoff retry pattern for API calls."""
    for attempt in range(max_retries):
        try:
            return api_call()
        except APIError as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(backoff_factor ** attempt)
```

#### Rate Limiting:
```python
class RateLimiter:
    def __init__(self, calls_per_minute=60):
        self.calls = []
        self.limit = calls_per_minute
    
    def wait_if_needed(self):
        now = time.time()
        # Remove calls older than 1 minute
        self.calls = [call_time for call_time in self.calls if now - call_time < 60]
        
        if len(self.calls) >= self.limit:
            sleep_time = 60 - (now - self.calls[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
```

## ⚡ Technical Decisions & Rationale

### 1. **Scene Detection: Motion Vectors + Thresholding**
**Decision**: Hybrid approach combining FFmpeg scene detection with motion analysis
**Rationale**: 
- Pure scene detection misses action within scenes
- Motion vectors identify dynamic moments (jumping, reaching)
- Strategic sampling ensures we capture progression over time
**Trade-off**: Increased complexity vs. better action capture

### 2. **Frame Extraction: 2-5 Frames per Scene**
**Decision**: Variable frame count based on scene duration and motion
**Rationale**:
- Short scenes (≤3s): 3 frames to catch quick action
- Medium scenes (3-6s): 4-5 frames to show progression  
- Long scenes (>6s): 5 frames with action focus
**Trade-off**: More API calls vs. better temporal understanding

### 3. **Audio Processing: Segment-Level Transcription**
**Decision**: Extract audio per scene, not globally
**Rationale**:
- Improves transcription accuracy for short segments
- Enables precise dialogue-to-scene alignment
- Handles overlapping dialogue across scene boundaries
**Trade-off**: Multiple Whisper calls vs. accuracy

### 4. **Scene Chunking: 7s + 1s Overlap**
**Decision**: Split >8s scenes with 1-second overlap
**Rationale**:
- Veo3 has hard 8-second limit
- Overlap ensures continuity between chunks
- 7s chunks leave buffer for processing
**Trade-off**: Some content duplication vs. smooth transitions

### 5. **Cost Optimization: Scene Combining**
**Decision**: Group short scenes into single 8s clips
**Rationale**:
- Veo3 charges per 8s regardless of actual content
- Can achieve 70-80% cost savings on fragmented content
- Auto-splitting maintains individual scene access
**Trade-off**: Implementation complexity vs. significant cost savings

### 6. **Claude Prompting: Temporal Sequence Focus**
**Decision**: Emphasize motion analysis over static description
**Rationale**:
- Original system treated video as static images
- Veo3 needs dynamic understanding for realistic motion
- Multi-frame context enables progression analysis
**Trade-off**: Longer prompts/higher cost vs. much better results

### 7. **Error Handling: Graceful Degradation**
**Decision**: Continue processing when individual components fail
**Rationale**:
- API failures shouldn't break entire pipeline
- JSON parsing errors fall back to raw content
- Missing audio doesn't prevent video generation
**Trade-off**: Partial results vs. complete failure

## 🚧 Limitations & Trade-offs

### Current Limitations:

#### 1. **Veo3 API Constraints**
- **Fixed 8s Duration**: Cannot generate shorter clips, leading to potential waste
- **Resolution Limits**: Maximum 1080p output
- **Audio Quality**: Limited control over voice characteristics
- **Processing Time**: 30-120 seconds per clip generation

#### 2. **Scene Detection Accuracy**
- **Lighting Changes**: May trigger false scene boundaries
- **Fast Motion**: Can miss rapid movements between frames
- **Similar Scenes**: May not distinguish between similar compositions
- **Threshold Sensitivity**: Requires manual tuning per video type

#### 3. **Audio Processing**
- **Background Noise**: Can interfere with dialogue transcription  
- **Multiple Speakers**: Limited speaker separation capabilities
- **Audio Quality**: Poor audio affects transcription accuracy
- **Language Support**: Primarily optimized for English

#### 4. **Cost Considerations**
- **Minimum Billing**: 8s minimum per clip regardless of content
- **Token Usage**: Detailed analysis uses significant Claude tokens
- **API Dependencies**: Multiple paid services increase operational costs
- **Scale Limitations**: Cost grows linearly with video length

### Design Trade-offs:

#### Quality vs. Speed:
- **High Quality**: Detailed analysis, multiple frames, comprehensive prompts
- **Speed Impact**: Multiple API calls, longer processing time
- **Decision**: Prioritized quality for better Veo3 generation results

#### Accuracy vs. Cost:
- **Accuracy**: Motion detection, multiple frame analysis, detailed prompts
- **Cost Impact**: More API calls, longer prompts, higher token usage
- **Decision**: Optimized where possible (scene combining) while maintaining quality

#### Flexibility vs. Complexity:
- **Flexibility**: Configurable parameters, multiple generation modes, optimization options
- **Complexity**: More code paths, edge cases, user configuration
- **Decision**: Provided flexibility with sensible defaults

## 🚀 Performance Considerations

### Optimization Strategies:

#### 1. **Parallel Processing**
```python
# Multiple API calls can run concurrently
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
    audio_future = executor.submit(transcribe_audio, audio_path)
    frame_futures = [executor.submit(extract_frame, video, t) for t in timestamps]
    results = [f.result() for f in frame_futures]
```

#### 2. **Caching System**
```python
def cache_key(scene_data):
    return hashlib.md5(f"{scene_data['id']}_{scene_data['duration']}_{scene_data['prompt']}".encode()).hexdigest()

def get_cached_result(cache_key):
    cache_path = f"cache/{cache_key}.json"
    if os.path.exists(cache_path):
        return json.load(open(cache_path))
    return None
```

#### 3. **Memory Management**
```python
# Stream large files instead of loading into memory
def process_video_streaming(video_path):
    with tempfile.TemporaryDirectory() as temp_dir:
        # Process in chunks, clean up immediately
        for scene in scenes:
            frames = extract_frames(video_path, scene, temp_dir)
            result = analyze_scene(frames)
            # Frames automatically cleaned up when temp_dir exits
            yield result
```

#### 4. **Progress Tracking**
```python
from tqdm import tqdm

def generate_scenes_with_progress(scenes):
    progress_bar = tqdm(total=len(scenes), desc="Generating clips")
    for scene in scenes:
        result = generate_single_scene(scene)
        progress_bar.update(1)
        progress_bar.set_postfix({"Current": scene['id'], "Cost": f"${result['cost']:.2f}"})
    progress_bar.close()
```

### Scalability Considerations:

#### Bottlenecks:
1. **API Rate Limits**: Claude (60 RPM), fal.ai (varies by plan)
2. **File I/O**: Large video processing, temporary file creation
3. **Memory Usage**: Multiple frames in memory during analysis
4. **Network Latency**: Multiple API calls per scene

#### Mitigation Strategies:
1. **Rate Limiting**: Built-in delays and retry logic
2. **Streaming Processing**: Process scenes individually  
3. **Temporary File Management**: Aggressive cleanup, streaming where possible
4. **Connection Pooling**: Reuse HTTP connections for API calls

### Resource Requirements:

#### Minimum System Requirements:
- **CPU**: 2+ cores (for FFmpeg processing)
- **RAM**: 4GB (for video processing and frame extraction)
- **Storage**: 1GB free space (for temporary files)
- **Network**: Stable internet (for API calls and video upload/download)

#### Recommended for Production:
- **CPU**: 4+ cores with high clock speed
- **RAM**: 8GB+ (for larger videos and parallel processing)
- **Storage**: SSD with 10GB+ free space
- **Network**: High-bandwidth connection (for large video uploads)

This architecture provides a robust, scalable foundation for video-to-video AI translation while maintaining flexibility for future enhancements and optimizations.