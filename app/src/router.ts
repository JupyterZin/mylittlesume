// Roteador mínimo (history API). As rotas espelham os links que o core gera
// (ex.: "ver completo" do Telegram aponta para /aprovacoes/<id>).
// A página Tela vive em /navegador: o caminho /tela pertence ao noVNC (tailscale serve).
import { useSyncExternalStore } from 'react'

export type Page = 'conversa' | 'tarefas' | 'aprovacoes' | 'agenda' | 'tela' | 'ajustes'

export interface Route {
  page: Page
  id?: number
}

export const PAGE_PATH: Record<Page, string> = {
  conversa: '/',
  tarefas: '/tarefas',
  aprovacoes: '/aprovacoes',
  agenda: '/agenda',
  tela: '/navegador',
  ajustes: '/ajustes',
}

export function parseRoute(pathname: string): Route {
  const parts = pathname.replace(/\/+$/, '').split('/').filter(Boolean)
  const [head, rawId] = parts
  const id = rawId && /^\d+$/.test(rawId) ? Number(rawId) : undefined
  switch (head) {
    case undefined:
    case 'conversa':
      return { page: 'conversa' }
    case 'tarefas':
      return { page: 'tarefas', id }
    case 'aprovacoes':
      return { page: 'aprovacoes', id }
    case 'agenda':
      return { page: 'agenda' }
    case 'navegador':
      return { page: 'tela' }
    case 'ajustes':
      return { page: 'ajustes' }
    default:
      return { page: 'conversa' }
  }
}

export function hrefFor(route: Route): string {
  const base = PAGE_PATH[route.page]
  return route.id !== undefined ? `${base}/${route.id}` : base
}

const listeners = new Set<() => void>()

function subscribe(fn: () => void): () => void {
  listeners.add(fn)
  window.addEventListener('popstate', fn)
  return () => {
    listeners.delete(fn)
    window.removeEventListener('popstate', fn)
  }
}

export function navigate(to: string | Route, opts: { replace?: boolean } = {}): void {
  const href = typeof to === 'string' ? to : hrefFor(to)
  if (href === location.pathname) return
  if (opts.replace) history.replaceState(null, '', href)
  else history.pushState(null, '', href)
  listeners.forEach((fn) => fn())
}

export function useRoute(): Route {
  const path = useSyncExternalStore(subscribe, () => location.pathname, () => '/')
  return parseRoute(path)
}
