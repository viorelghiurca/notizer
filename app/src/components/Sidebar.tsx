import { useState } from 'react'
import type { Counts, Folder } from '../lib/api'
import type { View } from '../App'
import {
  IconFolder,
  IconInbox,
  IconList,
  IconMic,
  IconMoon,
  IconPlus,
  IconSettings,
  IconTemplate,
  IconTrash,
} from './Icons'

interface Props {
  view: View
  onNavigate: (view: View) => void
  folders: Folder[]
  counts: Counts | null
  onCreateFolder: (name: string) => void
  coreState: 'connecting' | 'ok' | 'error'
  dark: boolean
  onToggleTheme: () => void
}

const isList = (v: View, kind: string, id?: string) =>
  v.page === 'recordings' && v.list.kind === kind && (id === undefined || ('id' in v.list && v.list.id === id))

export function Sidebar({ view, onNavigate, folders, counts, onCreateFolder, coreState, dark, onToggleTheme }: Props) {
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')

  const submit = () => {
    const n = name.trim()
    if (n) onCreateFolder(n)
    setName('')
    setAdding(false)
  }

  const item = (active: boolean, extra = '') => `nav-item ${extra} ${active ? 'active' : ''}`

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-dot" aria-hidden="true" />
        Notizer
      </div>

      <nav className="nav" aria-label="Hauptmenü">
        <button className={item(isList(view, 'all'))} onClick={() => onNavigate({ page: 'recordings', list: { kind: 'all' } })}>
          <IconList />Aufnahmen<span className="count">{counts?.all ?? ''}</span>
        </button>
        <button className={item(view.page === 'templates')} onClick={() => onNavigate({ page: 'templates' })}>
          <IconTemplate />Vorlagen
        </button>
        <button className={item(view.page === 'device')} onClick={() => onNavigate({ page: 'device' })}>
          <IconMic />Gerät &amp; Sync
        </button>
        <button className={item(view.page === 'settings')} onClick={() => onNavigate({ page: 'settings' })}>
          <IconSettings />Einstellungen
        </button>
      </nav>

      <div className="nav-section">
        <span className="nav-label">Ordner</span>
        {folders.map((f) => (
          <button
            key={f.id}
            className={item(isList(view, 'folder', f.id), 'small')}
            onClick={() => onNavigate({ page: 'recordings', list: { kind: 'folder', id: f.id } })}
          >
            <IconFolder />
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.name}</span>
            <span className="count">{f.count}</span>
          </button>
        ))}
        <button className={item(isList(view, 'unfiled'), 'small')} onClick={() => onNavigate({ page: 'recordings', list: { kind: 'unfiled' } })}>
          <IconInbox />Nicht zugeordnet<span className="count">{counts?.unfiled ?? ''}</span>
        </button>
        {adding ? (
          <input
            className="folder-input"
            autoFocus
            placeholder="Name des Ordners"
            aria-label="Name des neuen Ordners"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={submit}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit()
              if (e.key === 'Escape') {
                setName('')
                setAdding(false)
              }
            }}
          />
        ) : (
          <button className="nav-item small muted" onClick={() => setAdding(true)}>
            <IconPlus />Neuer Ordner
          </button>
        )}
        <button
          className={item(isList(view, 'trash'), 'small')}
          style={{ marginTop: 8 }}
          onClick={() => onNavigate({ page: 'recordings', list: { kind: 'trash' } })}
        >
          <IconTrash />Papierkorb<span className="count">{counts?.trash || ''}</span>
        </button>
      </div>

      <div className="sidebar-foot">
        <div className="core-state" role="status">
          <span className={`core-dot ${coreState === 'ok' ? 'ok' : coreState === 'error' ? 'err' : ''}`} />
          {coreState === 'ok' ? 'Core läuft' : coreState === 'error' ? 'Core nicht erreichbar' : 'Core startet …'}
        </div>
        <button className="theme-toggle" onClick={onToggleTheme}>
          <IconMoon />{dark ? 'Helles Design' : 'Dunkles Design'}
        </button>
      </div>
    </aside>
  )
}
