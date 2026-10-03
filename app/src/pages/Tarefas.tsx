// Tarefas agrupadas por situação; cada uma abre a sua timeline de auditoria.
import { useEffect, useMemo, useState } from 'react'
import { useStore } from '../store'
import { navigate } from '../router'
import { Icon } from '../components/Icon'
import { ApprovalCard } from '../components/ApprovalCard'
import { PageHeader } from '../components/PageHeader'
import { fmtDay, fmtRelative, fmtTime, plural, TASK_GROUPS, TASK_STATUS_LABEL, taskGroup } from '../lib/format'
import { describeEvent } from '../lib/events'
import type { Task, TaskStatus } from '../types'

const STATUS_TONE: Partial<Record<TaskStatus, string>> = {
  running: 'agent',
  planning: 'agent',
  waiting_approval: 'warn',
  waiting_external: 'neutral',
  done: 'good',
  failed: 'bad',
  cancelled: 'muted',
}

function StatusChip({ status }: { status: TaskStatus }) {
  return (
    <span className="chip" data-tone={STATUS_TONE[status] ?? 'neutral'}>
      {TASK_STATUS_LABEL[status] ?? status}
    </span>
  )
}

function TaskRow({ t }: { t: Task }) {
  return (
    <li>
      <a
        className="row row-link"
        href={`/tarefas/${t.id}`}
        onClick={(e) => {
          e.preventDefault()
          navigate(`/tarefas/${t.id}`)
        }}
      >
        <span className="row-main">
          <span className="row-title">{t.title}</span>
          <span className="row-sub">
            #{t.id} · atualizada {fmtRelative(t.updated_at)}
          </span>
        </span>
        <StatusChip status={t.status} />
        <Icon name="avancar" size={18} className="row-chevron" />
      </a>
    </li>
  )
}

function TaskList() {
  const tasks = useStore((s) => s.tasks)
  const [showAllDone, setShowAllDone] = useState(false)
  const groups = useMemo(() => {
    const g: Record<string, Task[]> = { voce: [], andamento: [], terceiros: [], concluidas: [] }
    for (const t of tasks) g[taskGroup(t.status)].push(t)
    return g
  }, [tasks])
  const open = tasks.length - groups.concluidas.length

  return (
    <div className="page">
      <PageHeader title="Tarefas" subtitle={open ? `${plural(open, 'aberta', 'abertas')}` : 'Nada em aberto'} />
      {tasks.length === 0 && (
        <p className="empty">Quando você pedir algo que leva tempo, o Talos abre uma tarefa e mostra aqui cada passo.</p>
      )}
      {TASK_GROUPS.map(({ id, title }) => {
        const list = groups[id]
        if (!list.length) return null
        const shown = id === 'concluidas' && !showAllDone ? list.slice(0, 8) : list
        return (
          <section key={id} className="group" aria-labelledby={`g-${id}`}>
            <h2 id={`g-${id}`} className="group-title">
              {title} <span className="count">{list.length}</span>
            </h2>
            <ul className="list">
              {shown.map((t) => (
                <TaskRow key={t.id} t={t} />
              ))}
            </ul>
            {shown.length < list.length && (
              <button type="button" className="btn btn-quiet more" onClick={() => setShowAllDone(true)}>
                Ver todas as {list.length}
              </button>
            )}
          </section>
        )
      })}
    </div>
  )
}

function TaskDetail({ id }: { id: number }) {
  const task = useStore((s) => s.tasks.find((t) => t.id === id))
  const events = useStore((s) => s.timelines[id])
  const allApprovals = useStore((s) => s.approvals)
  const approvals = useMemo(
    () => allApprovals.filter((a) => a.task_id === id && a.status === 'pending'),
    [allApprovals, id],
  )
  const loadTimeline = useStore((s) => s.loadTimeline)
  const refreshTasks = useStore((s) => s.refreshTasks)

  useEffect(() => {
    void loadTimeline(id)
    if (!task) void refreshTasks()
  }, [id])

  let lastDay = ''
  return (
    <div className="page">
      <header className="page-head detail-head">
        <a
          className="back"
          href="/tarefas"
          onClick={(e) => {
            e.preventDefault()
            navigate('/tarefas')
          }}
        >
          <Icon name="voltar" size={20} />
          Tarefas
        </a>
        <h1 className="title">{task?.title ?? `Tarefa #${id}`}</h1>
        {task && (
          <p className="subtitle">
            <StatusChip status={task.status} /> <span className="muted">#{task.id} · criada {fmtRelative(task.created_at)}</span>
          </p>
        )}
      </header>
      {task?.goal && task.goal !== task.title && (
        <section className="card prose">
          <h2 className="card-title">Objetivo</h2>
          <p>{task.goal}</p>
        </section>
      )}
      {task?.summary && (
        <section className="card prose">
          <h2 className="card-title">Resumo</h2>
          <p>{task.summary}</p>
        </section>
      )}
      {approvals.map((a) => (
        <ApprovalCard key={a.id} a={a} variant="full" />
      ))}
      <section aria-labelledby="timeline-title">
        <h2 id="timeline-title" className="group-title">
          Linha do tempo
        </h2>
        {!events && <p className="muted">Carregando…</p>}
        {events && events.length === 0 && <p className="muted">Ainda sem eventos registrados.</p>}
        {events && events.length > 0 && (
          <ol className="timeline">
            {events.map((e, i) => {
              const d = describeEvent(e.type, e.payload_json ?? {})
              const day = fmtDay(e.created_at)
              const sep = day !== lastDay
              lastDay = day
              return (
                <li key={e.id ?? i} data-tone={d.tone}>
                  {sep && <p className="timeline-day">{day}</p>}
                  <div className="timeline-item">
                    <span className="timeline-dot" aria-hidden="true" />
                    <div>
                      <p className="timeline-title">
                        {d.title} <time className="muted small">{fmtTime(e.created_at)}</time>
                      </p>
                      {d.detail && <p className="timeline-detail">{d.detail}</p>}
                    </div>
                  </div>
                </li>
              )
            })}
          </ol>
        )}
      </section>
    </div>
  )
}

export function Tarefas({ id }: { id?: number }) {
  return id !== undefined ? <TaskDetail id={id} /> : <TaskList />
}
