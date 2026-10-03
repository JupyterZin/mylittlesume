// Ajustes: controle, conectores, Sentinela, memória, cofre (só chaves), persona, uso, silêncio,
// aparência, PIN e créditos.
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../api'
import { useStore } from '../store'
import { usePrefs, type MascotPref, type ThemePref } from '../prefs'
import { getPin, pinRemembered, setPin } from '../lib/storage'
import { reconnectNow } from '../live'
import { PageHeader } from '../components/PageHeader'
import { Icon } from '../components/Icon'
import { Sheet } from '../components/Sheet'
import { fmtRelative, fmtWhen, parseDate } from '../lib/format'
import type { MemoryFact, SentinelRules, SettingsView, Usage, VaultKey } from '../types'

function Section({ id, title, summary, children, open }: { id: string; title: string; summary?: ReactNode; children: ReactNode; open?: boolean }) {
  return (
    <details className="setting" id={id} open={open}>
      <summary>
        <span className="setting-title">{title}</span>
        {summary !== undefined && <span className="setting-summary">{summary}</span>}
        <Icon name="avancar" size={18} className="setting-chevron" />
      </summary>
      <div className="setting-body">{children}</div>
    </details>
  )
}

function Segmented<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

// ------------------------------------------------------------------ memória
function Memoria() {
  const [facts, setFacts] = useState<MemoryFact[] | null>(null)
  const [q, setQ] = useState('')
  const [editing, setEditing] = useState<MemoryFact | null>(null)
  const [value, setValue] = useState('')
  const [confirm, setConfirm] = useState<MemoryFact | null>(null)
  const toast = useStore((s) => s.toast)

  const load = () => api.memory().then(setFacts).catch(() => setFacts([]))
  useEffect(() => {
    void load()
  }, [])

  const shown = useMemo(() => {
    if (!facts) return []
    const n = q.trim().toLowerCase()
    return n ? facts.filter((f) => `${f.scope} ${f.key} ${f.value}`.toLowerCase().includes(n)) : facts
  }, [facts, q])

  return (
    <>
      {facts && facts.length > 6 && (
        <label className="field">
          <span className="sr-only">Buscar na memória</span>
          <input type="search" placeholder="Buscar na memória" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
      )}
      {facts && facts.length === 0 && <p className="muted">Ainda não há fatos. O Talos só guarda o que você diz ou confirma.</p>}
      <ul className="list facts-list">
        {shown.map((f) => (
          <li key={f.id} className="row">
            <span className="row-main">
              <span className="row-sub">
                {f.scope} · {f.key}
              </span>
              <span className="row-title fact-value">{f.value}</span>
              <span className="row-sub">{f.source === 'confirmado' ? 'confirmado por você' : 'dito por você'} · {fmtRelative(f.updated_at)}</span>
            </span>
            <span className="row-actions">
              <button
                type="button"
                className="icon-btn"
                aria-label={`Editar ${f.key}`}
                onClick={() => {
                  setEditing(f)
                  setValue(f.value)
                }}
              >
                <Icon name="editar" size={18} />
              </button>
              <button type="button" className="icon-btn" data-tone="bad" aria-label={`Apagar ${f.key}`} onClick={() => setConfirm(f)}>
                <Icon name="apagar" size={18} />
              </button>
            </span>
          </li>
        ))}
      </ul>
      <Sheet open={!!editing} title={editing ? `Editar · ${editing.key}` : 'Editar'} onClose={() => setEditing(null)}>
        <form
          className="stack"
          onSubmit={async (e) => {
            e.preventDefault()
            if (!editing) return
            try {
              await api.memoryPut(editing.id, value.trim())
              toast('Memória atualizada.')
              setEditing(null)
              void load()
            } catch (err) {
              toast(err instanceof Error ? err.message : 'Não foi possível salvar.', 'bad')
            }
          }}
        >
          <label className="field">
            <span>Valor</span>
            <textarea rows={3} value={value} onChange={(e) => setValue(e.target.value)} autoFocus />
          </label>
          <button type="submit" className="btn btn-primary btn-block" disabled={!value.trim()}>
            Salvar
          </button>
        </form>
      </Sheet>
      <Sheet open={!!confirm} title="Apagar este fato?" onClose={() => setConfirm(null)}>
        <div className="stack">
          <p>
            <strong>{confirm?.key}:</strong> {confirm?.value}
          </p>
          <p className="muted small">O Talos deixa de saber isto. Não dá para desfazer.</p>
          <button
            type="button"
            className="btn btn-danger btn-block"
            onClick={async () => {
              if (!confirm) return
              try {
                await api.memoryDelete(confirm.id)
                toast('Apagado da memória.')
                setConfirm(null)
                void load()
              } catch (err) {
                toast(err instanceof Error ? err.message : 'Não foi possível apagar.', 'bad')
              }
            }}
          >
            Apagar
          </button>
        </div>
      </Sheet>
    </>
  )
}

// ------------------------------------------------------------------ cofre
function Cofre() {
  const [keys, setKeys] = useState<VaultKey[] | null>(null)
  const [target, setTarget] = useState<{ key: string; isNew: boolean } | null>(null)
  const [newKey, setNewKey] = useState('dados.')
  const [value, setValue] = useState('')
  const [reveal, setReveal] = useState(false)
  const toast = useStore((s) => s.toast)
  const load = () => api.vaultKeys().then(setKeys).catch(() => setKeys([]))
  useEffect(() => {
    void load()
  }, [])
  const groups = [
    { kind: 'dado_pessoal', title: 'Dados pessoais', note: 'Só saem depois da sua aprovação, e o cartão diz quais.' },
    { kind: 'segredo', title: 'Segredos', note: 'Nunca saem pelo agente.' },
  ]
  const keyName = target?.isNew ? newKey.trim() : target?.key ?? ''
  const validKey = /^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$/.test(keyName) && (!target?.isNew || keyName.startsWith('dados.'))
  return (
    <>
      <p className="muted small">
        <Icon name="cadeado" size={14} /> Os valores nunca aparecem aqui: só dá para escrever um valor novo.
      </p>
      {groups.map((g) => {
        const list = (keys ?? []).filter((k) => k.kind === g.kind)
        return (
          <div key={g.kind} className="vault-group">
            <h3 className="sub-title">{g.title}</h3>
            <p className="muted small">{g.note}</p>
            {list.length === 0 ? (
              <p className="muted">Nenhum.</p>
            ) : (
              <ul className="list">
                {list.map((k) => (
                  <li key={k.key} className="row">
                    <span className="row-main">
                      <span className="row-title">{k.label}</span>
                      <span className="row-sub mono">{k.key}</span>
                    </span>
                    <button
                      type="button"
                      className="btn btn-small btn-quiet"
                      onClick={() => {
                        setTarget({ key: k.key, isNew: false })
                        setValue('')
                        setReveal(false)
                      }}
                    >
                      Editar valor
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )
      })}
      <button
        type="button"
        className="btn btn-secondary"
        onClick={() => {
          setTarget({ key: '', isNew: true })
          setNewKey('dados.')
          setValue('')
          setReveal(false)
        }}
      >
        Adicionar dado pessoal
      </button>
      <Sheet open={!!target} title={target?.isNew ? 'Novo dado pessoal' : `Novo valor · ${target?.key}`} onClose={() => setTarget(null)}>
        <form
          className="stack"
          autoComplete="off"
          onSubmit={async (e) => {
            e.preventDefault()
            try {
              await api.vaultPut(keyName, value)
              toast('Guardado no cofre.')
              setTarget(null)
              setValue('')
              void load()
            } catch (err) {
              toast(err instanceof Error ? err.message : 'Não foi possível salvar.', 'bad')
            }
          }}
        >
          {target?.isNew && (
            <label className="field">
              <span>Chave</span>
              <input value={newKey} onChange={(e) => setNewKey(e.target.value.toLowerCase())} spellCheck={false} autoCapitalize="off" />
              <small className="muted">Ex.: dados.iban, dados.data_nascimento</small>
            </label>
          )}
          <label className="field">
            <span>Valor</span>
            <input
              type={reveal ? 'text' : 'password'}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              autoFocus={!target?.isNew}
            />
          </label>
          <label className="check">
            <input type="checkbox" checked={reveal} onChange={(e) => setReveal(e.target.checked)} />
            <span>Mostrar o que estou digitando</span>
          </label>
          <p className="muted small">O valor vai cifrado para o cofre e não volta para o app.</p>
          <button type="submit" className="btn btn-primary btn-block" disabled={!value || !validKey}>
            Guardar no cofre
          </button>
        </form>
      </Sheet>
    </>
  )
}

// ------------------------------------------------------------------ uso
function Uso({ usage }: { usage: Usage | null }) {
  if (!usage) return <p className="muted">Carregando…</p>
  const t = usage.today
  const pct = Math.min(100, Math.round((t.runs / Math.max(1, usage.daily_limit)) * 100))
  const max = Math.max(1, ...usage.days.map((d) => d.runs))
  return (
    <div className="stack">
      <div>
        <p className="usage-big">
          <strong>{t.runs}</strong> de {usage.daily_limit} execuções hoje
        </p>
        <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={usage.daily_limit} aria-valuenow={t.runs} aria-label="Execuções hoje">
          <span style={{ width: `${pct}%` }} data-high={pct >= 80 ? 'true' : undefined} />
        </div>
        <p className="muted small">
          {t.turns} turnos · {(t.input_tokens + t.output_tokens).toLocaleString('pt-BR')} tokens · custo equivalente ~US${' '}
          {t.cost_usd.toFixed(2)} (informativo; a assinatura não cobra por token)
        </p>
        {usage.rate_limited_until && parseDate(usage.rate_limited_until)! > new Date() && (
          <p className="warn-line">
            <Icon name="relogio" size={16} /> Limite da assinatura até {fmtWhen(usage.rate_limited_until)}
          </p>
        )}
      </div>
      <div className="bars" aria-label="Execuções nos últimos 7 dias">
        {usage.days.map((d) => (
          <div key={d.date} className="bar" title={`${d.date}: ${d.runs} execuções`}>
            <span className="bar-fill" style={{ height: `${(d.runs / max) * 100}%` }} />
            <span className="bar-label">{new Date(`${d.date}T12:00:00Z`).toLocaleDateString('pt-BR', { weekday: 'narrow', timeZone: 'UTC' })}</span>
          </div>
        ))}
      </div>
      <p className="muted small">Modo: {usage.auth_mode === 'subscription' ? 'assinatura' : 'chave de API'}</p>
    </div>
  )
}

// ------------------------------------------------------------------ página
export function Ajustes() {
  const app = useStore((s) => s.app)
  const setPaused = useStore((s) => s.setPaused)
  const toast = useStore((s) => s.toast)
  const prefs = usePrefs()
  const [settings, setSettings] = useState<SettingsView | null>(null)
  const [rules, setRules] = useState<SentinelRules | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [pin, setPinValue] = useState('')
  const [hasPin, setHasPin] = useState(() => !!getPin())

  useEffect(() => {
    api.settings().then(setSettings).catch(() => undefined)
    api.rules().then(setRules).catch(() => undefined)
    api.usage().then(setUsage).catch(() => undefined)
  }, [])

  const paused = app?.paused ?? false
  const okCount = settings?.connectors.filter((c) => c.ok).length ?? 0

  return (
    <div className="page">
      <PageHeader title="Ajustes" subtitle={settings ? `${settings.agent_name} ${settings.version}` : ' '} />

      <section className="card control-card" aria-labelledby="ctl">
        <div>
          <h2 id="ctl" className="card-title">
            {paused ? 'Pausado' : 'Funcionando'}
          </h2>
          <p className="muted small">
            {paused
              ? 'Nada roda nem é executado até você retomar.'
              : 'O botão de pânico para tudo na hora: execuções, envios e propostas.'}
          </p>
        </div>
        <button type="button" className={paused ? 'btn btn-primary' : 'btn btn-danger'} onClick={() => void setPaused(!paused)}>
          <Icon name={paused ? 'play' : 'pausa'} size={18} />
          {paused ? 'Retomar' : 'Pausar'}
        </button>
      </section>

      <div className="settings">
        <Section id="conectores" title="Conectores" summary={settings ? `${okCount} de ${settings.connectors.length} ativos` : ''}>
          <ul className="list">
            {settings?.connectors.map((c) => (
              <li key={c.id} className="row">
                <span className="status-dot" data-ok={c.ok ? 'true' : 'false'} aria-hidden="true" />
                <span className="row-main">
                  <span className="row-title">{c.name}</span>
                  <span className="row-sub">
                    {c.ok ? 'conectado' : 'desligado'}
                    {c.detail ? ` · ${c.id === 'monitor' ? `último ciclo ${fmtRelative(c.detail)}` : c.detail}` : ''}
                  </span>
                </span>
              </li>
            ))}
          </ul>
          <p className="muted small">
            Para reautenticar o Google, rode <code>talos google-auth</code> no servidor e siga os passos do RUNBOOK.
          </p>
        </Section>

        <Section id="sentinela" title="Sentinela" summary={rules ? `classificador ${rules.classifier ? 'ligado' : 'desligado'}` : ''}>
          <div className="row">
            <span className="row-main">
              <span className="row-title">Classificador (Haiku)</span>
              <span className="row-sub">Só endurece decisões, nunca afrouxa. Para mudar, edite SENTINEL_CLASSIFIER no servidor.</span>
            </span>
            <span className="chip" data-tone={rules?.classifier ? 'good' : 'muted'}>
              {rules?.classifier ? 'ligado' : 'desligado'}
            </span>
          </div>
          <h3 className="sub-title">Regras</h3>
          <pre className="code" tabIndex={0} aria-label="Regras da Sentinela (somente leitura)">
            {rules?.yaml ?? '…'}
          </pre>
        </Section>

        <Section id="memoria" title="Memória" summary="ver, editar e apagar">
          <Memoria />
        </Section>

        <Section id="cofre" title="Cofre" summary="só as chaves">
          <Cofre />
        </Section>

        <Section id="persona" title="Persona" summary="CLAUDE.md">
          {settings?.persona ? (
            <pre className="code prose-pre" tabIndex={0} aria-label="Persona do Talos (somente leitura)">
              {settings.persona}
            </pre>
          ) : (
            <p className="muted">Sem persona no workspace.</p>
          )}
        </Section>

        <Section id="uso" title="Uso da assinatura" summary={usage ? `${usage.today.runs} de ${usage.daily_limit} hoje` : ''}>
          <Uso usage={usage} />
        </Section>

        <Section
          id="silencio"
          title="Horas de silêncio"
          summary={settings ? `${settings.quiet_hours.window.replace('-', '–')}${settings.quiet_hours.active ? ' · agora' : ''}` : ''}
        >
          <p>
            Entre <strong>{settings?.quiet_hours.window.split('-')[0]}</strong> e{' '}
            <strong>{settings?.quiet_hours.window.split('-')[1]}</strong> só passam avisos urgentes; o resto chega quando a janela
            acaba. {settings?.quiet_hours.active ? 'Estamos nas horas de silêncio agora.' : ''}
          </p>
          <p className="muted small">Para mudar, edite QUIET_HOURS no servidor.</p>
        </Section>

        <Section id="aparencia" title="Aparência e voz">
          <div className="stack">
            <div>
              <h3 className="sub-title">Tema</h3>
              <Segmented<ThemePref>
                label="Tema"
                value={prefs.theme}
                onChange={prefs.setTheme}
                options={[
                  { value: 'auto', label: 'Automático' },
                  { value: 'light', label: 'Claro' },
                  { value: 'dark', label: 'Escuro' },
                ]}
              />
            </div>
            <div>
              <h3 className="sub-title">Mascote</h3>
              <Segmented<MascotPref>
                label="Mascote"
                value={prefs.mascot}
                onChange={prefs.setMascot}
                options={[
                  { value: 'auto', label: 'Automático' },
                  { value: '3d', label: '3D' },
                  { value: '2d', label: '2D' },
                ]}
              />
              {prefs.mascot === 'auto' && prefs.autoFellBack && (
                <p className="muted small">Este aparelho ficou lento com o 3D, então uso as poses 2D. Escolha 3D para tentar de novo.</p>
              )}
            </div>
            <label className="check">
              <input type="checkbox" checked={prefs.speak} onChange={(e) => prefs.setSpeak(e.target.checked)} />
              <span>Ler as respostas do Talos em voz alta</span>
            </label>
          </div>
        </Section>

        <Section id="pin" title="PIN do app" summary={hasPin ? (pinRemembered() ? 'lembrado neste aparelho' : 'nesta sessão') : 'sem PIN'}>
          <form
            className="stack"
            onSubmit={(e) => {
              e.preventDefault()
              setPin(pin.trim() || null, true)
              setHasPin(!!pin.trim())
              setPinValue('')
              toast(pin.trim() ? 'PIN guardado neste aparelho.' : 'PIN esquecido.')
              reconnectNow()
            }}
          >
            <p className="muted small">
              Se o servidor tiver APP_PIN, o app envia este PIN em cada pedido. Fica só neste aparelho.
            </p>
            <label className="field">
              <span>PIN</span>
              <input type="password" inputMode="numeric" autoComplete="new-password" value={pin} onChange={(e) => setPinValue(e.target.value)} />
            </label>
            <div className="row-buttons">
              <button type="submit" className="btn btn-primary" disabled={!pin.trim()}>
                Guardar PIN
              </button>
              {hasPin && (
                <button
                  type="button"
                  className="btn btn-quiet"
                  onClick={() => {
                    setPin(null, false)
                    setHasPin(false)
                    toast('PIN esquecido neste aparelho.')
                  }}
                >
                  Esquecer PIN
                </button>
              )}
            </div>
          </form>
        </Section>

        <Section id="sobre" title="Sobre">
          <div className="stack prose">
            <p>
              <strong>Talos</strong> {settings?.version} · {settings?.auth_mode === 'subscription' ? 'assinatura do Claude' : 'chave de API'}
            </p>
            <p>
              O mascote é o <strong>RobotExpressive</strong>, de <strong>Tomás Laulhé (Quaternius)</strong>, com modificações de{' '}
              <strong>Don McCurdy</strong>. Licença{' '}
              <a href="https://creativecommons.org/publicdomain/zero/1.0/deed.pt_BR" target="_blank" rel="noreferrer noopener">
                CC0 1.0
              </a>{' '}
              (domínio público), recolorido em bronze e pátina. Obrigado!
            </p>
            <p>
              <a className="link-strong" href="https://www.patreon.com/quaternius" target="_blank" rel="noreferrer noopener">
                Apoie o Quaternius no Patreon
                <Icon name="link" size={16} />
              </a>
            </p>
            <p className="muted small">Feito com three.js, React Three Fiber e Archivo (SIL OFL).</p>
          </div>
        </Section>
      </div>
    </div>
  )
}
