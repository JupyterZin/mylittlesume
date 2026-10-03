// Página só para scripts (scripts/render-poses.mjs): desenha uma pose congelada do mascote
// para gerar as imagens 2D e os ícones: /?render-pose=<estado>&t=<s>&framing=stage|icon&bg=<hex>&zoom=<x>.
import { lazy, Suspense, useLayoutEffect, useMemo } from 'react'
import { animationFor } from '../mascot/states'
import type { MascotState } from '../types'

const Mascot3D = lazy(() => import('../mascot/Mascot3D'))

declare global {
  interface Window {
    __poseReady?: boolean
  }
}

export default function PoseRender() {
  const params = new URLSearchParams(location.search)
  const state = (params.get('render-pose') ?? 'idle') as MascotState
  const gesture = params.get('gesture')
  const time = Number(params.get('t') ?? '0.5')
  const framing = params.get('framing') === 'icon' ? 'icon' : 'stage'
  const bg = params.get('bg')
  const zoom = Number(params.get('zoom') ?? '1') // >1 afasta a câmera (ícone "maskable": zona segura)
  const spec = useMemo(() => animationFor(state, gesture), [state, gesture])
  const pose = useMemo(() => ({ time, onRendered: () => (window.__poseReady = true) }), [time])
  useLayoutEffect(() => {
    // fundo transparente de verdade (as poses 2D vão por cima do palco, claro ou escuro)
    document.documentElement.style.background = 'transparent'
    document.body.style.background = 'transparent'
  }, [])
  return (
    <div style={{ position: 'fixed', inset: 0, background: bg ? `#${bg}` : 'transparent' }}>
      <Suspense fallback={null}>
        <Mascot3D spec={spec} playKey="pose" active framing={framing} distance={zoom} pose={pose} />
      </Suspense>
    </div>
  )
}
