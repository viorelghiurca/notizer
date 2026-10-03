import { useCallback, useEffect, useMemo, useState } from 'react'
import { isTauri } from '@tauri-apps/api/core'
import { api } from './lib/api'
import type { CoreInfo, Counts, Folder, Recording } from './lib/api'
import { useTheme } from './lib/theme'
import { Sidebar } from './components/Sidebar'
import { RecordingList } from './components/RecordingList'
import { RecordingDetail } from './components/RecordingDetail'
import { DevicePage, SettingsPage, TemplatesPage } from './components/Pages'
import { IconUpload } from './components/Icons'

export type ListView =
  | { kind: 'all' }
  | { kind: 'unfiled' }
  | { kind: 'trash' }
  | { kind: 'folder'; id: string }

export type View =
  | { page: 'recordings'; list: ListView }
  | { page: 'templates' }
  | { page: 'device' }
  | { page: 'settings' }

interface Toast {
  id: number
  text: string
  error?: boolean
}

const AUDIO_EXT = /\.(mp3|m4a|wav)$/i

async function confirmAction(message: string): Promise<boolean> {
  if (isTauri()) {
    const { ask } = await import('@tauri-apps/plugin-dialog')
    return ask(message, { title: 'Notizer', kind: 'warning', okLabel: 'Löschen', cancelLabel: 'Abbrechen' })
  }
  return window.confirm(message)
}

export default function App() {
  const theme = useTheme()
  const [view, setView] = useState<View>({ page: 'recordings', list: { kind: 'all' } })
  const [coreState, setCoreState] = useState<'connecting' | 'ok' | 'error'>('connecting')
  const [info, setInfo] = useState<CoreInfo | null>(null)
  const [folders, setFolders] = useState<Folder[]>([])
  const [counts, setCounts] = useState<Counts | null>(null)
  const [recordings, setRecordings] = useState<Recording[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [dragging, setDragging] = useState(false)
  const [toasts, setToasts] = useState<Toast[]>([])

  const toast = useCallback((text: string, error = false) => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, text, error }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), error ? 6000 : 3500)
  }, [])

  const list: ListView = view.page === 'recordings' ? view.list : { kind: 'all' }
  const listKey = JSON.stringify(list)

  const refreshSidebar = useCallback(async () => {
    const [f, c] = await Promise.all([api.folders(), api.counts()])
    setFolders(f)
    setCounts(c)
  }, [])

  const refreshList = useCallback(async () => {
    const recs = await api.recordings({
      folderId: list.kind === 'folder' ? list.id : undefined,
      unfiled: list.kind === 'unfiled',
      trash: list.kind === 'trash',
      q: debounced || undefined,
    })
    setRecordings(recs)
    setSelectedId((cur) => (cur && recs.some((r) => r.id === cur) ? cur : (recs[0]?.id ?? null)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listKey, debounced])

  // Verbindung zum Core
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        await api.health()
        const i = await api.info()
        if (!alive) return
        setInfo(i)
        setCoreState('ok')
        await refreshSidebar()
      } catch {
        if (alive) setCoreState('error')
      }
    })()
    return () => {
      alive = false
    }
  }, [refreshSidebar])

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250)
    return () => clearTimeout(t)
  }, [query])

  useEffect(() => {
    if (coreState !== 'ok') return
    refreshList().catch((e: Error) => toast(e.message, true))
  }, [coreState, refreshList, toast])

  const refreshAll = useCallback(async () => {
    await Promise.all([refreshList(), refreshSidebar()])
  }, [refreshList, refreshSidebar])

  const importFiles = useCallback(
    async (files: File[]) => {
      const audio = files.filter((f) => AUDIO_EXT.test(f.name))
      const ignored = files.length - audio.length
      if (!audio.length) {
        toast('Nur MP3, M4A und WAV werden unterstützt.', true)
        return
      }
      try {
        const folderId = list.kind === 'folder' ? list.id : undefined
        const res = await api.importFiles(audio, folderId)
        if (list.kind === 'trash') setView({ page: 'recordings', list: { kind: 'all' } })
        await refreshAll()
        if (res.imported[0]) setSelectedId(res.imported[0].id)
        const n = res.imported.length
        toast(n === 1 ? `„${res.imported[0].title}“ importiert` : `${n} Aufnahmen importiert`)
        const skipped = res.skipped.length + ignored
        if (skipped) toast(`${skipped} Datei(en) übersprungen – nur MP3, M4A und WAV.`, true)
      } catch (e) {
        toast((e as Error).message, true)
      }
    },
    [list, refreshAll, toast],
  )

  // Dateien ins Fenster ziehen
  useEffect(() => {
    let depth = 0
    const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer?.types ?? []).includes('Files')
    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return
      depth++
      setDragging(true)
    }
    const leave = (e: DragEvent) => {
      if (!hasFiles(e)) return
      depth = Math.max(0, depth - 1)
      if (depth === 0) setDragging(false)
    }
    const over = (e: DragEvent) => hasFiles(e) && e.preventDefault()
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return
      e.preventDefault()
      depth = 0
      setDragging(false)
      const files = Array.from(e.dataTransfer?.files ?? [])
      if (files.length && coreState === 'ok') void importFiles(files)
    }
    window.addEventListener('dragenter', enter)
    window.addEventListener('dragleave', leave)
    window.addEventListener('dragover', over)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragenter', enter)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('dragover', over)
      window.removeEventListener('drop', drop)
    }
  }, [importFiles, coreState])

  const selected = useMemo(() => recordings.find((r) => r.id === selectedId) ?? null, [recordings, selectedId])

  const run = async (action: () => Promise<unknown>, message?: string) => {
    try {
      await action()
      await refreshAll()
      if (message) toast(message)
    } catch (e) {
      toast((e as Error).message, true)
    }
  }

  const title =
    list.kind === 'all'
      ? 'Aufnahmen'
      : list.kind === 'unfiled'
        ? 'Nicht zugeordnet'
        : list.kind === 'trash'
          ? 'Papierkorb'
          : (folders.find((f) => f.id === list.id)?.name ?? 'Ordner')

  const navigate = (next: View) => {
    setView(next)
    setQuery('')
  }

  return (
    <div className={`app ${view.page === 'recordings' ? '' : 'wide'}`}>
      <Sidebar
        view={view}
        onNavigate={navigate}
        folders={folders}
        counts={counts}
        coreState={coreState}
        dark={theme.dark}
        onToggleTheme={theme.toggle}
        onCreateFolder={(name) => void run(() => api.createFolder(name), `Ordner „${name}“ angelegt`)}
      />

      {view.page === 'recordings' && (
        <>
          <RecordingList
            title={title}
            trash={list.kind === 'trash'}
            recordings={recordings}
            selectedId={selectedId}
            onSelect={setSelectedId}
            query={query}
            onQuery={setQuery}
            onImport={(files) => void importFiles(files)}
            trashDays={info?.trash_days ?? 30}
            onEmptyTrash={async () => {
              if (await confirmAction('Alle Aufnahmen im Papierkorb endgültig löschen?')) {
                void run(() => api.emptyTrash(), 'Papierkorb geleert')
              }
            }}
          />
          {selected ? (
            <RecordingDetail
              key={selected.id}
              recording={selected}
              folders={folders}
              onError={(m) => toast(m, true)}
              onChange={(rec) => {
                setRecordings((rs) => rs.map((r) => (r.id === rec.id ? rec : r)))
                void refreshSidebar()
                if (list.kind === 'folder' && rec.folder_id !== list.id) void refreshList()
                if (list.kind === 'unfiled' && rec.folder_id) void refreshList()
              }}
              onTrash={(id) => void run(() => api.trashRecording(id), 'In den Papierkorb verschoben')}
              onRestore={(id) => void run(() => api.restoreRecording(id), 'Wiederhergestellt')}
              onDeleteForever={async (id) => {
                if (await confirmAction('Diese Aufnahme endgültig löschen? Das lässt sich nicht rückgängig machen.')) {
                  void run(() => api.deleteRecording(id), 'Endgültig gelöscht')
                }
              }}
            />
          ) : (
            <main className="detail">
              <EmptyState coreState={coreState} trash={list.kind === 'trash'} />
            </main>
          )}
        </>
      )}
      {view.page === 'templates' && <TemplatesPage />}
      {view.page === 'device' && <DevicePage />}
      {view.page === 'settings' && <SettingsPage theme={theme.choice} onTheme={theme.setChoice} info={info} />}

      {dragging && (
        <div className="drop-overlay">
          <div>Loslassen zum Importieren</div>
        </div>
      )}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.error ? 'error' : ''}`}>{t.text}</div>
        ))}
      </div>
    </div>
  )
}

function EmptyState({ coreState, trash }: { coreState: string; trash: boolean }) {
  if (coreState === 'error') {
    return (
      <div className="dropzone">
        <h2>Core nicht erreichbar</h2>
        <p>Der Hintergrunddienst von Notizer antwortet nicht. Starte die App neu.</p>
      </div>
    )
  }
  if (trash) {
    return (
      <div className="dropzone" style={{ borderStyle: 'solid' }}>
        <h2>Nichts ausgewählt</h2>
        <p>Gelöschte Aufnahmen lassen sich hier wiederherstellen oder endgültig entfernen.</p>
      </div>
    )
  }
  return (
    <div className="dropzone">
      <IconUpload size={32} />
      <h2>Audiodatei hierher ziehen</h2>
      <p>MP3, M4A oder WAV vom Handy, Diktiergerät oder aus einem Mitschnitt. So wird jedes Gerät zum Pod.</p>
    </div>
  )
}
