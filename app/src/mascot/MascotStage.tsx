// Palco do mascote (topo da Conversa): escolhe 3D ou 2D, toca as reações e mostra a linha de estado.
import { Component, lazy, Suspense, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useStore, pendingApprovals } from '../store'
import { usePrefs } from '../prefs'
import { navigate } from '../router'
import { animationFor, displayState, poseName, reactionMillis } from './states'
import { chooseRender, detectDevice } from './capability'

const Mascot3D = lazy(() => import('./Mascot3D'))

class Fallback extends Component<{ fallback: ReactNode; onError: () => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  componentDidCatch() {
    this.props.onError()
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children
  }
}

function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false)
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    if (!mq) return
    const fn = () => setReduced(mq.matches)
    mq.addEventListener('change', fn)
    return () => mq.removeEventListener('change', fn)
  }, [])
  return reduced
}

export function Mascot2D({ pose, hidden }: { pose: string; hidden?: boolean }) {
  return (
    <img
      className="mascot-2d"
      src={`/poses/${pose}.png`}
      alt=""
      aria-hidden="true"
      draggable={false}
      data-hidden={hidden ? 'true' : undefined}
    />
  )
}

export function MascotStage({ active, compact }: { active: boolean; compact: boolean }) {
  const mascot = useStore((s) => s.mascot)
  const reaction = useStore((s) => s.reaction)
  const typing = useStore((s) => s.typing)
  const clearReaction = useStore((s) => s.clearReaction)
  const pending = useStore((s) => pendingApprovals(s.approvals).length)
  const paused = useStore((s) => s.app?.paused ?? false)
  const prefs = usePrefs()
  const reducedMotion = useReducedMotion()
  const [failed3d, setFailed3d] = useState(false)
  const [ready3d, setReady3d] = useState(false)

  const base = paused ? 'paused' : mascot.state
  const state = displayState(base, reaction?.state ?? null, typing)
  const gesture = reaction?.gesture ?? null
  const spec = useMemo(() => animationFor(state, gesture), [state, gesture])
  const status = reaction ? reaction.status : mascot.status

  const choice = useMemo(
    () => chooseRender(prefs.mascot, prefs.autoFellBack || failed3d, { ...detectDevice(), reducedMotion }),
    [prefs.mascot, prefs.autoFellBack, failed3d, reducedMotion],
  )

  // a reação dura o clipe (3D avisa no fim); por segurança há sempre um temporizador
  useEffect(() => {
    if (!reaction) return
    const nonce = reaction.nonce
    const ms = reactionMillis(spec) + (choice.mode === '3d' ? 1200 : 0)
    const t = setTimeout(() => clearReaction(nonce), ms)
    return () => clearTimeout(t)
  }, [reaction, spec, choice.mode, clearReaction])

  const onDone = useCallback(() => {
    if (reaction) setTimeout(() => clearReaction(reaction.nonce), 250)
  }, [reaction, clearReaction])

  const pose = poseName(state, gesture)
  const show3d = choice.mode === '3d'

  return (
    <section className="stage" data-compact={compact ? 'true' : undefined} aria-label="Talos">
      <div className="stage-figure">
        {(!show3d || !ready3d) && <Mascot2D pose={pose} />}
        {show3d && (
          <Fallback fallback={null} onError={() => setFailed3d(true)}>
            <Suspense fallback={null}>
              <div className="stage-canvas" data-ready={ready3d ? 'true' : undefined}>
                <Mascot3D
                  spec={spec}
                  playKey={reaction?.nonce ?? state}
                  active={active}
                  onReady={() => setReady3d(true)}
                  onDone={onDone}
                  onSlow={() => prefs.mascot === 'auto' && prefs.markSlow()}
                />
              </div>
            </Suspense>
          </Fallback>
        )}
        {spec.seal && pending > 0 && (
          <button
            type="button"
            className="seal"
            data-still={choice.still ? 'true' : undefined}
            onClick={() => navigate('/aprovacoes')}
            aria-label={pending === 1 ? '1 aprovação aguardando você' : `${pending} aprovações aguardando você`}
          >
            {pending}
          </button>
        )}
      </div>
      <p className="stage-status" aria-live="polite">
        {status}
      </p>
    </section>
  )
}
