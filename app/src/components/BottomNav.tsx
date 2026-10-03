import type { MouseEvent } from 'react'
import { Icon, type IconName } from './Icon'
import { navigate, PAGE_PATH, type Page } from '../router'
import { pendingApprovals, useStore } from '../store'

const ITEMS: { page: Page; label: string; icon: IconName }[] = [
  { page: 'conversa', label: 'Conversa', icon: 'conversa' },
  { page: 'tarefas', label: 'Tarefas', icon: 'tarefas' },
  { page: 'aprovacoes', label: 'Aprovações', icon: 'aprovacoes' },
  { page: 'agenda', label: 'Agenda', icon: 'agenda' },
  { page: 'tela', label: 'Tela', icon: 'tela' },
  { page: 'ajustes', label: 'Ajustes', icon: 'ajustes' },
]

export function BottomNav({ current }: { current: Page }) {
  const pending = useStore((s) => pendingApprovals(s.approvals).length)
  const go = (e: MouseEvent<HTMLAnchorElement>, page: Page) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
    e.preventDefault()
    navigate(PAGE_PATH[page])
    window.scrollTo(0, 0)
  }
  return (
    <nav className="tabbar" aria-label="Navegação principal">
      {ITEMS.map((it) => {
        const isCurrent = it.page === current
        const badge = it.page === 'aprovacoes' && pending > 0 ? pending : 0
        return (
          <a
            key={it.page}
            href={PAGE_PATH[it.page]}
            className="tab"
            aria-current={isCurrent ? 'page' : undefined}
            onClick={(e) => go(e, it.page)}
          >
            <span className="tab-icon">
              <Icon name={it.icon} />
              {badge > 0 && (
                <span className="badge" aria-label={`${badge} pendente${badge === 1 ? '' : 's'}`}>
                  {badge > 9 ? '9+' : badge}
                </span>
              )}
            </span>
            <span className="tab-label">{it.label}</span>
          </a>
        )
      })}
    </nav>
  )
}
