const time = new Intl.DateTimeFormat('de-DE', { hour: '2-digit', minute: '2-digit' })
const weekday = new Intl.DateTimeFormat('de-DE', { weekday: 'short' })
const date = new Intl.DateTimeFormat('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' })
const longDate = new Intl.DateTimeFormat('de-DE', {
  weekday: 'short',
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
})

export function formatDuration(seconds: number | null): string {
  if (seconds == null) return '–:–'
  const s = Math.round(seconds)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(sec).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

export function formatSize(bytes: number | null): string {
  if (bytes == null) return ''
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / 1024 / 1024).toFixed(1).replace('.', ',')} MB`
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

/** Gruppe in der Liste: Heute, Gestern, Diese Woche, Älter. */
export function dayGroup(iso: string, now = new Date()): string {
  const diff = Math.round((startOfDay(now) - startOfDay(new Date(iso))) / 86_400_000)
  if (diff <= 0) return 'Heute'
  if (diff === 1) return 'Gestern'
  if (diff < 7) return 'Diese Woche'
  return 'Älter'
}

/** Kurze Zeitangabe rechts in der Liste. */
export function listTime(iso: string, now = new Date()): string {
  const d = new Date(iso)
  const group = dayGroup(iso, now)
  if (group === 'Heute' || group === 'Gestern') return time.format(d)
  if (group === 'Diese Woche') return weekday.format(d)
  return date.format(d)
}

export function detailDate(iso: string): string {
  const d = new Date(iso)
  return `${longDate.format(d)} · ${time.format(d)} Uhr`
}

export function shortDate(iso: string): string {
  return date.format(new Date(iso))
}

export const STATUS_LABEL: Record<string, string> = {
  nur_audio: 'Nur Audio',
  wird_transkribiert: 'Wird transkribiert',
  transkribiert: 'Transkribiert',
  fehler: 'Fehler',
}
