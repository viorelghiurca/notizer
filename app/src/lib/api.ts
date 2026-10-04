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
  language: string | null
  transcript_model: string | null
  transcribed_at: string | null
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

export type JobStatus = 'wartet' | 'laeuft' | 'fertig' | 'fehler' | 'abgebrochen'

export interface Job {
  id: string
  recording_id: string
  kind: string
  status: JobStatus
  progress: number
  stage: string
  error: string | null
  finished_at: string | null
}

export interface Segment {
  id: string
  idx: number
  start_ms: number
  end_ms: number
  text: string
  speaker_label: string | null
  edited: boolean
}

export interface Speaker {
  label: string
  name: string | null
  idx: number
  talk_ms: number
}

export interface Transcript {
  recording_id: string
  language: string | null
  model: string | null
  transcribed_at: string | null
  speakers: Speaker[]
  segments: Segment[]
}

export interface AppSettings {
  whisper_model: string
  language: string
  diarize: boolean
  vocabulary: string
}

export interface ModelInfo {
  name: string
  label: string
  size_mb: number
  hint: string
  downloaded: boolean
}

export interface ModelsOverview {
  whisper: ModelInfo[]
  diarization: { downloaded: boolean; size_mb: number }
  models_dir: string
}

export interface TranscribeOptions {
  language?: string
  diarize?: boolean
  num_speakers?: number | null
}

export type CoreEvent =
  | { type: 'hello'; jobs: Job[] }
  | { type: 'job'; job: Job }
  | { type: 'recording'; id: string; status: RecordingStatus }
  | { type: 'ping' }

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
    for (let i = 0; i < 240; i++) {
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

  transcribe: (id: string, options: TranscribeOptions) =>
    request<Job>(`/api/recordings/${id}/transcribe`, json('POST', options)),
  jobs: () => request<Job[]>('/api/jobs'),
  lastJob: (recId: string) => request<Job | null>(`/api/recordings/${recId}/job`),
  cancelJob: (id: string) => request<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' }),
  transcript: (id: string) => request<Transcript>(`/api/recordings/${id}/transcript`),
  updateSegment: (id: string, patch: Partial<Pick<Segment, 'text' | 'speaker_label'>>) =>
    request<Segment>(`/api/segments/${id}`, json('PATCH', patch)),
  renameSpeaker: (recId: string, label: string, name: string) =>
    request<Speaker>(`/api/recordings/${recId}/speakers/${encodeURIComponent(label)}`, json('PATCH', { name })),
  exportToFile: (id: string, format: string, path: string) =>
    request<{ path: string }>(`/api/recordings/${id}/export`, json('POST', { format, path })),
  async exportUrl(id: string, format: string) {
    const { base, token } = await connect()
    return `${base}/api/recordings/${id}/export?format=${format}&token=${encodeURIComponent(token)}`
  },
  settings: () => request<AppSettings>('/api/settings'),
  updateSettings: (patch: Partial<AppSettings>) => request<AppSettings>('/api/settings', json('PATCH', patch)),
  models: () => request<ModelsOverview>('/api/models'),

  folders: () => request<Folder[]>('/api/folders'),
  createFolder: (name: string) => request<Folder>('/api/folders', json('POST', { name })),
  renameFolder: (id: string, name: string) => request<Folder>(`/api/folders/${id}`, json('PATCH', { name })),
  deleteFolder: (id: string) => request<void>(`/api/folders/${id}`, { method: 'DELETE' }),
}

/** Ereignisse des Cores (Auftragsfortschritt). Verbindet sich bei Abbruch neu. */
export function subscribeEvents(onEvent: (e: CoreEvent) => void): () => void {
  let ws: WebSocket | null = null
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | undefined

  const open = async () => {
    try {
      const { base, token } = await connect()
      if (stopped) return
      ws = new WebSocket(`${base.replace('http', 'ws')}/ws?token=${encodeURIComponent(token)}`)
      ws.onmessage = (m) => {
        try {
          onEvent(JSON.parse(m.data) as CoreEvent)
        } catch {
          /* ungültige Nachricht ignorieren */
        }
      }
      ws.onclose = () => {
        if (!stopped) timer = setTimeout(open, 2000)
      }
    } catch {
      if (!stopped) timer = setTimeout(open, 2000)
    }
  }
  void open()
  return () => {
    stopped = true
    clearTimeout(timer)
    ws?.close()
  }
}
