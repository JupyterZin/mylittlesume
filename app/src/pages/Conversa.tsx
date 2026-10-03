// Conversa: palco do mascote no topo, mensagens com cartões de aprovação inline, composer com ditado.
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useStore } from '../store'
import { MascotStage } from '../mascot/MascotStage'
import { ApprovalCard } from '../components/ApprovalCard'
import { Icon } from '../components/Icon'
import { Sheet } from '../components/Sheet'
import { navigate } from '../router'
import { dayKey, fmtDay, fmtTime, parseDate } from '../lib/format'
import { useDictation } from '../lib/speech'
import type { Approval, ChatMessage } from '../types'

type Item = { kind: 'msg'; at: number; m: ChatMessage } | { kind: 'approval'; at: number; a: Approval }

const URL_RE = /(https?:\/\/[^\s<>()]+[^\s<>().,;:!?'"»])/g

function linkify(text: string): ReactNode[] {
  return text.split(URL_RE).map((part, i) =>
    i % 2 === 1 ? (
      <a key={i} href={part} target="_blank" rel="noreferrer noopener">
        {part.replace(/^https?:\/\//, '')}
      </a>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  )
}

function ConnDot() {
  const conn = useStore((s) => s.conn)
  const label = conn === 'open' ? 'Conectado' : conn === 'connecting' ? 'Conectando…' : 'Sem conexão'
  return (
    <span className="conn" data-conn={conn} title={label}>
      <span className="conn-dot" aria-hidden="true" />
      <span className="sr-only">{label}</span>
      {conn !== 'open' && <span className="conn-label">{label}</span>}
    </span>
  )
}

function Composer({ onFocusChange }: { onFocusChange: (focused: boolean) => void }) {
  const [text, setText] = useState('')
  const send = useStore((s) => s.send)
  const setTyping = useStore((s) => s.setTyping)
  const ref = useRef<HTMLTextAreaElement>(null)
  const typingTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const base = useRef('')
  const blurTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  // enviar e ditar não tiram o foco do campo: o teclado continua aberto, como num mensageiro
  const keepFocus = (e: { preventDefault: () => void }) => e.preventDefault()
  const dict = useDictation((heard) => {
    setText(base.current ? `${base.current} ${heard}` : heard)
  })

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 148)}px`
  }, [text])

  const submit = () => {
    const t = text.trim()
    if (!t) return
    if (dict.listening) dict.stop()
    setText('')
    clearTimeout(typingTimer.current)
    void send(t)
    ref.current?.focus()
  }

  const fine = typeof window !== 'undefined' && window.matchMedia?.('(pointer: fine)').matches

  return (
    <form
      className="composer"
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      <label htmlFor="mensagem" className="sr-only">
        Mensagem para o Talos
      </label>
      <textarea
        id="mensagem"
        ref={ref}
        rows={1}
        value={text}
        placeholder={dict.listening ? 'Ouvindo…' : 'Escreva para o Talos…'}
        enterKeyHint="send"
        onChange={(e) => {
          setText(e.target.value)
          setTyping(true)
          clearTimeout(typingTimer.current)
          typingTimer.current = setTimeout(() => setTyping(false), 2500)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && fine && !e.nativeEvent.isComposing) {
            e.preventDefault()
            submit()
          }
        }}
        onFocus={() => {
          clearTimeout(blurTimer.current)
          onFocusChange(true)
        }}
        onBlur={() => {
          // adiado: o palco cresce e a barra volta; um toque em curso não pode "cair" noutro sítio
          blurTimer.current = setTimeout(() => onFocusChange(false), 160)
          setTyping(false)
        }}
      />
      {dict.supported && (
        <button
          type="button"
          className="icon-btn mic"
          onMouseDown={keepFocus}
          aria-pressed={dict.listening}
          aria-label={dict.listening ? 'Parar o ditado' : 'Ditar mensagem'}
          onClick={() => {
            if (dict.listening) dict.stop()
            else {
              base.current = text.trim()
              dict.start()
            }
          }}
        >
          <Icon name="mic" />
        </button>
      )}
      <button type="submit" className="send" aria-label="Enviar" disabled={!text.trim()} onMouseDown={keepFocus}>
        <Icon name="enviar" />
      </button>
      {dict.error && (
        <p className="composer-error" role="alert">
          {dict.error}
        </p>
      )}
    </form>
  )
}

function MessageRow({ m, last }: { m: ChatMessage; last: boolean }) {
  const retry = useStore((s) => s.retry)
  return (
    <div className="msg" data-role={m.role} data-last={last ? 'true' : undefined}>
      {m.task_id && m.role === 'assistant' ? (
        <a
          className="msg-task"
          href={`/tarefas/${m.task_id}`}
          onClick={(e) => {
            e.preventDefault()
            navigate(`/tarefas/${m.task_id}`)
          }}
        >
          Tarefa #{m.task_id}
        </a>
      ) : null}
      <div className="bubble">{linkify(m.content)}</div>
      {last && (
        <div className="msg-meta">
          {m.failed ? (
            <button type="button" className="link danger" onClick={() => void retry(m.key)}>
              Não enviada · tentar de novo
            </button>
          ) : (
            <>
              {fmtTime(m.created_at)}
              {m.channel === 'telegram' && ' · Telegram'}
              {m.pending && ' · enviando…'}
            </>
          )}
        </div>
      )}
    </div>
  )
}

export function Conversa({ active }: { active: boolean }) {
  const messages = useStore((s) => s.messages)
  const approvals = useStore((s) => s.approvals)
  const app = useStore((s) => s.app)
  const setPaused = useStore((s) => s.setPaused)
  const [focused, setFocused] = useState(false)
  const [confirmPause, setConfirmPause] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  const stick = useRef(true)

  const items = useMemo<Item[]>(() => {
    const out: Item[] = [
      ...messages.map((m) => ({ kind: 'msg' as const, at: parseDate(m.created_at)?.getTime() ?? 0, m })),
      ...approvals.map((a) => ({ kind: 'approval' as const, at: parseDate(a.created_at)?.getTime() ?? 0, a })),
    ]
    return out.sort((x, y) => x.at - y.at)
  }, [messages, approvals])

  useLayoutEffect(() => {
    const el = scroller.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [items, active, focused])

  useEffect(() => {
    const el = scroller.current
    if (!el) return
    const onScroll = () => {
      stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [])

  let lastDay = ''
  const paused = app?.paused ?? false

  return (
    <div className="conversa" data-focused={focused ? 'true' : undefined}>
      <header className="conversa-bar">
        <h1 className="brand">{app?.agent_name ?? 'Talos'}</h1>
        <ConnDot />
        <span className="spacer" />
        {paused ? (
          <button type="button" className="btn btn-small btn-primary" onClick={() => void setPaused(false)}>
            <Icon name="play" size={16} />
            Retomar
          </button>
        ) : (
          <button type="button" className="btn btn-small btn-ghost" onClick={() => setConfirmPause(true)}>
            <Icon name="pausa" size={16} />
            Pausar
          </button>
        )}
      </header>

      <MascotStage active={active} compact={focused} />

      <div className="thread" ref={scroller} role="log" aria-label="Mensagens">
        {items.length === 0 && (
          <p className="thread-empty">Mande uma mensagem como mandaria a uma pessoa. O Talos responde aqui e no Telegram.</p>
        )}
        {items.map((it, i) => {
          const day = dayKey(new Date(it.at))
          const sep = day !== lastDay
          lastDay = day
          const next = items[i + 1]
          let last = true
          if (it.kind === 'msg' && next?.kind === 'msg') {
            last = !(next.m.role === it.m.role && next.at - it.at < 3 * 60_000 && dayKey(new Date(next.at)) === day)
          }
          return (
            <Fragment key={it.kind === 'msg' ? it.m.key : `a${it.a.id}`}>
              {sep && (
                <div className="day-sep">
                  <span>{fmtDay(new Date(it.at).toISOString())}</span>
                </div>
              )}
              {it.kind === 'msg' ? <MessageRow m={it.m} last={last} /> : <ApprovalCard a={it.a} variant="inline" />}
            </Fragment>
          )
        })}
      </div>

      <Composer onFocusChange={setFocused} />

      <Sheet open={confirmPause} title="Pausar o Talos?" onClose={() => setConfirmPause(false)}>
        <div className="stack">
          <p>Para as execuções em andamento, congela as propostas pendentes e nada roda até você retomar.</p>
          <button
            type="button"
            className="btn btn-danger btn-block"
            onClick={() => {
              setConfirmPause(false)
              void setPaused(true)
            }}
          >
            Pausar agora
          </button>
        </div>
      </Sheet>
    </div>
  )
}
