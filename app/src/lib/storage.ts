// localStorage tolerante (modo privado, armazenamento bloqueado…).

export function load(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export function save(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    /* sem armazenamento: só vale para esta sessão */
  }
}

// O PIN só é guardado se o Lucas quiser ("lembrar neste aparelho"); senão fica em memória.
const PIN_KEY = 'talos.pin'
let sessionPin: string | null = null

export function getPin(): string | null {
  return sessionPin ?? load(PIN_KEY)
}

export function setPin(pin: string | null, remember: boolean): void {
  sessionPin = pin
  save(PIN_KEY, remember ? pin : null)
}

export function pinRemembered(): boolean {
  return load(PIN_KEY) !== null
}
