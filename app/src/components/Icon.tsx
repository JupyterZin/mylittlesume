// Ícones de traço (24×24, 1.75 px), desenhados para o Talos.
import type { SVGProps } from 'react'

const PATHS = {
  conversa: (
    <path d="M5 4.75h14A1.75 1.75 0 0 1 20.75 6.5v9A1.75 1.75 0 0 1 19 17.25h-7.4L7 20.75v-3.5H5A1.75 1.75 0 0 1 3.25 15.5v-9A1.75 1.75 0 0 1 5 4.75Z" />
  ),
  tarefas: (
    <>
      <path d="M4 6.5l1.6 1.6L8.6 5" />
      <path d="M4 13.5l1.6 1.6 3-3.1" />
      <path d="M11.5 6.75h8.5M11.5 13.75h8.5M11.5 19.25h5" />
      <circle cx="6" cy="19.25" r="1.2" />
    </>
  ),
  aprovacoes: (
    <>
      <path d="M12 3.25l2 1.45 2.45-.1.75 2.33 2.02 1.4-.8 2.32.8 2.32-2.02 1.4-.75 2.33-2.45-.1L12 18.25l-2-1.45-2.45.1-.75-2.33-2.02-1.4.8-2.32-.8-2.32 2.02-1.4.75-2.33 2.45.1Z" />
      <path d="M9.2 10.8l2 2 3.6-3.8" />
      <path d="M8.5 17.7 7.5 21l4.5-1.7 4.5 1.7-1-3.3" />
    </>
  ),
  agenda: (
    <>
      <rect x="3.75" y="5.25" width="16.5" height="15" rx="2" />
      <path d="M3.75 9.75h16.5M8 3.25v4M16 3.25v4" />
      <path d="M8 13.5h2M14 13.5h2M8 17h2" />
    </>
  ),
  tela: (
    <>
      <rect x="2.75" y="4.25" width="18.5" height="12.5" rx="2" />
      <path d="M2.75 7.75h18.5M9 20.25h6M12 16.75v3.5" />
      <circle cx="5.4" cy="6" r=".45" />
    </>
  ),
  ajustes: (
    <>
      <path d="M4 7h9M17 7h3M4 17h3M11 17h9" />
      <circle cx="15" cy="7" r="2.1" />
      <circle cx="9" cy="17" r="2.1" />
    </>
  ),
  enviar: <path d="M12 19.25V5.5M6.25 11 12 5.25 17.75 11" />,
  mic: (
    <>
      <rect x="9" y="3.25" width="6" height="11" rx="3" />
      <path d="M5.75 11a6.25 6.25 0 0 0 12.5 0M12 17.25v3.5" />
    </>
  ),
  pausa: <path d="M9 5.5v13M15 5.5v13" />,
  play: <path d="M8 5.25v13.5L18.5 12 8 5.25Z" />,
  voltar: <path d="M14.75 5.5 8.25 12l6.5 6.5" />,
  avancar: <path d="m9.25 5.5 6.5 6.5-6.5 6.5" />,
  fechar: <path d="M6 6l12 12M18 6 6 18" />,
  editar: <path d="M14.5 5.5l4 4M4.75 19.25l1-4.1L15.9 5a1.6 1.6 0 0 1 2.25 0l.85.85a1.6 1.6 0 0 1 0 2.25L8.85 18.25l-4.1 1Z" />,
  apagar: <path d="M4.75 7h14.5M9.5 7V5.25h5V7M6.75 7l.9 12.25h8.7L17.25 7M10.25 10.75v5M13.75 10.75v5" />,
  alerta: (
    <>
      <path d="M12 4.25 2.9 19.25h18.2L12 4.25Z" />
      <path d="M12 10v4M12 16.6v.4" />
    </>
  ),
  cadeado: (
    <>
      <rect x="5.25" y="10.25" width="13.5" height="10" rx="2" />
      <path d="M8.25 10.25V7.5a3.75 3.75 0 0 1 7.5 0v2.75" />
    </>
  ),
  maos: (
    <>
      <path d="M7 11.5V6.25a1.25 1.25 0 0 1 2.5 0v4.5M9.5 10.75V4.75a1.25 1.25 0 0 1 2.5 0v6M12 10.75v-5a1.25 1.25 0 0 1 2.5 0v5.5M14.5 11.25V7.75a1.25 1.25 0 0 1 2.5 0v6.5a6 6 0 0 1-6 6h-.5a5.5 5.5 0 0 1-4.6-2.5l-2.3-3.6a1.3 1.3 0 0 1 2-1.6L7 14" />
    </>
  ),
  link: <path d="M13.5 5.25h5.25v5.25M18.5 5.5l-8 8M16.25 13.75v4a1.5 1.5 0 0 1-1.5 1.5h-8.5a1.5 1.5 0 0 1-1.5-1.5v-8.5a1.5 1.5 0 0 1 1.5-1.5h4" />,
  relogio: (
    <>
      <circle cx="12" cy="12" r="8.25" />
      <path d="M12 7.5V12l3 2" />
    </>
  ),
} as const

export type IconName = keyof typeof PATHS

export function Icon({ name, size = 22, ...rest }: { name: IconName; size?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {PATHS[name]}
    </svg>
  )
}
