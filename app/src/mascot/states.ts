// Estado do agente → animação do RobotExpressive (SPEC §9.3). Puro: testado em states.test.ts.
import type { MascotState } from '../types'

export const CLIPS = [
  'Dance',
  'Death',
  'Idle',
  'Jump',
  'No',
  'Punch',
  'Running',
  'Sitting',
  'Standing',
  'ThumbsUp',
  'Walking',
  'WalkJump',
  'Wave',
  'Yes',
] as const
export type Clip = (typeof CLIPS)[number]

/** Não combinam com um assistente: nunca são tocadas. */
export const UNUSED_CLIPS: readonly Clip[] = ['Death', 'Punch']

export type Morph = 'Angry' | 'Surprised' | 'Sad'

/**
 * loop: repete (Idle, Walking, Running…);
 * hold: toca uma vez e fica no último quadro — `Sitting` (sentar) e `Standing` (levantar) são
 *       transições no GLB, como no exemplo do three.js; o estado contínuo é a pose final;
 * once: reação; toca uma vez e o palco volta ao estado de base.
 */
export type PlayMode = 'loop' | 'hold' | 'once'

export interface AnimSpec {
  clip: Clip
  mode: PlayMode
  expression?: { name: Morph; weight: number }
  /** inclinação procedural da cabeça (pensando) */
  headTilt?: boolean
  /** selo pulsando no palco (aguardando aprovação) */
  seal?: boolean
}

export const CROSSFADE_SECONDS = 0.3

export const ANIMATIONS: Record<MascotState, AnimSpec> = {
  idle: { clip: 'Idle', mode: 'loop' },
  greeting: { clip: 'Wave', mode: 'once' },
  typing: { clip: 'Standing', mode: 'hold' },
  thinking: { clip: 'Idle', mode: 'loop', headTilt: true },
  working: { clip: 'Walking', mode: 'loop' },
  long_task: { clip: 'Running', mode: 'loop' },
  waiting_approval: { clip: 'Standing', mode: 'hold', expression: { name: 'Surprised', weight: 0.4 }, seal: true },
  approved: { clip: 'ThumbsUp', mode: 'once' },
  rejected: { clip: 'No', mode: 'once' },
  reply: { clip: 'Jump', mode: 'once', expression: { name: 'Surprised', weight: 1 } },
  milestone: { clip: 'Dance', mode: 'once' },
  error: { clip: 'No', mode: 'once', expression: { name: 'Sad', weight: 1 } },
  blocked: { clip: 'No', mode: 'once', expression: { name: 'Angry', weight: 0.6 } },
  quiet_hours: { clip: 'Sitting', mode: 'hold' },
  paused: { clip: 'Sitting', mode: 'hold', expression: { name: 'Sad', weight: 0.3 } },
}

/** Gestos que o servidor pode pedir por cima de uma reação (ex.: "Yes" ao aprovar). */
const GESTURES: readonly Clip[] = ['Yes', 'No', 'ThumbsUp', 'Wave', 'Jump']

export function animationFor(state: MascotState, gesture?: string | null): AnimSpec {
  const spec = ANIMATIONS[state] ?? ANIMATIONS.idle
  if (gesture && (GESTURES as readonly string[]).includes(gesture) && spec.mode === 'once') {
    return { ...spec, clip: gesture as Clip }
  }
  return spec
}

/** Durações reais das animações do talos.glb (segundos), para o modo 2D/estático. */
export const CLIP_SECONDS: Record<Clip, number> = {
  Dance: 3.33,
  Death: 0.96,
  Idle: 3.33,
  Jump: 0.71,
  No: 1.67,
  Punch: 0.83,
  Running: 0.96,
  Sitting: 0.42,
  Standing: 0.42,
  ThumbsUp: 1.58,
  Walking: 0.96,
  WalkJump: 0.83,
  Wave: 1.83,
  Yes: 1.67,
}

/** Quanto tempo uma reação fica à vista antes de voltar ao estado de base. */
export function reactionMillis(spec: AnimSpec): number {
  return Math.max(1800, Math.round(CLIP_SECONDS[spec.clip] * 1000) + 400)
}

/** Nome do PNG da pose (fallback 2D / movimento reduzido). */
export function poseName(state: MascotState, gesture?: string | null): string {
  if (gesture === 'Yes' && state === 'approved') return 'yes'
  return state.replace('_', '-')
}

/** O que o palco mostra: reação em curso > "digitando" local > estado de base do servidor. */
export function displayState(
  base: MascotState,
  reaction: MascotState | null,
  typing: boolean,
): MascotState {
  if (reaction) return reaction
  if (typing && (base === 'idle' || base === 'quiet_hours' || base === 'waiting_approval')) return 'typing'
  return base
}
