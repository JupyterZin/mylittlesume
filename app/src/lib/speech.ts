// Voz pelo navegador (Web Speech API): ditar mensagens e, opcionalmente, ouvir as respostas.
import { useCallback, useEffect, useRef, useState } from 'react'

interface RecognitionResult {
  isFinal: boolean
  0: { transcript: string }
}
interface RecognitionEvent {
  resultIndex: number
  results: ArrayLike<RecognitionResult>
}
interface Recognition {
  lang: string
  interimResults: boolean
  continuous: boolean
  onresult: ((e: RecognitionEvent) => void) | null
  onend: (() => void) | null
  onerror: ((e: { error: string }) => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}
type RecognitionCtor = new () => Recognition

function ctor(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

export function useDictation(onText: (text: string) => void) {
  const [listening, setListening] = useState(false)
  const [error, setError] = useState('')
  const rec = useRef<Recognition | null>(null)
  const cb = useRef(onText)
  cb.current = onText
  const supported = typeof window !== 'undefined' && ctor() !== null

  const stop = useCallback(() => {
    rec.current?.stop()
  }, [])

  const start = useCallback(() => {
    const C = ctor()
    if (!C) return
    const r = new C()
    r.lang = 'pt-BR'
    r.interimResults = true
    r.continuous = false
    r.onresult = (e) => {
      let text = ''
      for (let i = 0; i < e.results.length; i++) text += e.results[i][0].transcript
      cb.current(text.trim())
    }
    r.onerror = (e) => {
      setError(e.error === 'not-allowed' ? 'Sem permissão para o microfone.' : 'Não consegui ouvir. Tente de novo.')
    }
    r.onend = () => setListening(false)
    rec.current = r
    setError('')
    setListening(true)
    try {
      r.start()
    } catch {
      setListening(false)
    }
  }, [])

  useEffect(() => () => rec.current?.abort(), [])

  return { supported, listening, error, start, stop }
}

export function speak(text: string): void {
  if (!('speechSynthesis' in window)) return
  const clean = text
    .replace(/https?:\/\/\S+/g, 'link')
    .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/gu, '')
    .slice(0, 600)
  if (!clean.trim()) return
  const u = new SpeechSynthesisUtterance(clean)
  u.lang = 'pt-BR'
  const voice = window.speechSynthesis.getVoices().find((v) => v.lang.toLowerCase().startsWith('pt'))
  if (voice) u.voice = voice
  window.speechSynthesis.cancel()
  window.speechSynthesis.speak(u)
}
