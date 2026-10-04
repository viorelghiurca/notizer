import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { Job, Segment, Speaker, Transcript } from '../lib/api'
import { clock, detailDate, languageName, speakerColor } from '../lib/format'

// ---------- Fortschritt ----------

export function JobProgress({ job, onCancel }: { job: Job; onCancel: () => void }) {
  const pct = Math.round(job.progress * 100)
  const downloading = /herunter|Lade .*modell/i.test(job.stage)
  return (
    <div className="progress-card" role="status">
      <h3>{job.status === 'wartet' ? 'Wartet auf den Start …' : 'Wird transkribiert'}</h3>
      <div className="progress-bar" aria-hidden="true">
        <div style={{ width: `${Math.max(2, pct)}%` }} />
      </div>
      <div className="progress-meta">
        <span>{job.stage}</span>
        <span className="mono">{pct} %</span>
      </div>
      {downloading && <p className="hint">Die Modelle werden nur beim ersten Mal geladen. Danach geht es ohne Internet.</p>}
      <button className="btn sm" onClick={onCancel}>Abbrechen</button>
    </div>
  )
}

// ---------- Transkript ----------

interface ViewProps {
  transcript: Transcript
  currentMs: number
  playing: boolean
  onSeek: (ms: number) => void
  onChanged: (t: Transcript) => void
  onRetranscribe: () => void
  onError: (m: string) => void
}

export function TranscriptView({ transcript, currentMs, playing, onSeek, onChanged, onRetranscribe, onError }: ViewProps) {
  const speakers = useMemo(() => new Map(transcript.speakers.map((s) => [s.label, s])), [transcript.speakers])
  const activeId = useMemo(() => {
    const seg = transcript.segments.find((s) => currentMs >= s.start_ms && currentMs < s.end_ms)
    return seg?.id ?? null
  }, [transcript.segments, currentMs])
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!playing || !activeId) return
    listRef.current?.querySelector(`[data-seg="${activeId}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [activeId, playing])

  const totalTalk = transcript.speakers.reduce((a, s) => a + s.talk_ms, 0) || 1

  const updateSegment = async (seg: Segment, patch: Partial<Pick<Segment, 'text' | 'speaker_label'>>) => {
    try {
      const saved = await api.updateSegment(seg.id, patch)
      onChanged({ ...transcript, segments: transcript.segments.map((s) => (s.id === saved.id ? saved : s)) })
      if (patch.speaker_label !== undefined) onChanged(await api.transcript(transcript.recording_id))
    } catch (e) {
      onError((e as Error).message)
    }
  }

  const rename = async (spk: Speaker, name: string) => {
    if ((spk.name ?? '') === name.trim()) return
    try {
      await api.renameSpeaker(transcript.recording_id, spk.label, name)
      onChanged(await api.transcript(transcript.recording_id))
    } catch (e) {
      onError((e as Error).message)
    }
  }

  return (
    <div className="transcript">
      <div className="transcript-main" ref={listRef}>
        {transcript.segments.length === 0 && (
          <p className="hint" style={{ textAlign: 'center', marginTop: 48 }}>In dieser Aufnahme wurde keine Sprache erkannt.</p>
        )}
        {transcript.segments.map((seg) => (
          <SegmentRow
            key={seg.id}
            seg={seg}
            speaker={seg.speaker_label ? speakers.get(seg.speaker_label) : undefined}
            speakers={transcript.speakers}
            active={seg.id === activeId}
            onSeek={() => onSeek(seg.start_ms)}
            onSave={(patch) => updateSegment(seg, patch)}
          />
        ))}
      </div>

      <aside className="transcript-rail">
        {transcript.speakers.length > 0 && (
          <section>
            <h3 className="rail-title">Sprecher erkannt</h3>
            <p className="hint" style={{ margin: '0 0 12px' }}>Namen anklicken zum Umbenennen.</p>
            {transcript.speakers.map((s) => (
              <SpeakerRow key={s.label} speaker={s} share={s.talk_ms / totalTalk} onRename={(n) => rename(s, n)} />
            ))}
          </section>
        )}
        <section>
          <h3 className="rail-title">Transkript</h3>
          <dl className="facts">
            {transcript.language && (<><dt>Sprache</dt><dd>{languageName(transcript.language)}</dd></>)}
            {transcript.model && (<><dt>Modell</dt><dd className="mono">{transcript.model}</dd></>)}
            {transcript.transcribed_at && (<><dt>Erstellt</dt><dd>{detailDate(transcript.transcribed_at)}</dd></>)}
            <dt>Abschnitte</dt><dd>{transcript.segments.length}</dd>
          </dl>
          <button className="btn sm" onClick={onRetranscribe}>Neu transkribieren</button>
        </section>
      </aside>
    </div>
  )
}

function SpeakerRow({ speaker, share, onRename }: { speaker: Speaker; share: number; onRename: (name: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(speaker.name ?? '')
  useEffect(() => setValue(speaker.name ?? ''), [speaker.name])
  const pct = Math.round(share * 100)
  const commit = () => {
    setEditing(false)
    onRename(value)
  }
  return (
    <div className="speaker-row">
      <div className="speaker-line">
        <span className="dot" style={{ background: speakerColor(speaker.idx) }} />
        {editing ? (
          <input
            className="speaker-input"
            autoFocus
            value={value}
            placeholder={speaker.label}
            aria-label={`Name für ${speaker.label}`}
            onChange={(e) => setValue(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commit()
              if (e.key === 'Escape') {
                setValue(speaker.name ?? '')
                setEditing(false)
              }
            }}
          />
        ) : (
          <button className="speaker-name" onClick={() => setEditing(true)} title="Umbenennen">
            {speaker.name || speaker.label}
          </button>
        )}
        <span className="mono share">{pct} %</span>
      </div>
      <div className="share-bar"><div style={{ width: `${pct}%`, background: speakerColor(speaker.idx) }} /></div>
    </div>
  )
}

interface RowProps {
  seg: Segment
  speaker?: Speaker
  speakers: Speaker[]
  active: boolean
  onSeek: () => void
  onSave: (patch: Partial<Pick<Segment, 'text' | 'speaker_label'>>) => void
}

function SegmentRow({ seg, speaker, speakers, active, onSeek, onSave }: RowProps) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(seg.text)
  const [picking, setPicking] = useState(false)
  const area = useRef<HTMLTextAreaElement>(null)

  useEffect(() => setText(seg.text), [seg.text])
  useEffect(() => {
    if (editing && area.current) {
      area.current.style.height = 'auto'
      area.current.style.height = `${area.current.scrollHeight}px`
    }
  }, [editing, text])

  const commit = () => {
    setEditing(false)
    const t = text.trim()
    if (!t) return setText(seg.text)
    if (t !== seg.text) onSave({ text: t })
  }

  return (
    <div className={`seg ${active ? 'active' : ''}`} data-seg={seg.id}>
      <button className="seg-time mono" onClick={onSeek} title="Ab hier abspielen">{clock(seg.start_ms)}</button>
      <div className="seg-body">
        {speaker && (
          <div className="seg-speaker">
            <span className="dot" style={{ background: speakerColor(speaker.idx) }} />
            {picking ? (
              <select
                className="speaker-select"
                autoFocus
                value={seg.speaker_label ?? ''}
                aria-label="Sprecher für diesen Abschnitt"
                onBlur={() => setPicking(false)}
                onChange={(e) => {
                  setPicking(false)
                  if (e.target.value !== seg.speaker_label) onSave({ speaker_label: e.target.value })
                }}
              >
                {speakers.map((s) => (
                  <option key={s.label} value={s.label}>{s.name || s.label}</option>
                ))}
              </select>
            ) : (
              <button className="speaker-name" onClick={() => setPicking(true)} title="Anderen Sprecher zuordnen">
                {speaker.name || speaker.label}
              </button>
            )}
          </div>
        )}
        {editing ? (
          <textarea
            ref={area}
            className="seg-edit"
            autoFocus
            value={text}
            aria-label="Text bearbeiten"
            onChange={(e) => setText(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === 'Escape') {
                setText(seg.text)
                setEditing(false)
              }
              if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) commit()
            }}
          />
        ) : (
          <p className="seg-text" onClick={() => setEditing(true)} title="Klicken zum Bearbeiten">
            {seg.text}
            {seg.edited && <span className="edited"> · bearbeitet</span>}
          </p>
        )}
      </div>
    </div>
  )
}
