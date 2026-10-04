import { useCallback, useEffect, useRef, useState } from 'react'
import { isTauri } from '@tauri-apps/api/core'
import { api } from '../lib/api'
import type { Folder, Job, Recording, Transcript, TranscribeOptions } from '../lib/api'
import { detailDate, formatDuration, formatSize, languageName, speakerColor } from '../lib/format'
import { IconPause, IconPlay, IconRestore, IconSpark, IconStar, IconTrash, IconUpload } from './Icons'
import { TranscribeDialog } from './TranscribeDialog'
import { JobProgress, TranscriptView } from './Transcript'

interface Props {
  recording: Recording
  folders: Folder[]
  job?: Job
  transcriptVersion: string
  onChange: (rec: Recording) => void
  onTrash: (id: string) => void
  onRestore: (id: string) => void
  onDeleteForever: (id: string) => void
  onError: (message: string) => void
  onToast: (message: string) => void
  onOpenSettings: () => void
}

const TABS = ['Transkript', 'Notizen', 'Mindmap', 'E-Mail & Termine'] as const

export function RecordingDetail(props: Props) {
  const { recording, folders, job, transcriptVersion, onChange, onTrash, onRestore, onDeleteForever, onError, onToast, onOpenSettings } = props
  const [title, setTitle] = useState(recording.title)
  const [tab, setTab] = useState<(typeof TABS)[number]>('Transkript')
  const [transcript, setTranscript] = useState<Transcript | null>(null)
  const [dialog, setDialog] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [currentMs, setCurrentMs] = useState(0)
  const [playing, setPlaying] = useState(false)
  const seekRef = useRef<(ms: number) => void>(() => {})
  const inTrash = recording.deleted_at !== null
  const active = job && (job.status === 'wartet' || job.status === 'laeuft')

  useEffect(() => setTitle(recording.title), [recording.id, recording.title])

  // Fehlermeldung des letzten Versuchs auch nach einem Neustart der App zeigen
  const [lastError, setLastError] = useState<string | null>(null)
  useEffect(() => {
    setLastError(null)
    if (recording.status === 'fehler' && !job) {
      void api.lastJob(recording.id).then((j) => setLastError(j?.error ?? null), () => {})
    }
  }, [recording.id, recording.status, job])

  // Transkript laden, sobald eines da ist (oder nach einer neuen Transkription)
  useEffect(() => {
    let alive = true
    if (recording.status === 'transkribiert') {
      api.transcript(recording.id).then((t) => alive && setTranscript(t), (e: Error) => onError(e.message))
    } else if (!active) {
      setTranscript(null)
    }
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recording.id, recording.status, transcriptVersion])

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

  const start = async (options: TranscribeOptions) => {
    setDialog(false)
    try {
      await api.transcribe(recording.id, options)
      onChange({ ...recording, status: 'wird_transkribiert' })
    } catch (e) {
      onError((e as Error).message)
    }
  }

  const doExport = async (format: 'txt' | 'srt') => {
    setExportOpen(false)
    try {
      if (isTauri()) {
        const { save: saveDialog } = await import('@tauri-apps/plugin-dialog')
        const path = await saveDialog({
          defaultPath: `${recording.title}.${format}`,
          filters: [{ name: format === 'txt' ? 'Text' : 'Untertitel', extensions: [format] }],
        })
        if (!path) return
        await api.exportToFile(recording.id, format, path)
        onToast('Transkript gespeichert')
      } else {
        window.open(await api.exportUrl(recording.id, format), '_blank')
      }
    } catch (e) {
      onError((e as Error).message)
    }
  }

  const meta = [
    detailDate(recording.recorded_at),
    formatDuration(recording.duration_s),
    recording.format?.toUpperCase(),
    formatSize(recording.size_bytes),
    recording.language ? languageName(recording.language) : null,
    transcript?.speakers.length ? `${transcript.speakers.length} Sprecher` : null,
  ].filter(Boolean)

  const hasTranscript = !!transcript && recording.status === 'transkribiert'

  const seek = useCallback((ms: number) => seekRef.current(ms), [])

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
                {hasTranscript && (
                  <div className="menu-wrap">
                    <button className="btn" aria-haspopup="menu" aria-expanded={exportOpen} onClick={() => setExportOpen(!exportOpen)}>
                      <IconUpload />Exportieren
                    </button>
                    {exportOpen && (
                      <div className="menu" role="menu" onMouseLeave={() => setExportOpen(false)}>
                        <button role="menuitem" onClick={() => void doExport('txt')}>Text (.txt)</button>
                        <button role="menuitem" onClick={() => void doExport('srt')}>Untertitel (.srt)</button>
                      </div>
                    )}
                  </div>
                )}
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

      {tab === 'Transkript' && hasTranscript && !active ? (
        <TranscriptView
          transcript={transcript}
          currentMs={currentMs}
          playing={playing}
          onSeek={seek}
          onChanged={setTranscript}
          onRetranscribe={() => setDialog(true)}
          onError={onError}
        />
      ) : (
        <div className="detail-body">
          {tab !== 'Transkript' ? (
            <div className="pending">
              <span className="badge">Kommt in M3</span>
              <h3>{tab} noch nicht verfügbar</h3>
              <p>Zusammenfassungen, Mindmap, E-Mail-Entwürfe und Termine entstehen aus dem Transkript, sobald die KI-Auswertung eingebaut ist.</p>
            </div>
          ) : active && job ? (
            <JobProgress job={job} onCancel={() => void api.cancelJob(job.id).catch((e: Error) => onError(e.message))} />
          ) : (
            <div className="pending">
              {recording.status === 'fehler' ? (
                <>
                  <h3>Transkription fehlgeschlagen</h3>
                  <p>{job?.error ?? lastError ?? 'Beim letzten Versuch ist ein Fehler aufgetreten.'}</p>
                </>
              ) : (
                <>
                  <h3>Noch kein Transkript</h3>
                  <p>Notizer schreibt die Aufnahme lokal auf diesem PC mit und erkennt, wer wann spricht.</p>
                </>
              )}
              {!inTrash && (
                <button className="btn primary" onClick={() => setDialog(true)}>
                  <IconSpark />{recording.status === 'fehler' ? 'Erneut versuchen' : 'Transkribieren'}
                </button>
              )}
            </div>
          )}
        </div>
      )}

      <Player
        recordingId={recording.id}
        fallbackDuration={recording.duration_s}
        transcript={hasTranscript ? transcript : null}
        onError={onError}
        onTime={setCurrentMs}
        onPlaying={setPlaying}
        seekRef={seekRef}
      />

      {dialog && (
        <TranscribeDialog
          title={recording.title}
          durationS={recording.duration_s}
          onStart={(o) => void start(o)}
          onClose={() => setDialog(false)}
          onOpenSettings={() => {
            setDialog(false)
            onOpenSettings()
          }}
        />
      )}
    </main>
  )
}

interface PlayerProps {
  recordingId: string
  fallbackDuration: number | null
  transcript: Transcript | null
  onError: (m: string) => void
  onTime: (ms: number) => void
  onPlaying: (p: boolean) => void
  seekRef: React.MutableRefObject<(ms: number) => void>
}

function Player({ recordingId, fallbackDuration, transcript, onError, onTime, onPlaying, seekRef }: PlayerProps) {
  const audio = useRef<HTMLAudioElement>(null)
  const [src, setSrc] = useState<string>()
  const [playing, setPlaying] = useState(false)
  const [pos, setPos] = useState(0)
  const [dur, setDur] = useState(fallbackDuration ?? 0)
  const [rate, setRate] = useState(1)

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

  useEffect(() => onPlaying(playing), [playing, onPlaying])

  seekRef.current = (ms: number) => {
    const el = audio.current
    if (!el) return
    el.currentTime = ms / 1000
    setPos(ms / 1000)
    onTime(ms)
    if (el.paused) el.play().catch(() => onError('Die Datei lässt sich nicht abspielen.'))
  }

  const toggle = () => {
    const el = audio.current
    if (!el) return
    if (el.paused) el.play().catch(() => onError('Die Datei lässt sich nicht abspielen.'))
    else el.pause()
  }

  const cycleRate = () => {
    const next = rate >= 2 ? 0.75 : rate === 0.75 ? 1 : rate + 0.25
    setRate(next)
    if (audio.current) audio.current.playbackRate = next
  }

  const speakerIdx = new Map(transcript?.speakers.map((s) => [s.label, s.idx]) ?? [])
  const total = dur || fallbackDuration || 0

  return (
    <div className="player">
      <audio
        ref={audio}
        src={src}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => {
          setPos(e.currentTarget.currentTime)
          onTime(e.currentTarget.currentTime * 1000)
        }}
        onLoadedMetadata={(e) => Number.isFinite(e.currentTarget.duration) && setDur(e.currentTarget.duration)}
      />
      <button className="play-btn" aria-label={playing ? 'Pause' : 'Abspielen'} onClick={toggle}>
        {playing ? <IconPause /> : <IconPlay />}
      </button>
      <span className="player-time">{formatDuration(pos)}</span>
      <div className="seek-wrap">
        {transcript && total > 0 && (
          <div className="speaker-strip" aria-hidden="true">
            {transcript.segments.map((s) => (
              <span
                key={s.id}
                style={{
                  left: `${(s.start_ms / 1000 / total) * 100}%`,
                  width: `${Math.max(0.3, ((s.end_ms - s.start_ms) / 1000 / total) * 100)}%`,
                  background: s.speaker_label ? speakerColor(speakerIdx.get(s.speaker_label) ?? 0) : 'var(--off)',
                }}
              />
            ))}
          </div>
        )}
        <input
          className="seek"
          type="range"
          min={0}
          max={total}
          step={0.1}
          value={Math.min(pos, total)}
          aria-label="Position"
          onChange={(e) => {
            const t = Number(e.target.value)
            if (audio.current) audio.current.currentTime = t
            setPos(t)
            onTime(t * 1000)
          }}
        />
      </div>
      <span className="player-time total">{formatDuration(total || null)}</span>
      <button className="rate-btn mono" onClick={cycleRate} aria-label="Wiedergabegeschwindigkeit">
        {rate.toString().replace('.', ',')}×
      </button>
    </div>
  )
}
