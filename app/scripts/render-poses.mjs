#!/usr/bin/env node
// Gera as poses 2D do mascote (public/poses/*.png) e os ícones do PWA (public/icons/*.png)
// a partir do próprio talos.glb, num Chromium headless (WebGL por SwiftShader).
//
//   npm run build && PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers npm run poses
//
// Usa o Playwright instalado globalmente (não é dependência do app: o servidor não precisa dele).
// Opções: --only=idle,yes  (só algumas poses)   --no-icons   --out=<pasta>
import { createRequire } from 'node:module'
import { execSync, spawn } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..')
const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, v] = a.replace(/^--/, '').split('=')
    return [k, v ?? true]
  }),
)

function loadPlaywright() {
  const require = createRequire(import.meta.url)
  try {
    return require('playwright')
  } catch {
    const globalRoot = execSync('npm root -g').toString().trim()
    return require(path.join(globalRoot, 'playwright'))
  }
}

// estado → [pose (nome do ficheiro), clipe/tempo em segundos, gesto]
const POSES = [
  ['idle', 'idle', 0.6],
  ['greeting', 'greeting', 0.62],
  ['typing', 'typing', 0.42],
  ['thinking', 'thinking', 1.4],
  ['working', 'working', 0.26],
  ['long-task', 'long_task', 0.22],
  ['waiting-approval', 'waiting_approval', 0.42],
  ['approved', 'approved', 0.95],
  ['yes', 'approved', 0.3, 'Yes'],
  ['rejected', 'rejected', 0.62],
  ['reply', 'reply', 0.25],
  ['milestone', 'milestone', 1.2],
  ['error', 'error', 0.62],
  ['blocked', 'blocked', 0.62],
  ['quiet-hours', 'quiet_hours', 0.42],
  ['paused', 'paused', 0.42],
]

const ICONS = [
  // [ficheiro, tamanho, afastamento da câmera]
  ['icon-512.png', 512, 1],
  ['icon-192.png', 192, 1],
  ['apple-touch-icon.png', 180, 1],
  ['icon-maskable-512.png', 512, 1.35],
]

async function waitForServer(url, tries = 60) {
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(url)
      if (r.ok) return
    } catch {
      /* ainda a arrancar */
    }
    await new Promise((r) => setTimeout(r, 250))
  }
  throw new Error(`servidor de pré-visualização não respondeu em ${url}`)
}

const port = Number(args.port ?? 4179)
const base = `http://127.0.0.1:${port}`
const server = spawn('npx', ['vite', 'preview', '--port', String(port), '--strictPort', '--host', '127.0.0.1'], {
  cwd: root,
  stdio: 'ignore',
})

try {
  await waitForServer(base)
  const { chromium } = loadPlaywright()
  const browser = await chromium.launch({
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
  })

  const shoot = async ({ url, width, height, scale, file, transparent }) => {
    const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: scale })
    page.on('pageerror', (e) => console.error('  erro na página:', e.message))
    await page.goto(url)
    await page.waitForFunction(() => window.__poseReady === true, null, { timeout: 90_000 })
    await page.waitForTimeout(120)
    await page.screenshot({ path: file, omitBackground: transparent })
    await page.close()
    console.log('  ✓', path.relative(root, file))
  }

  const only = typeof args.only === 'string' ? args.only.split(',') : null
  const poseDir = path.resolve(root, typeof args.out === 'string' ? args.out : 'public/poses')
  mkdirSync(poseDir, { recursive: true })
  console.log('poses →', path.relative(root, poseDir))
  for (const [name, state, t, gesture] of POSES) {
    if (only && !only.includes(name)) continue
    const q = new URLSearchParams({ 'render-pose': state, t: String(t) })
    if (gesture) q.set('gesture', gesture)
    await shoot({
      url: `${base}/?${q}`,
      width: 240,
      height: 240,
      scale: 2,
      file: path.join(poseDir, `${name}.png`),
      transparent: true,
    })
  }

  if (!args['no-icons'] && !only) {
    const iconDir = path.join(root, 'public/icons')
    mkdirSync(iconDir, { recursive: true })
    console.log('ícones →', path.relative(root, iconDir))
    for (const [file, size, zoom] of ICONS) {
      const q = new URLSearchParams({ 'render-pose': 'idle', t: '0.6', framing: 'icon', bg: '13302E', zoom: String(zoom) })
      await shoot({ url: `${base}/?${q}`, width: size, height: size, scale: 1, file: path.join(iconDir, file), transparent: false })
    }
  }
  await browser.close()
} finally {
  server.kill()
}
