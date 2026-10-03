// Decide como desenhar o mascote: 3D (R3F) ou poses 2D (PNG); estático com movimento reduzido.
import type { MascotPref } from '../prefs'

export interface DeviceInfo {
  webgl: boolean
  reducedMotion: boolean
  cores?: number
  memoryGb?: number
  saveData?: boolean
}

export interface RenderChoice {
  mode: '3d' | '2d'
  /** sem animação: poses estáticas (prefers-reduced-motion) */
  still: boolean
  reason: string
}

export function chooseRender(pref: MascotPref, fellBack: boolean, d: DeviceInfo): RenderChoice {
  if (d.reducedMotion) return { mode: '2d', still: true, reason: 'movimento reduzido' }
  if (pref === '2d') return { mode: '2d', still: false, reason: 'escolhido nas Ajustes' }
  if (!d.webgl) return { mode: '2d', still: false, reason: 'sem WebGL' }
  if (pref === '3d') return { mode: '3d', still: false, reason: 'escolhido nas Ajustes' }
  if (fellBack) return { mode: '2d', still: false, reason: 'aparelho lento' }
  if (d.saveData) return { mode: '2d', still: false, reason: 'economia de dados' }
  if ((d.cores !== undefined && d.cores <= 2) || (d.memoryGb !== undefined && d.memoryGb <= 2)) {
    return { mode: '2d', still: false, reason: 'aparelho modesto' }
  }
  return { mode: '3d', still: false, reason: 'automático' }
}

let webglCache: boolean | null = null

export function hasWebGL(): boolean {
  if (webglCache !== null) return webglCache
  try {
    const c = document.createElement('canvas')
    webglCache = !!(c.getContext('webgl2') || c.getContext('webgl'))
  } catch {
    webglCache = false
  }
  return webglCache
}

export function detectDevice(): DeviceInfo {
  const nav = navigator as Navigator & { deviceMemory?: number; connection?: { saveData?: boolean } }
  return {
    webgl: hasWebGL(),
    reducedMotion: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
    cores: nav.hardwareConcurrency || undefined,
    memoryGb: nav.deviceMemory,
    saveData: nav.connection?.saveData,
  }
}

/** Média de fps abaixo disto em primeiro plano → cai para 2D (e lembra). */
export const SLOW_FPS = 20
