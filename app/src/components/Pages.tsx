import type { CoreInfo } from '../lib/api'
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
}

export function SettingsPage({ theme, onTheme, info }: SettingsProps) {
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
        <p>Version {info?.version ?? '…'} · Meilenstein M0</p>
      </section>
    </div>
  )
}
