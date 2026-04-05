# SpeedTube 🎧

A personal web app that lets you play any YouTube video as audio at custom speeds — perfect for podcasts, lectures, and Quran recitations.

Paste any YouTube URL and listen at any speed from 0.5x up to 5x, with a clean podcast-style interface.

## Features

- 🎵 Audio-only playback — no video lag, just pure audio
- ⚡ Speed controls: 0.5x, 0.75x, 1x, 1.25x, 1.5x, 2x, 3x, 4x, 5x
- 🎨 Clean podcast-style UI with album art and track title
- 📦 Smart caching — yt-dlp only runs once per video, repeat plays are instant
- 🔁 Range request support for smooth seeking

## Tech Stack

- **Frontend:** React + Vite
- **Backend:** Python + FastAPI
- **Audio extraction:** yt-dlp
- **Streaming:** httpx proxy with Range support

## Run Locally

**Backend:**

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173
