import { describe, expect, it } from 'vitest'
import { ANIMATIONS, CLIPS, UNUSED_CLIPS, animationFor, displayState, poseName, reactionMillis } from './states'
import { chooseRender } from './capability'
import type { MascotState } from '../types'

const ALL: MascotState[] = [
  'idle',
  'greeting',
  'typing',
  'thinking',
  'working',
  'long_task',
  'waiting_approval',
  'approved',
  'rejected',
  'reply',
  'milestone',
  'error',
  'blocked',
  'quiet_hours',
  'paused',
]

describe('tabela estado → animação (SPEC §9.3)', () => {
  it('cobre os 15 estados e só usa clipes do GLB', () => {
    expect(Object.keys(ANIMATIONS).sort()).toEqual([...ALL].sort())
    for (const s of ALL) expect(CLIPS).toContain(ANIMATIONS[s].clip)
  })

  it('segue a tabela do SPEC', () => {
    expect(ANIMATIONS.idle).toEqual({ clip: 'Idle', mode: 'loop' })
    // Sitting/Standing são transições no GLB: ficam paradas no último quadro
    for (const s of ALL) {
      const a = ANIMATIONS[s]
      if (a.clip === 'Sitting' || a.clip === 'Standing') expect(a.mode).toBe('hold')
    }
    expect(ANIMATIONS.greeting).toMatchObject({ clip: 'Wave', mode: 'once' })
    expect(ANIMATIONS.typing).toMatchObject({ clip: 'Standing', mode: 'hold' })
    expect(ANIMATIONS.thinking).toMatchObject({ clip: 'Idle', mode: 'loop', headTilt: true })
    expect(ANIMATIONS.working).toMatchObject({ clip: 'Walking', mode: 'loop' })
    expect(ANIMATIONS.long_task).toMatchObject({ clip: 'Running', mode: 'loop' })
    expect(ANIMATIONS.waiting_approval).toMatchObject({
      clip: 'Standing',
      mode: 'hold',
      seal: true,
      expression: { name: 'Surprised', weight: 0.4 },
    })
    expect(ANIMATIONS.approved).toMatchObject({ clip: 'ThumbsUp', mode: 'once' })
    expect(ANIMATIONS.rejected).toMatchObject({ clip: 'No', mode: 'once' })
    expect(ANIMATIONS.reply).toMatchObject({ clip: 'Jump', mode: 'once', expression: { name: 'Surprised' } })
    expect(ANIMATIONS.milestone).toMatchObject({ clip: 'Dance', mode: 'once' })
    expect(ANIMATIONS.error).toMatchObject({ clip: 'No', expression: { name: 'Sad' } })
    expect(ANIMATIONS.blocked).toMatchObject({ clip: 'No', expression: { name: 'Angry', weight: 0.6 } })
    expect(ANIMATIONS.quiet_hours).toMatchObject({ clip: 'Sitting', mode: 'hold' })
    expect(ANIMATIONS.paused).toMatchObject({ clip: 'Sitting', mode: 'hold', expression: { name: 'Sad', weight: 0.3 } })
  })

  it('nunca usa Death nem Punch', () => {
    expect(UNUSED_CLIPS).toEqual(['Death', 'Punch'])
    for (const s of ALL) expect(UNUSED_CLIPS).not.toContain(ANIMATIONS[s].clip)
    expect(animationFor('approved', 'Punch').clip).toBe('ThumbsUp')
  })

  it('aprovar acena "Yes"; o gesto não muda estados contínuos', () => {
    expect(animationFor('approved', 'Yes').clip).toBe('Yes')
    expect(animationFor('approved').clip).toBe('ThumbsUp')
    expect(animationFor('working', 'Yes').clip).toBe('Walking')
  })

  it('reações ficam à vista pelo menos o tempo do clipe', () => {
    expect(reactionMillis(ANIMATIONS.milestone)).toBeGreaterThan(3330)
    expect(reactionMillis(ANIMATIONS.reply)).toBeGreaterThanOrEqual(1800)
  })

  it('nomes das poses 2D', () => {
    expect(poseName('waiting_approval')).toBe('waiting-approval')
    expect(poseName('approved', 'Yes')).toBe('yes')
    expect(poseName('quiet_hours')).toBe('quiet-hours')
  })
})

describe('o que o palco mostra', () => {
  it('reação > digitando > base', () => {
    expect(displayState('idle', null, false)).toBe('idle')
    expect(displayState('idle', null, true)).toBe('typing')
    expect(displayState('waiting_approval', null, true)).toBe('typing')
    expect(displayState('working', null, true)).toBe('working') // o Talos a trabalhar vence
    expect(displayState('paused', null, true)).toBe('paused')
    expect(displayState('working', 'reply', true)).toBe('reply')
  })
})

describe('escolha 3D/2D', () => {
  const strong = { webgl: true, reducedMotion: false, cores: 8, memoryGb: 8 }
  it('automático em aparelho bom → 3D', () => {
    expect(chooseRender('auto', false, strong)).toMatchObject({ mode: '3d', still: false })
  })
  it('movimento reduzido → poses estáticas, sempre', () => {
    expect(chooseRender('3d', false, { ...strong, reducedMotion: true })).toMatchObject({ mode: '2d', still: true })
  })
  it('aparelho fraco, sem WebGL ou lento → 2D', () => {
    expect(chooseRender('auto', false, { ...strong, cores: 2 }).mode).toBe('2d')
    expect(chooseRender('auto', false, { ...strong, memoryGb: 1 }).mode).toBe('2d')
    expect(chooseRender('3d', false, { ...strong, webgl: false }).mode).toBe('2d')
    expect(chooseRender('auto', true, strong).mode).toBe('2d')
    expect(chooseRender('3d', true, strong).mode).toBe('3d') // o Lucas pediu 3D
  })
})
