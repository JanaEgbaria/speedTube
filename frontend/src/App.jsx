import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'

const API_BASE = 'http://localhost:8000'

/** Playback speed up to 5× */
const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 5]

function buildStreamFetchUrl(pageUrl) {
  return `${API_BASE}/api/stream?url=${encodeURIComponent(pageUrl)}`
}

function formatDuration(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return ''
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function App() {
  const [urlInput, setUrlInput] = useState('')
  const [title, setTitle] = useState('')
  const [thumbnailUrl, setThumbnailUrl] = useState(null)
  const [durationSec, setDurationSec] = useState(null)
  const [pageUrl, setPageUrl] = useState('')
  const [playerActive, setPlayerActive] = useState(false)
  const [loadingStream, setLoadingStream] = useState(false)
  const [streamError, setStreamError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [speed, setSpeed] = useState(1)

  const audioRef = useRef(null)

  const fetchStreamAndPlay = useCallback(async () => {
    if (!pageUrl) return

    const a = audioRef.current
    if (!a) {
      setStreamError('Audio element is not ready.')
      return
    }

    setLoadingStream(true)
    setStreamError(null)

    try {
      const res = await fetch(buildStreamFetchUrl(pageUrl))
      const text = await res.text()
      if (!res.ok) {
        let detail = text
        try {
          const j = JSON.parse(text)
          detail = j.detail ?? text
        } catch {
          /* raw */
        }
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
      }
      const data = JSON.parse(text)
      const audioUrl = data.audio_url
      if (!audioUrl) throw new Error('Missing audio_url in response')

      a.pause()
      a.src = audioUrl
      a.playbackRate = speed
      setPlayerActive(true)
    } catch (err) {
      setStreamError(err.message || 'Failed to load audio')
      setPlayerActive(false)
    } finally {
      setLoadingStream(false)
    }
  }, [pageUrl, speed])

  useEffect(() => {
    const a = audioRef.current
    if (!a || !playerActive) return
    a.playbackRate = speed
  }, [playerActive, speed])

  const handleLoad = async (e) => {
    e.preventDefault()
    const url = urlInput.trim()
    if (!url) return

    setError(null)
    setLoading(true)
    setTitle('')
    setThumbnailUrl(null)
    setDurationSec(null)
    setPageUrl('')
    setPlayerActive(false)
    setStreamError(null)

    const au = audioRef.current
    if (au) {
      au.pause()
      au.src = ''
      au.removeAttribute('src')
    }

    try {
      const res = await fetch(`${API_BASE}/api/video-info`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      })
      const text = await res.text()
      if (!res.ok) {
        let detail = text
        try {
          const j = JSON.parse(text)
          detail = j.detail ?? text
        } catch {
          /* use raw text */
        }
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
      }
      const data = JSON.parse(text)
      setTitle(data.title ?? '')
      setThumbnailUrl(data.thumbnail_url ?? null)
      setDurationSec(
        data.duration != null && Number.isFinite(Number(data.duration))
          ? Number(data.duration)
          : null
      )
      setPageUrl(url)
    } catch (err) {
      setError(err.message || 'Failed to load info')
    } finally {
      setLoading(false)
    }
  }

  const setPlaybackSpeed = (rate) => {
    setSpeed(rate)
    if (audioRef.current) audioRef.current.playbackRate = rate
  }

  const trackReady = Boolean(pageUrl && title)

  return (
    <div className="app">
      <header className="app-header">
        <h1 className="logo">SpeedTube</h1>
        <p className="tagline">YouTube as audio — up to 5× speed</p>
      </header>

      <form className="load-form" onSubmit={handleLoad}>
        <label className="sr-only" htmlFor="track-url">
          YouTube URL
        </label>
        <input
          id="track-url"
          type="url"
          className="url-input"
          placeholder="Paste a YouTube URL…"
          value={urlInput}
          onChange={(e) => setUrlInput(e.target.value)}
          autoComplete="off"
        />
        <button type="submit" className="btn btn-primary" disabled={loading}>
          {loading ? 'Loading…' : 'Load'}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {trackReady && (
        <article className="player-card">
          <div className="album-wrap">
            {thumbnailUrl ? (
              <img className="album-art" src={thumbnailUrl} alt="" />
            ) : (
              <div className="album-art album-art--placeholder" aria-hidden="true" />
            )}
          </div>

          <div className="track-meta">
            <h2 className="track-title">{title}</h2>
            {durationSec != null ? (
              <p className="track-duration">{formatDuration(durationSec)}</p>
            ) : null}
          </div>

          <div className="play-row">
            <button
              type="button"
              className="btn btn-primary btn-play"
              disabled={loadingStream}
              onClick={fetchStreamAndPlay}
            >
              {loadingStream ? 'Loading…' : 'Watch'}
            </button>
          </div>

          {loadingStream && (
            <p className="stream-status">Preparing audio…</p>
          )}

          {streamError && <p className="error">{streamError}</p>}

          <div className="audio-shell">
            <audio
              ref={audioRef}
              className="audio-player"
              controls
              controlsList="nodownload"
              preload="auto"
            />
          </div>

          {playerActive && (
            <div className="speed-section">
              <span className="speed-label">Speed</span>
              <div className="speed-buttons">
                {SPEEDS.map((rate) => (
                  <button
                    key={rate}
                    type="button"
                    className={`btn btn-speed${speed === rate ? ' active' : ''}`}
                    onClick={() => setPlaybackSpeed(rate)}
                  >
                    {rate}x
                  </button>
                ))}
              </div>
            </div>
          )}
        </article>
      )}
    </div>
  )
}

export default App
