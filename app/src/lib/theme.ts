import { useEffect, useState } from 'react'

export type ThemeChoice = 'hell' | 'dunkel' | 'system'

const KEY = 'notizer.theme'

function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'hell' || v === 'dunkel' || v === 'system') return v
  } catch {
    /* Speicher nicht verfügbar */
  }
  return 'system'
}

function systemDark(): boolean {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false
}

/** Farbschema der App: Hell, Dunkel oder wie das Betriebssystem. */
export function useTheme() {
  const [choice, setChoice] = useState<ThemeChoice>(readChoice)
  const [sysDark, setSysDark] = useState(systemDark)

  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mq) return
    const onChange = () => setSysDark(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  const dark = choice === 'dunkel' || (choice === 'system' && sysDark)

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  }, [dark])

  const update = (next: ThemeChoice) => {
    setChoice(next)
    try {
      localStorage.setItem(KEY, next)
    } catch {
      /* Speicher nicht verfügbar */
    }
  }

  return { choice, dark, setChoice: update, toggle: () => update(dark ? 'hell' : 'dunkel') }
}
