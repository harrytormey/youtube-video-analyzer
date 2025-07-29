# 🎬 YouTube-to-Veo3 CLI Usage Examples

## 🚀 Complete Workflow Example

Here's a complete example using the E*TRADE Baby commercial:

### Step 1: Download Video
```bash
python3 cli.py download --url "https://youtu.be/EbnWbdR9wSY"
# ✅ Downloaded input.mp4 (34 seconds)
```

### Step 2: Analyze Scenes
```bash
python3 cli.py analyze input.mp4 --output scene_prompts.json
# ✅ Detected 14 scenes, analyzed with Claude
```

### Step 3: Browse Available Scenes
```bash
python3 cli.py list-scenes scene_prompts.json
```

**Output:**
```
📋 Available scenes (14 total):

 1. scene_01 (1.0s) - A serene mountainous landscape at dusk/dawn...
 2. scene_02 (3.0s) - A high-contrast black and white scene...
 3. scene_03 (15.2s) - A nursery scene showing a toddler...
 4. scene_05 (1.2s) - A festive nightclub/lounge scene...
 5. scene_06 (1.0s) - A polo match scene showing three riders...
 ...
```

### Step 4: Generate Specific Scenes
```bash
# Generate just the most interesting scenes
python3 cli.py generate scene_prompts.json --scenes "scene_01,scene_05,scene_19"
# ✅ Generated 3 scenes (8s each)
```

### Step 5: Stitch Final Video
```bash
python3 cli.py stitch ./clips/ --output final_commercial.mp4
# ✅ Created 24-second final video
```

## 🎯 Scene Selection Strategies

### By Content Type
```bash
# Character/dialogue scenes
python3 cli.py generate scene_prompts.json --scenes "scene_03,scene_07,scene_18"

# Action/movement scenes  
python3 cli.py generate scene_prompts.json --scenes "scene_06,scene_10"

# Branding/logo scenes
python3 cli.py generate scene_prompts.json --scenes "scene_19"
```

### By Quality/Duration
```bash
# Skip very short scenes (< 1s)
python3 cli.py generate scene_prompts.json --scenes "scene_02,scene_03,scene_18,scene_19"

# Skip the very long scene that gets truncated
# (scene_03 is 15.2s but will be capped at 8s)
python3 cli.py generate scene_prompts.json --scenes "scene_01,scene_02,scene_05,scene_19"
```

### Cost-Conscious Approach
```bash
# Test with just 1 scene first ($0.80)
python3 cli.py generate scene_prompts.json --scenes "scene_01"

# Review quality, then generate 2-3 more ($1.60-$2.40)
python3 cli.py generate scene_prompts.json --scenes "scene_05,scene_19"

# Generate all scenes if satisfied ($11.20 for all 14)
python3 cli.py generate scene_prompts.json
```

## 🔍 Preview & Iteration

### Dry Run Testing
```bash
# Preview what would be generated
python3 cli.py generate scene_prompts.json --scenes "scene_01,scene_05" --dry-run

# Preview first 3 scenes
python3 cli.py generate scene_prompts.json --max-scenes 3 --dry-run

# Preview all scenes
python3 cli.py generate scene_prompts.json --dry-run
```

### Iterative Generation
```bash
# Round 1: Test key scenes
python3 cli.py generate scene_prompts.json --scenes "scene_01,scene_19"

# Review results in ./clips/
ls -la ./clips/

# Round 2: Add character scenes  
python3 cli.py generate scene_prompts.json --scenes "scene_03,scene_07"

# Round 3: Fill in the rest
python3 cli.py generate scene_prompts.json --scenes "scene_02,scene_05,scene_06"

# Final stitch
python3 cli.py stitch ./clips/ --output complete_video.mp4
```

## 🛠️ Advanced Options

### Custom Output Directories
```bash
# Organize by content type
python3 cli.py generate scene_prompts.json --scenes "scene_03,scene_07" --output-dir ./character_scenes/
python3 cli.py generate scene_prompts.json --scenes "scene_06,scene_10" --output-dir ./action_scenes/

# Stitch from specific directory
python3 cli.py stitch ./character_scenes/ --output character_video.mp4
```

### Overwrite/Skip Existing
```bash
# Skip existing clips (default)
python3 cli.py generate scene_prompts.json --scenes "scene_01,scene_02" --skip-existing

# Overwrite existing clips
python3 cli.py generate scene_prompts.json --scenes "scene_01,scene_02" --overwrite
```

## 📊 Cost Management

### Scene Count vs Cost
- 1 scene = $0.80 (8 seconds)
- 5 scenes = $4.00 (40 seconds)  
- 10 scenes = $8.00 (80 seconds)
- All 14 scenes = $11.20 (112 seconds)

### Recommended Approach
1. **Browse scenes**: `list-scenes` command (free)
2. **Test 1-2 scenes** first: `--scenes "scene_01,scene_19"` ($1.60)
3. **Generate selectively**: Choose best 5-8 scenes ($4-6.40)
4. **Expand if needed**: Add more scenes incrementally

## 🎥 Final Tips

- **Scene_01** is usually the opening/title
- **Scene_19** (last scene) is often branding/logo
- **Character scenes** (scene_03, scene_07, scene_18) work well for dialogue
- **Action scenes** (scene_06, scene_10) are good for movement
- **Very short scenes** (< 1s) may not generate well
- **All clips are 8 seconds** due to Veo3 API limitation