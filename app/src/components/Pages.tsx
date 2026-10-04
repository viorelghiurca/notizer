import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { AppSettings, CoreInfo, ModelsOverview } from '../lib/api'
import { LANGUAGES } from '../lib/format'
import type { ThemeChoice } from '../lib/theme'

export function TemplatesPage() {
  return (
    <div className="page">
      <h1>Vorlagen</h1>
      <div className="card">
        <span className="badge">Kommt in M3</span>
        <h2>Vorlagen-Bibliothek</h2>
        <p>
          Hier entstehen eigene und mitgelieferte Vorlagen für Zusammenfassungen: Abschnitte an- und
          ausschalten, Anweisungen an die KI, Länge, Ton und Vorschau.
        </p>
      </div>
    </div>
  )
}

export function DevicePage() {
  return (
    <div className="page">
      <h1>Gerät &amp; Sync</h1>
      <div className="card">
        <span className="badge">Kommt in M4</span>
        <h2>Notizer Pod</h2>
        <p>
          Der Pod synchronisiert später per Bluetooth, WLAN oder USB-Kabel. Bis dahin wird jedes Gerät
          zum Pod: Aufnahmen vom Handy oder Diktiergerät als MP3, M4A oder WAV importieren.
        </p>
      </div>
    </div>
  )
}

interface SettingsProps {
  theme: ThemeChoice
  onTheme: (t: ThemeChoice) => void
  info: CoreInfo | null
  onError: (m: string) => void
}

function TranscriptionSettings({ onError }: { onError: (m: string) => void }) {
  const [s, setS] = useState<AppSettings | null>(null)
  const [models, setModels] = useState<ModelsOverview | null>(null)
  const [vocab, setVocab] = useState('')

  useEffect(() => {
    void Promise.all([api.settings(), api.models()]).then(([a, m]) => {
      setS(a)
      setVocab(a.vocabulary)
      setModels(m)
    }, (e: Error) => onError(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const update = async (patch: Partial<AppSettings>) => {
    try {
      setS(await api.updateSettings(patch))
    } catch (e) {
      onError((e as Error).message)
    }
  }

  if (!s || !models) return null
  return (
    <section className="card" aria-labelledby="s-tr">
      <h2 id="s-tr">Transkription</h2>
      <span className="field-label">Sprachmodell (faster-whisper, lokal)</span>
      <div className="model-grid" role="radiogroup" aria-label="Sprachmodell">
        {models.whisper.map((m) => (
          <button
            key={m.name}
            role="radio"
            aria-checked={s.whisper_model === m.name}
            className={`model-card ${s.whisper_model === m.name ? 'on' : ''}`}
            onClick={() => void update({ whisper_model: m.name })}
          >
            <span className="name">{m.label}</span>
            <span className="meta">{m.hint}</span>
            <span className="meta">
              {m.downloaded ? <span className="chip ok">Geladen</span> : `ca. ${(m.size_mb / 1000).toFixed(1).replace('.', ',')} GB, lädt beim ersten Gebrauch`}
            </span>
          </button>
        ))}
      </div>
      <div className="field-grid">
        <div className="field">
          <label className="field-label" htmlFor="s-lang">Standardsprache</label>
          <select id="s-lang" className="select" value={s.language} onChange={(e) => void update({ language: e.target.value })}>
            {LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>{l.label}</option>
            ))}
          </select>
        </div>
      </div>
      <div className="toggle-row">
        <div>
          <div className="field-label">Sprecher automatisch kennzeichnen</div>
          <div className="hint">Sprechertrennung mit sherpa-onnx, ca. 33 MB, lädt beim ersten Gebrauch.</div>
        </div>
        <button
          className={`switch ${s.diarize ? 'on' : ''}`}
          role="switch"
          aria-checked={s.diarize}
          aria-label="Sprecher automatisch kennzeichnen"
          onClick={() => void update({ diarize: !s.diarize })}
        >
          <span />
        </button>
      </div>
      <div className="field">
        <label className="field-label" htmlFor="s-vocab">Eigene Begriffe</label>
        <textarea
          id="s-vocab"
          className="textarea"
          placeholder="z. B. Citrix, Finanz Informatik, OSPlus"
          value={vocab}
          onChange={(e) => setVocab(e.target.value)}
          onBlur={() => vocab !== s.vocabulary && void update({ vocabulary: vocab })}
        />
        <span className="hint">Namen und Fachbegriffe, die richtig geschrieben werden sollen, durch Kommas getrennt.</span>
      </div>
      <span className="hint">Modelle liegen in: <span className="mono">{models.models_dir}</span></span>
    </section>
  )
}

export function SettingsPage({ theme, onTheme, info, onError }: SettingsProps) {
  const options: { value: ThemeChoice; label: string }[] = [
    { value: 'hell', label: 'Hell' },
    { value: 'dunkel', label: 'Dunkel' },
    { value: 'system', label: 'System' },
  ]
  return (
    <div className="page">
      <h1>Einstellungen</h1>
      <section className="card" aria-labelledby="s-look">
        <h2 id="s-look">Darstellung</h2>
        <span className="field-label">Farbschema</span>
        <div className="segmented" role="radiogroup" aria-label="Farbschema">
          {options.map((o) => (
            <button key={o.value} role="radio" aria-checked={theme === o.value} className={theme === o.value ? 'on' : ''} onClick={() => onTheme(o.value)}>
              {o.label}
            </button>
          ))}
        </div>
        <p style={{ fontSize: 13, color: 'var(--muted)' }}>„System“ folgt dem hellen oder dunklen Modus von Windows bzw. Linux.</p>
      </section>
      <TranscriptionSettings onError={onError} />
      <section className="card" aria-labelledby="s-store">
        <h2 id="s-store">Speicher</h2>
        <span className="field-label">Datenordner</span>
        <div className="path">{info?.data_dir ?? '…'}</div>
        <p>
          Aufnahmen und Datenbank liegen nur auf diesem PC. Der Papierkorb wird nach {info?.trash_days ?? 30} Tagen
          automatisch geleert.
        </p>
      </section>
      <section className="card" aria-labelledby="s-about">
        <h2 id="s-about">Über Notizer</h2>
        <p>Version {info?.version ?? '…'} · Meilenstein M1</p>
      </section>
    </div>
  )
}
