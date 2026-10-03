// Verbindung zum Notizer Core.
//
// In der Desktop-App startet Tauri den Core und gibt Port und Token über den
// Befehl `core_info` heraus. Im Browser (Entwicklung ohne Tauri) läuft der Core
// manuell mit festem Port und Token, siehe README.

import { invoke, isTauri } from '@tauri-apps/api/core'

export type RecordingStatus = 'nur_audio' | 'wird_transkribiert' | 'transkribiert' | 'fehler'

export interface Recording {
  id: string
  title: string
  folder_id: string | null
  recorded_at: string
  created_at: string
  duration_s: number | null
  source: 'import' | 'pod'
  status: RecordingStatus
  favorite: boolean
  deleted_at: string | null
  format: string | null
  original_name: string | null
  size_bytes: number | null
}

export interface Folder {
  id: string
  name: string
  sort: number
  count: number
}

export interface Counts {
  all: number
  unfiled: number
  trash: number
}

export interface CoreInfo {
  version: string
  data_dir: string
  allowed_extensions: string[]
  trash_days: number
}

export interface ImportResult {
  imported: Recording[]
  skipped: { name: string; reason: string }[]
}

interface Connection {
  base: string
  token: string
}

let connection: Connection | null = null

async function connect(): Promise<Connection> {
  if (connection) return connection
  if (isTauri()) {
    // Der Core braucht beim ersten Start ein paar Sekunden.
    for (let i = 0; i < 120; i++) {
      const info = await invoke<{ port: number; token: string } | null>('core_info')
      if (info) {
        connection = { base: `http://127.0.0.1:${info.port}`, token: info.token }
        return connection
      }
      await new Promise((r) => setTimeout(r, 250))
    }
    throw new Error('Der Notizer Core ist nicht gestartet.')
  }
  const port = import.meta.env.VITE_CORE_PORT ?? '8765'
  const token = import.meta.env.VITE_CORE_TOKEN ?? 'dev'
  connection = { base: `http://127.0.0.1:${port}`, token }
  return connection
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { base, token } = await connect()
  const res = await fetch(base + path, {
    ...init,
    headers: { 'X-Notizer-Token': token, ...(init.headers ?? {}) },
  })
  if (!res.ok) {
    let message = `Fehler ${res.status}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      /* keine JSON-Antwort */
    }
    throw new Error(message)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export interface ListFilter {
  folderId?: string
  unfiled?: boolean
  trash?: boolean
  q?: string
}

export const api = {
  health: () => request<{ status: string; version: string }>('/api/health'),
  info: () => request<CoreInfo>('/api/info'),
  counts: () => request<Counts>('/api/counts'),

  recordings(filter: ListFilter = {}) {
    const p = new URLSearchParams()
    if (filter.folderId) p.set('folder_id', filter.folderId)
    if (filter.unfiled) p.set('unfiled', 'true')
    if (filter.trash) p.set('trash', 'true')
    if (filter.q) p.set('q', filter.q)
    const qs = p.toString()
    return request<Recording[]>(`/api/recordings${qs ? `?${qs}` : ''}`)
  },

  importFiles(files: File[], folderId?: string) {
    const form = new FormData()
    for (const f of files) {
      form.append('files', f, f.name)
      form.append('last_modified', String(f.lastModified || 0))
    }
    if (folderId) form.append('folder_id', folderId)
    return request<ImportResult>('/api/recordings/import', { method: 'POST', body: form })
  },

  updateRecording: (id: string, patch: Partial<Pick<Recording, 'title' | 'folder_id' | 'favorite'>>) =>
    request<Recording>(`/api/recordings/${id}`, json('PATCH', patch)),
  trashRecording: (id: string) => request<Recording>(`/api/recordings/${id}`, { method: 'DELETE' }),
  restoreRecording: (id: string) => request<Recording>(`/api/recordings/${id}/restore`, { method: 'POST' }),
  deleteRecording: (id: string) => request<void>(`/api/recordings/${id}/permanent`, { method: 'DELETE' }),
  emptyTrash: () => request<void>('/api/trash', { method: 'DELETE' }),

  async audioUrl(id: string) {
    const { base, token } = await connect()
    return `${base}/api/recordings/${id}/audio?token=${encodeURIComponent(token)}`
  },

  folders: () => request<Folder[]>('/api/folders'),
  createFolder: (name: string) => request<Folder>('/api/folders', json('POST', { name })),
  renameFolder: (id: string, name: string) => request<Folder>(`/api/folders/${id}`, json('PATCH', { name })),
  deleteFolder: (id: string) => request<void>(`/api/folders/${id}`, { method: 'DELETE' }),
}
