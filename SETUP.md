# Setup Instructions

## 1. Create and Activate Virtual Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Verify activation (should show venv path)
which python
```

## 2. Install Dependencies

```bash
# Install all required packages
pip install -r requirements.txt
```

## 3. Setup Environment Variables

```bash
# Copy environment template
cp .env.example .env

# Edit .env file with your API keys
# FAL_API_KEY=your_fal_api_key_here
# ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

## 4. Verify Setup

```bash
# Run setup check
python cli.py setup
```

## 5. Test Download (with fixes applied)

```bash
# Test YouTube download
python cli.py download --url "https://youtu.be/EbnWbdR9wSY"

# If pytube fails, it will automatically try yt-dlp as fallback
```

## Troubleshooting

### YouTube Download Issues

The implementation now includes:

1. **URL cleaning**: Removes tracking parameters like `?si=`
2. **Multiple stream strategies**: Progressive → Adaptive → Any MP4
3. **Detailed error reporting**: Shows available streams on failure
4. **yt-dlp fallback**: Automatically tries yt-dlp if pytube fails
5. **Better error messages**: Suggests solutions

### Common Fixes

1. **Upgrade pytube**: `pip install --upgrade pytube`
2. **Install yt-dlp**: `pip install yt-dlp` (already in requirements.txt)
3. **Use clean URLs**: Remove tracking parameters manually
4. **Try different videos**: Some videos may be restricted

### Dependencies Already Fixed

- Added `yt-dlp` as fallback downloader
- Updated pytube version requirements
- Added subprocess support for yt-dlp integration