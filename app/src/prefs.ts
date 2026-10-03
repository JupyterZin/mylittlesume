// Preferências locais do aparelho (tema, modo do mascote, voz). Nada disto vai para o servidor.
import { create } from 'zustand'
import { load, save } from './lib/storage'

export type ThemePref = 'auto' | 'light' | 'dark'
export type MascotPref = 'auto' | '3d' | '2d'

interface Prefs {
  theme: ThemePref
  mascot: MascotPref
  /** o modo automático caiu para 2D por desempenho (lembrado até o Lucas pedir 3D de novo) */
  autoFellBack: boolean
  speak: boolean
  setTheme: (t: ThemePref) => void
  setMascot: (m: MascotPref) => void
  markSlow: () => void
  setSpeak: (on: boolean) => void
}

function initialTheme(): ThemePref {
  const t = load('talos.theme')
  return t === 'light' || t === 'dark' ? t : 'auto'
}

function initialMascot(): MascotPref {
  const m = load('talos.mascot')
  return m === '3d' || m === '2d' ? m : 'auto'
}

export function applyTheme(t: ThemePref): void {
  const root = document.documentElement
  if (t === 'auto') delete root.dataset.theme
  else root.dataset.theme = t
}

export const usePrefs = create<Prefs>((set) => ({
  theme: initialTheme(),
  mascot: initialMascot(),
  autoFellBack: load('talos.mascot.slow') === '1',
  speak: load('talos.speak') === '1',
  setTheme: (theme) => {
    save('talos.theme', theme === 'auto' ? null : theme)
    applyTheme(theme)
    set({ theme })
  },
  setMascot: (mascot) => {
    save('talos.mascot', mascot === 'auto' ? null : mascot)
    if (mascot === '3d') save('talos.mascot.slow', null)
    set({ mascot, autoFellBack: mascot === '3d' ? false : load('talos.mascot.slow') === '1' })
  },
  markSlow: () => {
    save('talos.mascot.slow', '1')
    set({ autoFellBack: true })
  },
  setSpeak: (speak) => {
    save('talos.speak', speak ? '1' : null)
    set({ speak })
  },
}))
