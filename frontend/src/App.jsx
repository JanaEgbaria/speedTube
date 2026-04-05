import { useEffect, useRef, useState } from 'react'
import './App.css'

const API_BASE = 'http://localhost:8000'

const SPEEDS = [0.25, 0.5, 1, 1.5, 2, 3, 4, 5, 8, 12, 16]

function App() {
  const [urlInput, setUrlInput] = useState('')
  const [title, setTitle] = useState('')
  const [thumbnailUrl, setThumbnailUrl] = useState(null)
  const [formats, setFormats] = useState([])
  const [videoPageUrl, setVideoPageUrl] = useState('')
  const [selectedFormat, setSelectedFormat] = useState('')
  const [streamUrl, setStreamUrl] = useState('')
  const [streamLoading, setStreamLoading] = useState(false)
  const [streamError, setStreamError] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [speed, setSpeed] = useState(1)

  const videoRef = useRef(null)

  useEffect(() => {
    if (!videoPageUrl || !selectedFormat) {
      setStreamUrl('')
      setStreamError(null)
      setStreamLoading(false)
      return
    }

    let cancelled = false
    setStreamLoading(true)
    setStreamError(null)
    setStreamUrl('')

    ;(async () => {
      try {
        const res = await fetch(
          `${API_BASE}/api/stream?url=${encodeURIComponent(videoPageUrl)}&format=${encodeURIComponent(selectedFormat)}`
        )
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
        if (!cancelled) setStreamUrl(data.stream_url ?? '')
      } catch (err) {
        if (!cancelled) {
          setStreamUrl('')
          setStreamError(err.message || 'Failed to resolve stream URL')
        }
      } finally {
        if (!cancelled) setStreamLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [videoPageUrl, selectedFormat])

  useEffect(() => {
    const v = videoRef.current
    if (!v || !streamUrl) return
    v.playbackRate = speed
  }, [streamUrl, speed])

  const onVideoLoaded = () => {
    const v = videoRef.current
    if (v) v.playbackRate = speed
  }

  const handleLoad = async (e) => {
    e.preventDefault()
    const url = urlInput.trim()
    if (!url) return

    setError(null)
    setLoading(true)
    setTitle('')
    setThumbnailUrl(null)
    setFormats([])
    setVideoPageUrl('')
    setSelectedFormat('')
    setStreamUrl('')
    setStreamError(null)

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
      const fmts = data.formats ?? []
      setFormats(fmts)
      setVideoPageUrl(url)
      if (fmts.length > 0) setSelectedFormat(fmts[0].format)
    } catch (err) {
      setError(err.message || 'Failed to load video info')
    } finally {
      setLoading(false)
    }
  }

  const setPlaybackSpeed = (rate) => {
    setSpeed(rate)
    if (videoRef.current) videoRef.current.playbackRate = rate
  }

  const showPlayerBlock = formats.length > 0 && videoPageUrl && selectedFormat

  return (
    <div className="app">
      <header className="app-header">
        <h1 className="logo">SpeedTube</h1>
        <p className="tagline">Paste a URL, pick quality, play beyond 2×</p>
      </header>

      <form className="load-form" onSubmit={handleLoad}>
        <label className="sr-only" htmlFor="video-url">
          YouTube URL
        </label>
        <input
          id="video-url"
          type="url"
          className="url-input"
          placeholder="https://www.youtube.com/watch?v=…"
          value={urlInput}
          onChange={(e) => setUrlInput(e.target.value)}
          autoComplete="off"
        />
        <button type="submit" className="btn btn-primary" disabled={loading}>
          {loading ? 'Loading…' : 'Load Video'}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {title && (
        <section className="meta">
          <h2 className="video-title">{title}</h2>
          {thumbnailUrl && (
            <img
              className="thumb"
              src={thumbnailUrl}
              alt=""
            />
          )}
        </section>
      )}

      {formats.length > 0 && (
        <div className="quality-row">
          <label htmlFor="quality">Quality</label>
          <select
            id="quality"
            className="quality-select"
            value={selectedFormat}
            onChange={(e) => setSelectedFormat(e.target.value)}
          >
            {formats.map((f) => (
              <option key={f.label} value={f.format}>
                {f.label}
              </option>
            ))}
          </select>
        </div>
      )}

      {streamLoading && (
        <p className="stream-status">Resolving direct stream…</p>
      )}

      {streamError && <p className="error">{streamError}</p>}

      {showPlayerBlock && streamUrl && !streamLoading && (
        <>
          <div className="video-wrap">
            <video
              ref={videoRef}
              className="player"
              controls
              playsInline
              src={streamUrl}
              onLoadedData={onVideoLoaded}
            />
          </div>

          <div className="speed-section">
            <span className="speed-label">Playback speed</span>
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
        </>
      )}
    </div>
  )
}

export default App
