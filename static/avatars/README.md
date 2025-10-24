# Avatar Images

This folder contains user avatar images for profile customization.

## Current Status
- ✅ **avatar1.png** to **avatar8.png** - Available
- ⚠️ **avatar9.png** to **avatar25.png** - Need to be added

## Adding New Avatars

To add new avatar images:

1. Create or download avatar images (recommended size: 256x256px or higher)
2. Save them as PNG files with transparent backgrounds (preferred)
3. Name them sequentially: `avatar9.png`, `avatar10.png`, ... `avatar25.png`
4. Place them in this `/static/avatars/` directory

## Image Requirements
- **Format**: PNG (preferred for transparency)
- **Size**: 256x256px minimum (square aspect ratio)
- **Style**: Can be illustrations, icons, or photos
- **File Size**: Keep under 1MB per image for faster loading

## Fallback Behavior
If an avatar file is missing, the system will automatically fall back to `avatar1.png` to prevent broken images.

---

**Note**: The app is currently configured to show 25 avatar slots in the profile customization page.
