import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { AppSettings, ModelsOverview, TranscribeOptions } from '../lib/api'
import { LANGUAGES, formatDuration } from '../lib/format'

interface Props {
  title: string
  durationS: number | null
  onStart: (options: TranscribeOptions) => void
  onClose: () => void
  onOpenSettings: () => void
}

export function TranscribeDialog({ title, durationS, onStart, onClose, onOpenSettings }: Props) {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [models, setModels] = useState<ModelsOverview | null>(null)
  const [language, setLanguage] = useState('de')
  const [diarize, setDiarize] = useState(true)
  const [speakers, setSpeakers] = useState<string>('auto')

  useEffect(() => {
    void Promise.all([api.settings(), api.models()]).then(([s, m]) => {
      setSettings(s)
      setModels(m)
      setLanguage(s.language)
      setDiarize(s.diarize)
    })
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const model = models?.whisper.find((m) => m.name === settings?.whisper_model)
  const needsDownload = (model && !model.downloaded) || (diarize && models && !models.diarization.downloaded)

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="tr-title">
        <div className="modal-head">
          <h2 id="tr-title">Transkribieren</h2>
          <span className="detail-meta">
            {title} · <span className="mono">{formatDuration(durationS)}</span>
          </span>
        </div>

        <div className="modal-body">
          <div className="field-grid">
            <div className="field">
              <label className="field-label" htmlFor="tr-lang">Sprache</label>
              <select id="tr-lang" className="select" value={language} onChange={(e) => setLanguage(e.target.value)}>
                {LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>{l.label}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label className="field-label" htmlFor="tr-spk">Anzahl Sprecher</label>
              <select id="tr-spk" className="select" value={speakers} disabled={!diarize} onChange={(e) => setSpeakers(e.target.value)}>
                <option value="auto">Automatisch erkennen</option>
                {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
                  <option key={n} value={n}>{n} {n === 1 ? 'Person' : 'Personen'}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="toggle-row">
            <div>
              <div className="field-label">Sprecher kennzeichnen</div>
              <div className="hint">Erkennt, wer wann spricht, und trennt das Transkript danach.</div>
            </div>
            <button
              className={`switch ${diarize ? 'on' : ''}`}
              role="switch"
              aria-checked={diarize}
              aria-label="Sprecher kennzeichnen"
              onClick={() => setDiarize(!diarize)}
            >
              <span />
            </button>
          </div>

          {model && (
            <p className="hint">
              Modell: <strong>{model.label}</strong> · läuft lokal auf diesem PC.{' '}
              {needsDownload && (
                <>Beim ersten Mal werden die Modelle einmalig heruntergeladen (ca. {(((model.downloaded ? 0 : model.size_mb) + (diarize && !models?.diarization.downloaded ? 33 : 0)) / 1000).toFixed(1).replace('.', ',')} GB). </>
              )}
              <button className="link" onClick={onOpenSettings}>Ändern</button>
            </p>
          )}
        </div>

        <div className="modal-foot">
          <button className="btn" onClick={onClose}>Abbrechen</button>
          <button
            className="btn accent"
            disabled={!settings}
            onClick={() =>
              onStart({
                language,
                diarize,
                num_speakers: diarize && speakers !== 'auto' ? Number(speakers) : null,
              })
            }
          >
            Jetzt starten
          </button>
        </div>
      </div>
    </div>
  )
}
