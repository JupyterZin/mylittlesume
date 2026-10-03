import { useEffect, useState } from 'react'
import { useRoute } from './router'
import { useStore, onAssistantMessage } from './store'
import { usePrefs } from './prefs'
import { startLive } from './live'
import { setTimeZone } from './lib/format'
import { speak } from './lib/speech'
import { BottomNav } from './components/BottomNav'
import { Toasts } from './components/Toasts'
import { Forbidden, PinGate } from './components/PinGate'
import { Conversa } from './pages/Conversa'
import { Tarefas } from './pages/Tarefas'
import { Aprovacoes } from './pages/Aprovacoes'
import { Agenda } from './pages/Agenda'
import { Tela } from './pages/Tela'
import { Ajustes } from './pages/Ajustes'

function useVisible(): boolean {
  const [visible, setVisible] = useState(() => document.visibilityState === 'visible')
  useEffect(() => {
    const fn = () => setVisible(document.visibilityState === 'visible')
    document.addEventListener('visibilitychange', fn)
    return () => document.removeEventListener('visibilitychange', fn)
  }, [])
  return visible
}

export default function App() {
  const route = useRoute()
  const auth = useStore((s) => s.auth)
  const tz = useStore((s) => s.app?.timezone)
  const boot = useStore((s) => s.boot)
  const visible = useVisible()

  useEffect(() => {
    void boot()
    const stop = startLive()
    onAssistantMessage((text) => {
      if (usePrefs.getState().speak && document.visibilityState === 'visible') speak(text)
    })
    return stop
  }, [boot])

  useEffect(() => {
    if (tz) setTimeZone(tz)
  }, [tz])

  useEffect(() => {
    const titles: Record<string, string> = {
      conversa: 'Talos',
      tarefas: 'Tarefas · Talos',
      aprovacoes: 'Aprovações · Talos',
      agenda: 'Agenda · Talos',
      tela: 'Tela · Talos',
      ajustes: 'Ajustes · Talos',
    }
    document.title = titles[route.page]
  }, [route.page])

  if (auth === 'pin') return <PinGate />
  if (auth === 'forbidden') return <Forbidden />

  const onConversa = route.page === 'conversa'

  return (
    <div className="app" data-page={route.page}>
      {auth === 'offline' && (
        <div className="offline" role="status">
          Sem conexão com o Talos. Tentando de novo…
          <button type="button" className="link" onClick={() => void boot()}>
            Tentar agora
          </button>
        </div>
      )}
      <main className="main">
        {/* a Conversa fica montada (palco 3D e posição da leitura); as outras páginas entram e saem */}
        <div className="page-slot" hidden={!onConversa}>
          <Conversa active={onConversa && visible} />
        </div>
        {route.page === 'tarefas' && <Tarefas id={route.id} />}
        {route.page === 'aprovacoes' && <Aprovacoes id={route.id} />}
        {route.page === 'agenda' && <Agenda />}
        {route.page === 'tela' && <Tela />}
        {route.page === 'ajustes' && <Ajustes />}
      </main>
      <Toasts />
      <BottomNav current={route.page} />
    </div>
  )
}
