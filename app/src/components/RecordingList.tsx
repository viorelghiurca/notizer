import { useRef } from 'react'
import type { Job, Recording } from '../lib/api'
import { STATUS_LABEL, dayGroup, formatDuration, listTime, shortDate } from '../lib/format'
import { IconPlus, IconSearch, IconStar } from './Icons'

interface Props {
  title: string
  trash: boolean
  recordings: Recording[]
  selectedId: string | null
  onSelect: (id: string) => void
  query: string
  onQuery: (q: string) => void
  onImport: (files: File[]) => void
  onEmptyTrash: () => void
  trashDays: number
  jobs: Record<string, Job>
}

export const ACCEPT = '.mp3,.m4a,.wav,audio/mpeg,audio/mp4,audio/x-m4a,audio/wav,audio/x-wav'

const GROUP_ORDER = ['Heute', 'Gestern', 'Diese Woche', 'Älter']

export function RecordingList(props: Props) {
  const { title, trash, recordings, selectedId, onSelect, query, onQuery, onImport, onEmptyTrash, trashDays, jobs } = props
  const fileInput = useRef<HTMLInputElement>(null)

  const groups = trash
    ? recordings.length
      ? [{ label: `Werden nach ${trashDays} Tagen gelöscht`, items: recordings }]
      : []
    : GROUP_ORDER.map((label) => ({
        label,
        items: recordings.filter((r) => dayGroup(r.recorded_at) === label),
      })).filter((g) => g.items.length > 0)

  return (
    <section className="list-col" aria-label={title}>
      <div className="list-head">
        <div className="list-title-row">
          <h1 className="list-title">{title}</h1>
          {!trash && (
            <>
              <button className="icon-btn" aria-label="Audiodatei importieren" title="MP3, M4A oder WAV importieren" onClick={() => fileInput.current?.click()}>
                <IconPlus />
              </button>
              <input
                ref={fileInput}
                type="file"
                multiple
                accept={ACCEPT}
                hidden
                onChange={(e) => {
                  const files = Array.from(e.target.files ?? [])
                  if (files.length) onImport(files)
                  e.target.value = ''
                }}
              />
            </>
          )}
        </div>
        <label className="search">
          <IconSearch />
          <span className="sr-only">Aufnahmen suchen</span>
          <input type="search" placeholder="Aufnahmen suchen …" value={query} onChange={(e) => onQuery(e.target.value)} />
        </label>
      </div>

      <div className="list-body">
        {groups.length === 0 && (
          <p className="list-empty">
            {query
              ? 'Keine Aufnahme gefunden.'
              : trash
                ? 'Der Papierkorb ist leer.'
                : 'Noch keine Aufnahmen. Importiere eine MP3-, M4A- oder WAV-Datei mit „+“ oder ziehe sie ins Fenster.'}
          </p>
        )}
        {groups.map((g) => (
          <div key={g.label} style={{ display: 'contents' }}>
            <span className="group-label">{g.label}</span>
            {g.items.map((r) => (
              <button key={r.id} className={`row ${r.id === selectedId ? 'selected' : ''}`} onClick={() => onSelect(r.id)}>
                <span className="row-top">
                  <span className="row-title">
                    {r.favorite && <IconStar filled size={13} style={{ marginRight: 6, verticalAlign: '-1px', color: 'var(--accent)' }} />}
                    {r.title}
                  </span>
                  <span className="row-time">{trash && r.deleted_at ? shortDate(r.deleted_at) : listTime(r.recorded_at)}</span>
                </span>
                <span className="row-meta">
                  <span className="mono">{formatDuration(r.duration_s)}</span>
                  {r.format && (
                    <>
                      <span>·</span>
                      <span>{r.format.toUpperCase()}</span>
                    </>
                  )}
                  <span className={`chip ${r.status}`}>
                    {r.status === 'wird_transkribiert' && jobs[r.id]?.status === 'laeuft'
                      ? `Läuft … ${Math.round(jobs[r.id].progress * 100)} %`
                      : r.status === 'wird_transkribiert' && jobs[r.id]?.status === 'wartet'
                        ? 'Wartet'
                        : (STATUS_LABEL[r.status] ?? r.status)}
                  </span>
                </span>
              </button>
            ))}
          </div>
        ))}
      </div>

      {trash && recordings.length > 0 && (
        <div className="list-foot">
          <button className="btn danger full" onClick={onEmptyTrash}>Papierkorb leeren</button>
        </div>
      )}
    </section>
  )
}
