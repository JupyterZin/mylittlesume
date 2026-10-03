// Agenda: acompanhamentos (follow-ups e vigilâncias), recorrências e check-ins de objetivos.
import { useEffect, useState } from 'react'
import { api } from '../api'
import { navigate } from '../router'
import { PageHeader } from '../components/PageHeader'
import { fmtWhen, humanizeRRule, SCHEDULE_LABEL } from '../lib/format'
import type { Agenda as AgendaData } from '../types'

function TaskLink({ id, title }: { id: number | null; title: string }) {
  if (!id) return <span>{title || 'Sem tarefa'}</span>
  return (
    <a
      href={`/tarefas/${id}`}
      onClick={(e) => {
        e.preventDefault()
        navigate(`/tarefas/${id}`)
      }}
    >
      {title || `Tarefa #${id}`}
    </a>
  )
}

export function Agenda() {
  const [data, setData] = useState<AgendaData | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .agenda()
      .then(setData)
      .catch((e: Error) => setError(e.message))
  }, [])

  const total = data ? data.watches.length + data.schedules.length + data.goals.length : 0

  return (
    <div className="page">
      <PageHeader title="Agenda" subtitle={data ? (total ? 'O que o Talos tem marcado' : 'Nada marcado') : ' '} />
      {error && <p className="error-text">{error}</p>}
      {!data && !error && <p className="muted">Carregando…</p>}
      {data && (
        <>
          <section className="group" aria-labelledby="ag-acomp">
            <h2 id="ag-acomp" className="group-title">
              Acompanhamentos <span className="count">{data.watches.length}</span>
            </h2>
            {data.watches.length === 0 ? (
              <p className="empty">Quando o Talos esperar uma resposta, ele marca aqui quando vai cobrar.</p>
            ) : (
              <ul className="list">
                {data.watches.map((w) => (
                  <li key={w.id} className="row">
                    <span className="row-main">
                      <span className="row-title">
                        <TaskLink id={w.task_id} title={w.task_title} />
                      </span>
                      <span className="row-sub">
                        {w.kind === 'webpage' ? `Vigiando ${w.target.replace(/^https?:\/\//, '')}` : 'Esperando resposta por email'}
                      </span>
                      <span className="row-sub">
                        {w.next_check_at ? `Próximo follow-up ${fmtWhen(w.next_check_at)}` : 'Sem prazo; sigo atento a respostas'}
                        {' · '}
                        {w.followups_sent} de {w.max_followups} follow-ups
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="group" aria-labelledby="ag-rec">
            <h2 id="ag-rec" className="group-title">
              Recorrências <span className="count">{data.schedules.length}</span>
            </h2>
            {data.schedules.length === 0 ? (
              <p className="empty">Briefing da manhã, reflexão da noite e outras rotinas aparecem aqui.</p>
            ) : (
              <ul className="list">
                {data.schedules.map((s) => (
                  <li key={s.id} className="row">
                    <span className="row-main">
                      <span className="row-title">
                        {SCHEDULE_LABEL[s.kind] ?? (s.task_title || s.prompt.split('\n')[0] || 'Rotina')}
                      </span>
                      <span className="row-sub">{humanizeRRule(s.rrule)}</span>
                      <span className="row-sub">Próxima {fmtWhen(s.next_run_at)}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="group" aria-labelledby="ag-obj">
            <h2 id="ag-obj" className="group-title">
              Objetivos <span className="count">{data.goals.length}</span>
            </h2>
            {data.goals.length === 0 ? (
              <p className="empty">Objetivos de longo prazo e os check-ins combinados aparecem aqui.</p>
            ) : (
              <ul className="list">
                {data.goals.map((g) => (
                  <li key={g.id} className="row">
                    <span className="row-main">
                      <span className="row-title">{g.title}</span>
                      {g.why && <span className="row-sub">{g.why}</span>}
                      <span className="row-sub">
                        {g.cadence ? `Check-in ${g.cadence}` : 'Check-in'}
                        {g.next_checkin_at ? ` · próximo ${fmtWhen(g.next_checkin_at)}` : ''}
                        {g.status === 'proposed' ? ' · proposto' : ''}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  )
}
