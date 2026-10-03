import { useState } from 'react'
import { setPin } from '../lib/storage'
import { reconnectNow } from '../live'
import { useStore } from '../store'

export function PinGate() {
  const [pin, setValue] = useState('')
  const [remember, setRemember] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const boot = useStore((s) => s.boot)

  return (
    <main className="gate">
      <div className="gate-card">
        <img className="gate-mark" src="/poses/idle.png" alt="" aria-hidden="true" />
        <h1 className="display">Talos</h1>
        <form
          className="stack"
          onSubmit={async (e) => {
            e.preventDefault()
            setBusy(true)
            setError('')
            setPin(pin, remember)
            await boot()
            setBusy(false)
            if (useStore.getState().auth === 'pin') setError('PIN incorreto. Tente de novo.')
            else reconnectNow()
          }}
        >
          <label className="field">
            <span>PIN do app</span>
            <input
              type="password"
              inputMode="numeric"
              autoComplete="current-password"
              value={pin}
              onChange={(e) => setValue(e.target.value)}
              autoFocus
              aria-invalid={error ? 'true' : undefined}
              aria-describedby={error ? 'pin-erro' : undefined}
            />
          </label>
          {error && (
            <p id="pin-erro" className="error-text" role="alert">
              {error}
            </p>
          )}
          <label className="check">
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
            <span>Lembrar neste aparelho</span>
          </label>
          <button type="submit" className="btn btn-primary btn-block" disabled={!pin || busy}>
            {busy ? 'Entrando…' : 'Entrar'}
          </button>
        </form>
      </div>
    </main>
  )
}

export function Forbidden() {
  return (
    <main className="gate">
      <div className="gate-card">
        <h1 className="display">Sem acesso</h1>
        <p>Esta identidade do Tailscale não está autorizada a usar o Talos.</p>
        <p className="muted small">Peça ao administrador para incluí-la em ALLOWED_TAILSCALE_LOGINS.</p>
      </div>
    </main>
  )
}
