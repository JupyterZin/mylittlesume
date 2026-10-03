// Tela: o navegador do Talos ao vivo (noVNC na mesma origem, via tailscale serve /tela).
import { useEffect, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import { Icon } from '../components/Icon'
import { fmtRelative } from '../lib/format'

const VNC_URL = '/tela/vnc.html?path=tela/websockify&autoconnect=1&resize=scale&reconnect=1'

type Availability = 'checking' | 'ok' | 'missing'

export function Tela() {
  const takeover = useStore((s) => s.app?.takeover)
  const refreshState = useStore((s) => s.refreshState)
  const toast = useStore((s) => s.toast)
  const [busy, setBusy] = useState(false)
  const [avail, setAvail] = useState<Availability>('checking')
  const active = takeover?.active ?? false

  useEffect(() => {
    let alive = true
    fetch('/tela/vnc.html', { method: 'HEAD', credentials: 'same-origin' })
      .then((r) => alive && setAvail(r.ok ? 'ok' : 'missing'))
      .catch(() => alive && setAvail('missing'))
    return () => {
      alive = false
    }
  }, [])

  const toggle = async () => {
    setBusy(true)
    try {
      const res = await api.takeover(!active)
      toast(
        res.takeover.active
          ? 'Você está no controle. O Talos espera até você devolver.'
          : 'Devolvido. O Talos continua de onde parou.',
      )
      await refreshState()
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Não foi possível mudar o controle.', 'bad')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="tela" data-control={active ? 'lucas' : 'talos'}>
      <header className="tela-bar">
        <div className="tela-who">
          <h1 className="title-sm">Tela</h1>
          <p className="muted small">
            {active
              ? `Você está no controle${takeover?.since ? ` · ${fmtRelative(takeover.since)}` : ''}`
              : 'O Talos está no controle'}
          </p>
        </div>
        <button
          type="button"
          className={active ? 'btn btn-primary' : 'btn btn-secondary'}
          onClick={() => void toggle()}
          disabled={busy}
        >
          <Icon name={active ? 'play' : 'maos'} size={18} />
          {busy ? 'Um momento…' : active ? 'Devolver ao Talos' : 'Assumir controle'}
        </button>
      </header>

      <div className="tela-frame">
        {avail === 'ok' && <iframe title="Navegador do Talos" src={VNC_URL} allow="clipboard-read; clipboard-write" />}
        {avail === 'ok' && !active && (
          <div className="tela-shield">
            <span>Só olhando. Para mexer, toque em Assumir controle.</span>
          </div>
        )}
        {avail === 'missing' && (
          <div className="tela-missing">
            <Icon name="tela" size={32} />
            <p>A Tela não está disponível agora.</p>
            <p className="muted small">
              No servidor ela aparece pelo Tailscale em /tela (serviços talos-browser e talos-novnc). Assumir e devolver o
              controle funciona mesmo assim.
            </p>
          </div>
        )}
        {avail === 'checking' && <p className="muted tela-missing">Conectando à Tela…</p>}
      </div>
    </div>
  )
}
