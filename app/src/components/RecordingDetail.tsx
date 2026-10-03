import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { Folder, Recording } from '../lib/api'
import { detailDate, formatDuration, formatSize } from '../lib/format'
import { IconPause, IconPlay, IconRestore, IconSpark, IconStar, IconTrash } from './Icons'

interface Props {
  recording: Recording
  folders: Folder[]
  onChange: (rec: Recording) => void
  onTrash: (id: string) => void
  onRestore: (id: string) => void
  onDeleteForever: (id: string) => void
  onError: (message: string) => void
}

const TABS = ['Transkript', 'Notizen', 'Mindmap', 'E-Mail & Termine'] as const

export function RecordingDetail({ recording, folders, onChange, onTrash, onRestore, onDeleteForever, onError }: Props) {
  const [title, setTitle] = useState(recording.title)
  const [tab, setTab] = useState<(typeof TABS)[number]>('Transkript')
  const inTrash = recording.deleted_at !== null

  useEffect(() => setTitle(recording.title), [recording.id, recording.title])

  const save = async (patch: Parameters<typeof api.updateRecording>[1]) => {
    try {
      onChange(await api.updateRecording(recording.id, patch))
    } catch (e) {
      onError((e as Error).message)
    }
  }

  const commitTitle = () => {
    const t = title.trim()
    if (!t) return setTitle(recording.title)
    if (t !== recording.title) void save({ title: t })
  }

  const meta = [
    detailDate(recording.recorded_at),
    formatDuration(recording.duration_s),
    recording.format?.toUpperCase(),
    formatSize(recording.size_bytes),
  ].filter(Boolean)

  return (
    <main className="detail">
      <header className="detail-head">
        <div className="detail-top">
          <div className="detail-titles">
            <label className="sr-only" htmlFor="rec-title">Titel</label>
            <input
              id="rec-title"
              className="title-input"
              value={title}
              disabled={inTrash}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={commitTitle}
              onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
            />
            <span className="detail-meta">{meta.join(' · ')}</span>
          </div>
          <div className="detail-actions">
            {inTrash ? (
              <>
                <button className="btn" onClick={() => onRestore(recording.id)}><IconRestore />Wiederherstellen</button>
                <button className="btn danger" onClick={() => onDeleteForever(recording.id)}>Endgültig löschen</button>
              </>
            ) : (
              <>
                <label className="sr-only" htmlFor="rec-folder">Ordner</label>
                <select
                  id="rec-folder"
                  className="select"
                  value={recording.folder_id ?? ''}
                  onChange={(e) => void save({ folder_id: e.target.value || null })}
                >
                  <option value="">Nicht zugeordnet</option>
                  {folders.map((f) => (
                    <option key={f.id} value={f.id}>{f.name}</option>
                  ))}
                </select>
                <button
                  className="icon-btn"
                  aria-label={recording.favorite ? 'Favorit entfernen' : 'Als Favorit markieren'}
                  aria-pressed={recording.favorite}
                  style={recording.favorite ? { color: 'var(--accent)' } : undefined}
                  onClick={() => void save({ favorite: !recording.favorite })}
                >
                  <IconStar filled={recording.favorite} size={18} />
                </button>
                <button className="icon-btn danger" aria-label="In den Papierkorb" onClick={() => onTrash(recording.id)}>
                  <IconTrash />
                </button>
              </>
            )}
          </div>
        </div>
        <div className="tabs" role="tablist">
          {TABS.map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
              {t}
            </button>
          ))}
        </div>
      </header>

      <div className="detail-body">
        <div className="pending">
          <span className="badge">{tab === 'Transkript' ? 'Kommt in M1' : 'Kommt in M3'}</span>
          <h3>{tab === 'Transkript' ? 'Noch kein Transkript' : `${tab} noch nicht verfügbar`}</h3>
          <p>
            {tab === 'Transkript'
              ? 'Die Aufnahme ist gespeichert und lässt sich unten abspielen. Transkription mit Sprechererkennung folgt im nächsten Meilenstein.'
              : 'Zusammenfassungen, Mindmap, E-Mail-Entwürfe und Termine entstehen aus dem Transkript, sobald die KI-Auswertung eingebaut ist.'}
          </p>
          <button className="btn primary" disabled title="Kommt in M1">
            <IconSpark />Transkribieren &amp; zusammenfassen
          </button>
        </div>
      </div>

      <Player recordingId={recording.id} fallbackDuration={recording.duration_s} onError={onError} />
    </main>
  )
}

function Player({ recordingId, fallbackDuration, onError }: { recordingId: string; fallbackDuration: number | null; onError: (m: string) => void }) {
  const audio = useRef<HTMLAudioElement>(null)
  const [src, setSrc] = useState<string>()
  const [playing, setPlaying] = useState(false)
  const [pos, setPos] = useState(0)
  const [dur, setDur] = useState(fallbackDuration ?? 0)

  useEffect(() => {
    let alive = true
    setPlaying(false)
    setPos(0)
    setDur(fallbackDuration ?? 0)
    void api.audioUrl(recordingId).then((url) => alive && setSrc(url))
    return () => {
      alive = false
    }
  }, [recordingId, fallbackDuration])

  const toggle = () => {
    const el = audio.current
    if (!el) return
    if (el.paused) el.play().catch(() => onError('Die Datei lässt sich nicht abspielen.'))
    else el.pause()
  }

  return (
    <div className="player">
      <audio
        ref={audio}
        src={src}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => setPos(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => Number.isFinite(e.currentTarget.duration) && setDur(e.currentTarget.duration)}
      />
      <button className="play-btn" aria-label={playing ? 'Pause' : 'Abspielen'} onClick={toggle}>
        {playing ? <IconPause /> : <IconPlay />}
      </button>
      <span className="player-time">{formatDuration(pos)}</span>
      <input
        className="seek"
        type="range"
        min={0}
        max={dur || 0}
        step={0.1}
        value={Math.min(pos, dur || 0)}
        aria-label="Position"
        onChange={(e) => {
          const t = Number(e.target.value)
          if (audio.current) audio.current.currentTime = t
          setPos(t)
        }}
      />
      <span className="player-time total">{formatDuration(dur || null)}</span>
    </div>
  )
}
