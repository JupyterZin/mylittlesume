// Mascote 3D: RobotExpressive (CC0) recolorido em runtime (ADR-014) — bronze polido no corpo,
// pátina nos detalhes. Render controlado à mão (frameloop="never"): para quando a aba está
// oculta, limita a 30 fps fora de primeiro plano e mede o desempenho para cair para 2D.
import { Suspense, useEffect, useLayoutEffect, useMemo, useRef } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useGLTF } from '@react-three/drei'
import * as THREE from 'three'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'
import { CROSSFADE_SECONDS, type AnimSpec, type Morph } from './states'
import { SLOW_FPS } from './capability'

export const MODEL_URL = '/assets/talos.glb'

const BRONZE = '#B5762F'
const PATINA = '#4E8C80'
const VISOR = '#0E1B1A'
const MORPHS: Morph[] = ['Angry', 'Surprised', 'Sad']

export interface PoseRequest {
  /** tempo (s) dentro do clipe a congelar */
  time: number
  onRendered: () => void
}

export interface Mascot3DProps {
  spec: AnimSpec
  /** muda a cada nova reação, para repetir o mesmo clipe (ex.: dois "No" seguidos) */
  playKey: string | number
  active: boolean
  framing?: 'stage' | 'icon'
  /** multiplica a distância da câmera (ícones) */
  distance?: number
  pose?: PoseRequest
  onReady?: () => void
  onDone?: () => void
  onSlow?: () => void
}

export default function Mascot3D(props: Mascot3DProps) {
  const { pose } = props
  return (
    <Canvas
      frameloop="never"
      dpr={pose ? 2 : [1, 2]}
      gl={{ antialias: true, alpha: true, powerPreference: 'low-power', preserveDrawingBuffer: !!pose }}
      camera={{ fov: 28, near: 0.1, far: 100, position: [0, 2.6, 11] }}
      style={{ background: 'transparent' }}
      aria-hidden="true"
    >
      <CameraRig framing={props.framing ?? 'stage'} distance={props.distance ?? 1} />
      {!pose && <Driver active={props.active} onSlow={props.onSlow} />}
      <Lights />
      <Environment />
      <Floor />
      <Suspense fallback={null}>
        <Robot {...props} />
      </Suspense>
    </Canvas>
  )
}

// ------------------------------------------------------------------ laço de render
function Driver({ active, onSlow }: { active: boolean; onSlow?: () => void }) {
  const advance = useThree((s) => s.advance)
  const slowRef = useRef(onSlow)
  slowRef.current = onSlow
  useEffect(() => {
    if (!active) return
    let raf = 0
    let last = 0
    let start = 0
    let frames = 0
    let measured = false
    const tick = (t: number) => {
      raf = requestAnimationFrame(tick)
      if (document.hidden) return // aba oculta: nada de render
      const foreground = document.hasFocus()
      if (!foreground && t - last < 1000 / 30 - 1) return // fora de primeiro plano: 30 fps
      last = t
      advance(t / 1000)
      if (measured) return
      if (!foreground) {
        start = 0
        frames = 0
        return
      }
      if (!start) start = t + 1500 // ignora a compilação dos shaders
      if (t < start) return
      frames++
      if (t - start >= 4000) {
        measured = true
        const fps = (frames * 1000) / (t - start)
        if (fps < SLOW_FPS) slowRef.current?.()
      }
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [active, advance])
  return null
}

// ------------------------------------------------------------------ câmera, luz, chão
function CameraRig({ framing, distance }: { framing: 'stage' | 'icon'; distance: number }) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera
  const size = useThree((s) => s.size)
  useLayoutEffect(() => {
    const aspect = size.width / Math.max(1, size.height)
    const tan2 = 2 * Math.tan(THREE.MathUtils.degToRad((framing === 'icon' ? 24 : 26) / 2))
    if (framing === 'icon') {
      // cabeça e ombros, com folga para a máscara redonda dos ícones
      camera.fov = 24
      const dist = (3.9 / tan2) * distance
      camera.position.set(-dist * 0.13, 3.45, dist)
      camera.lookAt(0, 3.2, 0)
    } else {
      // o robô mede ~4,4; o salto (Jump) sobe ~1,6 — o canvas passa por baixo do cabeçalho
      camera.fov = 26
      const dist = Math.max(6.3 / tan2, 4.6 / aspect / tan2) * distance
      camera.position.set(-dist * 0.16, 3.1, dist)
      camera.lookAt(0, 2.9, 0)
    }
    camera.updateProjectionMatrix()
  }, [camera, size, framing, distance])
  return null
}

function Lights() {
  return (
    <>
      <hemisphereLight args={['#fff4e6', '#20403c', 1.0]} />
      <directionalLight position={[3.5, 7, 6]} intensity={2.4} color="#fff0dc" />
      <directionalLight position={[-5, 4, -4]} intensity={1.6} color="#8fd6c6" />
      <directionalLight position={[-3, 1.5, 6]} intensity={0.5} color="#ffffff" />
    </>
  )
}

function Environment() {
  const gl = useThree((s) => s.gl)
  const scene = useThree((s) => s.scene)
  useEffect(() => {
    const pmrem = new THREE.PMREMGenerator(gl)
    const room = new RoomEnvironment()
    const env = pmrem.fromScene(room, 0.04).texture
    scene.environment = env
    scene.environmentIntensity = 0.75
    return () => {
      scene.environment = null
      env.dispose()
      pmrem.dispose()
      room.dispose()
    }
  }, [gl, scene])
  return null
}

function Floor() {
  const texture = useMemo(() => {
    const c = document.createElement('canvas')
    c.width = c.height = 128
    const ctx = c.getContext('2d')
    if (ctx) {
      const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64)
      g.addColorStop(0, 'rgba(0,0,0,0.42)')
      g.addColorStop(0.55, 'rgba(0,0,0,0.16)')
      g.addColorStop(1, 'rgba(0,0,0,0)')
      ctx.fillStyle = g
      ctx.fillRect(0, 0, 128, 128)
    }
    return new THREE.CanvasTexture(c)
  }, [])
  useEffect(() => () => texture.dispose(), [texture])
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, 0]} renderOrder={-1}>
      <planeGeometry args={[3.6, 2.4]} />
      <meshBasicMaterial map={texture} transparent depthWrite={false} />
    </mesh>
  )
}

// ------------------------------------------------------------------ o robô
function recolor(material: THREE.Material): THREE.Material {
  const src = material as THREE.MeshStandardMaterial
  const m = src.clone()
  switch (src.name) {
    case 'Main': // corpo: bronze polido
      m.color.set(BRONZE)
      m.metalness = 0.92
      m.roughness = 0.3
      break
    case 'Grey': // detalhes: pátina verde-azulada
      m.color.set(PATINA)
      m.metalness = 0.4
      m.roughness = 0.46
      break
    case 'Black': // visor e olhos
      m.color.set(VISOR)
      m.metalness = 0.3
      m.roughness = 0.28
      break
  }
  return m
}

interface Rig {
  scene: THREE.Object3D
  mixer: THREE.AnimationMixer
  actions: Record<string, THREE.AnimationAction>
  head: THREE.Object3D | null
  faces: THREE.Mesh[]
}

function useRig(): Rig {
  const gltf = useGLTF(MODEL_URL, false, false)
  return useMemo(() => {
    const scene = gltf.scene
    const faces: THREE.Mesh[] = []
    let head: THREE.Object3D | null = null
    scene.traverse((o) => {
      const bone = o as THREE.Bone
      if (bone.isBone && bone.name === 'Head') head = bone
      const mesh = o as THREE.Mesh
      if (!mesh.isMesh) return
      mesh.frustumCulled = false
      const mats = mesh.material
      mesh.material = Array.isArray(mats) ? mats.map(recolor) : recolor(mats)
      if (mesh.morphTargetDictionary && mesh.morphTargetInfluences) faces.push(mesh)
    })
    const mixer = new THREE.AnimationMixer(scene)
    const actions: Record<string, THREE.AnimationAction> = {}
    for (const clip of gltf.animations) actions[clip.name] = mixer.clipAction(clip)
    return { scene, mixer, actions, head, faces }
  }, [gltf])
}

function setMorphs(faces: THREE.Mesh[], targets: Record<Morph, number>, blend: number): void {
  for (const f of faces) {
    const dict = f.morphTargetDictionary!
    const infl = f.morphTargetInfluences!
    for (const name of MORPHS) {
      const i = dict[name]
      if (i === undefined) continue
      infl[i] += (targets[name] - infl[i]) * blend
    }
  }
}

function Robot({ spec, playKey, pose, onReady, onDone }: Mascot3DProps) {
  const { scene, mixer, actions, head, faces } = useRig()
  const advance = useThree((s) => s.advance)
  const current = useRef<THREE.AnimationAction | null>(null)
  const morphTargets = useRef<Record<Morph, number>>({ Angry: 0, Surprised: 0, Sad: 0 })
  const tilt = useRef(0)
  const headBase = useRef(new THREE.Quaternion())
  const tiltApplied = useRef(false)
  const doneRef = useRef(onDone)
  doneRef.current = onDone

  // troca de animação com crossfade de 0,3 s
  useEffect(() => {
    const next = actions[spec.clip]
    if (!next) return
    const prev = current.current
    const prevClip = prev?.getClip().name
    // o mesmo clipe contínuo segue sem recomeçar (ex.: digitando → aguardando aprovação)
    const continuing = prev === next && spec.mode !== 'once' && (spec.mode === 'hold' || next.isRunning())
    if (!continuing) {
      next.reset()
      next.setLoop(spec.mode === 'loop' ? THREE.LoopRepeat : THREE.LoopOnce, spec.mode === 'loop' ? Infinity : 1)
      next.clampWhenFinished = spec.mode !== 'loop'
      // `Standing` é "levantar-se": só vale a transição se estava sentado; senão já começa de pé
      if (spec.clip === 'Standing' && prevClip !== 'Sitting') next.time = next.getClip().duration
      next.setEffectiveTimeScale(1).setEffectiveWeight(1)
      if (prev && prev !== next && !pose) {
        next.crossFadeFrom(prev, CROSSFADE_SECONDS, false)
      } else if (prev && prev !== next) {
        prev.stop()
      }
      next.play()
      current.current = next
    }
    const t: Record<Morph, number> = { Angry: 0, Surprised: 0, Sad: 0 }
    if (spec.expression) t[spec.expression.name] = spec.expression.weight
    morphTargets.current = t
    if (pose) {
      mixer.setTime(0)
      next.time = pose.time
      mixer.update(0)
      setMorphs(faces, t, 1)
      tilt.current = spec.headTilt ? 1 : 0
    }
  }, [spec, playKey, actions, mixer, faces, pose])

  useEffect(() => {
    const fn = (e: { action: THREE.AnimationAction }) => {
      if (e.action === current.current) doneRef.current?.()
    }
    mixer.addEventListener('finished', fn as never)
    return () => mixer.removeEventListener('finished', fn as never)
  }, [mixer])

  useEffect(() => {
    onReady?.()
    if (!pose) return
    // modo "pose" (scripts/render-poses.mjs): dois quadros e avisa que pode fotografar
    let raf = requestAnimationFrame(() => {
      advance(performance.now() / 1000)
      raf = requestAnimationFrame(() => {
        advance(performance.now() / 1000)
        pose.onRendered()
      })
    })
    return () => cancelAnimationFrame(raf)
  }, [])

  useEffect(() => () => void mixer.stopAllAction(), [mixer])

  useFrame((state, delta) => {
    const dt = pose ? 0 : Math.min(delta, 0.1)
    // a cabeça volta ao valor da animação antes de o mixer atualizar (sem acumular a inclinação)
    if (head && tiltApplied.current) head.quaternion.copy(headBase.current)
    mixer.update(dt)
    if (head) {
      headBase.current.copy(head.quaternion)
      if (!pose) tilt.current += ((spec.headTilt ? 1 : 0) - tilt.current) * Math.min(1, dt * 3)
      tiltApplied.current = tilt.current > 0.001
      if (tiltApplied.current) {
        const t = pose ? 1.2 : state.clock.elapsedTime
        const e = new THREE.Euler(0.1 * tilt.current, 0, (0.2 + Math.sin(t * 0.8) * 0.06) * tilt.current)
        head.quaternion.multiply(new THREE.Quaternion().setFromEuler(e))
      }
    }
    if (!pose) setMorphs(faces, morphTargets.current, Math.min(1, dt / CROSSFADE_SECONDS))
  })

  return <primitive object={scene} />
}

useGLTF.preload(MODEL_URL, false, false)
