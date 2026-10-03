// Fila de aprovações: cartões completos; histórico das decididas abaixo.
import { useEffect, useMemo } from 'react'
import { pendingApprovals, useStore } from '../store'
import { ApprovalCard } from '../components/ApprovalCard'
import { PageHeader } from '../components/PageHeader'

export function Aprovacoes({ id }: { id?: number }) {
  const approvals = useStore((s) => s.approvals)
  const pending = useMemo(() => pendingApprovals(approvals), [approvals])
  const decided = useMemo(() => approvals.filter((a) => a.status !== 'pending').slice(0, 15), [approvals])

  useEffect(() => {
    if (id === undefined) return
    const t = setTimeout(() => {
      document.getElementById(`proposta-${id}`)?.scrollIntoView({ block: 'start', behavior: 'auto' })
    }, 60)
    return () => clearTimeout(t)
  }, [id, approvals.length])

  return (
    <div className="page">
      <PageHeader
        title="Aprovações"
        subtitle={pending.length ? `${pending.length} aguardando você` : 'Nada aguardando você'}
      />
      {pending.length === 0 && (
        <p className="empty">
          Quando o Talos precisar enviar, reservar, comprar ou partilhar algo em seu nome, a proposta aparece aqui com tudo o
          que vai sair.
        </p>
      )}
      <div className="stack-lg">
        {pending.map((a) => (
          <ApprovalCard key={a.id} a={a} variant="full" highlight={a.id === id} />
        ))}
      </div>
      {decided.length > 0 && (
        <section aria-labelledby="decididas" className="group">
          <h2 id="decididas" className="group-title">
            Decididas recentemente
          </h2>
          <div className="stack">
            {decided.map((a) =>
              a.id === id ? (
                <ApprovalCard key={a.id} a={a} variant="full" highlight />
              ) : (
                <ApprovalCard key={a.id} a={a} variant="inline" />
              ),
            )}
          </div>
        </section>
      )}
    </div>
  )
}
