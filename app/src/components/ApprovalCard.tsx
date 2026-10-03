// Cartão de aprovação (SPEC Anexo A): o que sai, para quem, dados pessoais, risco e motivo.
import { useEffect, useState } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import { navigate } from '../router'
import { actionLabel, approveVerb, doneLabel, RISK_LABEL } from '../lib/verbs'
import { fmtRelative, fmtWhen } from '../lib/format'
import type { Approval } from '../types'
import { Icon } from './Icon'
import { Sheet } from './Sheet'

function Screenshot({ id }: { id: number }) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    let made: string | null = null
    api
      .screenshot(id)
      .then((b) => {
        if (!alive) return
        made = URL.createObjectURL(b)
        setUrl(made)
      })
      .catch(() => undefined)
    return () => {
      alive = false
      if (made) URL.revokeObjectURL(made)
    }
  }, [id])
  if (!url) return null
  return (
    <figure className="approval-shot">
      <img src={url} alt="Captura da página no momento da pausa" />
    </figure>
  )
}

export function ApprovalCard({ a, variant, highlight }: { a: Approval; variant: 'full' | 'inline'; highlight?: boolean }) {
  const decide = useStore((s) => s.decide)
  const [busy, setBusy] = useState<null | 'approve' | 'later' | 'edit' | 'reject'>(null)
  const [sheet, setSheet] = useState<null | 'edit' | 'reject'>(null)
  const [note, setNote] = useState('')
  const d = a.details
  const pending = a.status === 'pending'
  const verb = approveVerb(a.kind)
  const action = actionLabel(a.kind)

  if (!pending && variant === 'inline') {
    return (
      <div className="approval-resolved" data-status={a.status}>
        <Icon name="aprovacoes" size={18} />
        <span>
          {doneLabel(a.kind, a.status)} · {action}
          <span className="muted"> · proposta #{a.id}</span>
        </span>
      </div>
    )
  }

  const run = async (decision: 'approve' | 'reject' | 'edit' | 'later', text = '') => {
    setBusy(decision)
    const ok = await decide(a.id, decision, text)
    setBusy(null)
    if (ok) {
      setSheet(null)
      setNote('')
    }
  }

  const risk = RISK_LABEL[a.risk] ?? a.risk
  const novos = d.to.filter((r) => r.status === 'novo')

  return (
    <article
      className="approval"
      data-variant={variant}
      data-risk={a.risk}
      data-status={a.status}
      data-highlight={highlight ? 'true' : undefined}
      id={`proposta-${a.id}`}
      aria-labelledby={`proposta-${a.id}-titulo`}
    >
      <header className="approval-head">
        <p className="kicker">
          Proposta #{a.id}
          {d.task_title ? ` · ${d.task_title}` : a.task_id ? ` · tarefa #${a.task_id}` : ''}
        </p>
        <h3 id={`proposta-${a.id}-titulo`} className="approval-title">
          {action}
        </h3>
        <span className="chip" data-tone={a.risk === 'alto' ? 'bad' : a.risk === 'medio' ? 'warn' : 'neutral'}>
          Risco {risk}
        </span>
      </header>

      {(d.to.length > 0 || d.subject || d.when) && (
        <dl className="facts">
          {d.to.length > 0 && (
            <div>
              <dt>Para</dt>
              <dd>
                <ul className="recipients">
                  {d.to.map((r) => (
                    <li key={r.address} data-status={r.status}>
                      <span className="addr">{r.address}</span>
                      {r.note && (
                        <span className="recipient-note">
                          {r.status === 'novo' && <Icon name="alerta" size={14} />}
                          {r.note}
                          {r.source_url && (
                            <>
                              {' · '}
                              <a href={r.source_url} target="_blank" rel="noreferrer noopener">
                                {r.source_url.replace(/^https?:\/\//, '')}
                              </a>
                            </>
                          )}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </dd>
            </div>
          )}
          {d.subject && (
            <div>
              <dt>Assunto</dt>
              <dd>{d.subject}</dd>
            </div>
          )}
          {d.when && (
            <div>
              <dt>Quando</dt>
              <dd>{d.when}</dd>
            </div>
          )}
        </dl>
      )}

      {d.summary && <p className="approval-summary">{d.summary}</p>}
      {d.body && (
        <div className="approval-body" data-clamp={variant === 'inline' ? 'true' : undefined}>
          {d.body}
        </div>
      )}
      {variant === 'inline' && d.body && d.body.split('\n').length > 5 && (
        <a
          className="link"
          href={`/aprovacoes/${a.id}`}
          onClick={(e) => {
            e.preventDefault()
            navigate(`/aprovacoes/${a.id}`)
          }}
        >
          Ver completo
        </a>
      )}
      {d.screenshot && <Screenshot id={a.id} />}

      {(d.personal_data.length > 0 || d.raw_personal.length > 0) && (
        <div className="approval-data">
          {d.personal_data.length > 0 && (
            <p>
              <span className="label">Dados pessoais incluídos</span>
              <span className="chips">
                {d.personal_data.map((k) => (
                  <span key={k} className="chip" data-tone="data">
                    <Icon name="cadeado" size={13} />
                    {k}
                  </span>
                ))}
              </span>
            </p>
          )}
          {d.raw_personal.length > 0 && (
            <p className="warn-line">
              <Icon name="alerta" size={16} />
              Dados pessoais escritos por extenso: {d.raw_personal.join(', ')}
            </p>
          )}
        </div>
      )}

      <div className="approval-why">
        {novos.length > 0 && (
          <p className="warn-line">
            <Icon name="alerta" size={16} />
            {novos.length === 1 ? 'Destinatário novo' : 'Destinatários novos'}: confira antes de aprovar.
          </p>
        )}
        {d.risk_why && (
          <p>
            <span className="label">Risco {risk}:</span> {d.risk_why}
          </p>
        )}
        {d.reason && (
          <p>
            <span className="label">Por que:</span> {d.reason}
          </p>
        )}
        {pending && a.expires_at && <p className="muted small">Expira {fmtRelative(a.expires_at)}</p>}
      </div>

      {pending ? (
        <div className="approval-actions">
          <button type="button" className="btn btn-primary btn-block" disabled={busy !== null} onClick={() => run('approve')}>
            {busy === 'approve' ? 'Aprovando…' : verb}
          </button>
          <div className="approval-secondary">
            <button type="button" className="btn btn-quiet" disabled={busy !== null} onClick={() => setSheet('edit')}>
              <Icon name="editar" size={18} />
              Editar
            </button>
            <button type="button" className="btn btn-quiet" data-tone="bad" disabled={busy !== null} onClick={() => setSheet('reject')}>
              Recusar
            </button>
            <button type="button" className="btn btn-quiet" disabled={busy !== null} onClick={() => run('later')}>
              {busy === 'later' ? 'Ok…' : 'Lembrar mais tarde'}
            </button>
          </div>
        </div>
      ) : (
        <p className="approval-outcome" data-status={a.status}>
          {doneLabel(a.kind, a.status)}
          {a.decided_at && <span className="muted"> · {fmtWhen(a.decided_at)}</span>}
          {a.decided_via && <span className="muted"> · via {a.decided_via === 'app' ? 'app' : a.decided_via}</span>}
        </p>
      )}

      <Sheet open={sheet === 'edit'} title="Editar proposta" onClose={() => setSheet(null)}>
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault()
            if (note.trim()) void run('edit', note.trim())
          }}
        >
          <label className="field">
            <span>O que quer mudar?</span>
            <textarea
              rows={4}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Ex.: mais curto, sem o telefone, assine só como Lucas."
              autoFocus
            />
          </label>
          <p className="muted small">O Talos refaz a proposta com o seu pedido; esta fica substituída.</p>
          <button type="submit" className="btn btn-primary btn-block" disabled={!note.trim() || busy !== null}>
            {busy === 'edit' ? 'Enviando…' : 'Pedir alteração'}
          </button>
        </form>
      </Sheet>

      <Sheet open={sheet === 'reject'} title="Recusar proposta" onClose={() => setSheet(null)}>
        <form
          className="stack"
          onSubmit={(e) => {
            e.preventDefault()
            void run('reject', note.trim())
          }}
        >
          <label className="field">
            <span>Motivo (opcional)</span>
            <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Ajuda o Talos a acertar da próxima vez." />
          </label>
          <p className="muted small">Nada é enviado. O Talos fica sabendo do motivo, se você der um.</p>
          <button type="submit" className="btn btn-danger btn-block" disabled={busy !== null}>
            {busy === 'reject' ? 'Recusando…' : 'Recusar proposta'}
          </button>
        </form>
      </Sheet>
    </article>
  )
}
