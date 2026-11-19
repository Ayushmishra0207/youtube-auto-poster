"""
Viral Clip Maker — paste a YouTube link, get vertical, captioned Shorts/Reels.

Pipeline (see clipper/job.py):
  downloader  → yt-dlp fetch (≤1080p) + metadata
  analyzer    → audio energy, scene cuts, speech density → candidate windows
  transcriber → faster-whisper word timestamps (local, free)
  planner     → Claude picks the best moments + writes hooks/titles (optional)
  subtitles   → word-by-word animated ASS captions
  renderer    → ffmpeg 9:16 reframe, grade, captions, hook banner, progress bar
"""
