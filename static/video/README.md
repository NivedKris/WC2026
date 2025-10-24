# Video Background

Place your World Cup background video here.

**Required file:** `background.mp4`

## Video Specifications

- **Format:** MP4 (H.264 codec recommended)
- **Recommended Resolution:** 1920x1080 (Full HD) or 1280x720 (HD)
- **Recommended Duration:** 30-60 seconds (will loop automatically)
- **File Size:** Keep under 10MB for optimal loading
- **Aspect Ratio:** 16:9

## Video Usage

This video will be used as:
1. **Index Page (Home):** Full opacity background with dark overlay (60% black)
2. **Dashboard:** Subtle background at 20% opacity

## Optimization Tips

To optimize your video:
```bash
# Using ffmpeg to compress and optimize
ffmpeg -i input.mp4 -vcodec h264 -acodec aac -b:v 2M -b:a 128k background.mp4
```

## Copyright Notice

Ensure you have the rights to use any video content. Use royalty-free or licensed World Cup footage.
