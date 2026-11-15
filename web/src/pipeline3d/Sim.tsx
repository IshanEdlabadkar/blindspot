import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { RoundedBoxGeometry } from 'three/examples/jsm/geometries/RoundedBoxGeometry.js'
import burrowUrl from '../assets/burrow.svg'
import type { SimRun } from './run'

/* A clay desk diorama of one real question going through the pipeline.
   Laptop (front left) -> recorder (the wiretap) -> four library servers (back row), and back.
   Every number on screen comes from the SimRun built from that question's stream. */

const BG = 0xecebe7
const SEALED = 0x23408e
const SEALED_SOFT = 0x7088bd
const RED = 0xc5050c
const V = (x: number, y: number, z: number) => new THREE.Vector3(x, y, z)
const clamp01 = (x: number) => Math.min(1, Math.max(0, x))
const seg = (t: number, a: number, b: number) => clamp01((t - a) / (b - a))
const ease = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2)
const secs = (v?: number, d = 2) => (v === undefined ? 'not timed' : `${v.toFixed(d)} s`)
const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!))

type Tone = 'ink' | 'sealed' | 'red'
type Label = { at: THREE.Vector3; text?: string; html?: string; dx: number; dy: number; delay?: number; tone?: Tone }
type Beat = { key: string; word: string; dur: number; cam: THREE.Vector3; look: THREE.Vector3; labels: Label[] }

function clay(color: number) { return new THREE.MeshStandardMaterial({ color, roughness: 0.92, metalness: 0 }) }
function rbox(w: number, h: number, d: number, r: number, mat: THREE.Material) {
  const m = new THREE.Mesh(new RoundedBoxGeometry(w, h, d, 4, r), mat)
  m.castShadow = true; m.receiveShadow = true
  return m
}

/** A tube that draws itself along a curve, with an arrowhead at the end. */
function makeArc(curve: THREE.Curve<THREE.Vector3>, color: number, radius = 0.035) {
  const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.55 })
  const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, 96, radius, 10), mat)
  tube.castShadow = true
  const arrow = new THREE.Mesh(new THREE.ConeGeometry(radius * 2.8, radius * 7, 16), mat)
  arrow.position.copy(curve.getPointAt(1))
  arrow.quaternion.setFromUnitVectors(V(0, 1, 0), curve.getTangentAt(1).normalize())
  const total = tube.geometry.index!.count
  const set = (p: number) => {
    tube.visible = p > 0.001
    tube.geometry.setDrawRange(0, Math.floor((total * clamp01(p)) / 6) * 6)
    arrow.visible = p >= 0.999
  }
  set(0)
  return { tube, arrow, curve, set }
}

function bezier(a: THREE.Vector3, b: THREE.Vector3, lift: number, side = 0) {
  const flat = b.clone().sub(a).setY(0)
  const perp = V(-flat.z, 0, flat.x).normalize().multiplyScalar(side)
  return new THREE.CubicBezierCurve3(a, a.clone().add(V(0, lift, 0)).add(perp), b.clone().add(V(0, lift, 0)).add(perp), b)
}

function mulberry(seed: number) {
  return () => { seed |= 0; seed = (seed + 0x6d2b79f5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296 }
}

function wrap(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, max: number, lh: number, lines: number) {
  const words = text.split(/\s+/)
  let line = ''
  let n = 0
  for (const w of words) {
    const test = line ? `${line} ${w}` : w
    if (ctx.measureText(test).width > max && line) {
      ctx.fillText(line, x, y + n * lh); n++; line = w
      if (n >= lines) return
    } else line = test
  }
  if (line && n < lines) ctx.fillText(line, x, y + n * lh)
}

export default function Sim({ run, onClose, onRestart, inline }: { run: SimRun; onClose?: () => void; onRestart?: () => void; inline?: boolean }) {
  const host = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const overlay = useRef<HTMLDivElement>(null)
  const lines = useRef<SVGSVGElement>(null)
  const ctl = useRef({ go: (_: number) => {} })
  const scroller = useRef<HTMLDivElement>(null)
  const [beat, setBeat] = useState(0)
  const [count, setCount] = useState(1)
  const [caption, setCaption] = useState('')
  const [steps, setSteps] = useState<{ key: string; word: string; explain: string; side: 'left' | 'right' }[]>([])
  const [ended, setEnded] = useState(false)

  useEffect(() => {
    const canvas = canvasRef.current!, box = host.current!, layer = overlay.current!, svg = lines.current!
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, inline ? 1.5 : 2))
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = THREE.PCFSoftShadowMap
    renderer.outputColorSpace = THREE.SRGBColorSpace
    const scene = new THREE.Scene()
    scene.background = new THREE.Color(BG)
    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 200)

    scene.add(new THREE.HemisphereLight(0xffffff, 0xcfc9bf, 1.7))
    const sun = new THREE.DirectionalLight(0xffffff, 1.5)
    sun.position.set(-6, 14, 9)
    sun.castShadow = true
    sun.shadow.mapSize.set(2048, 2048)
    Object.assign(sun.shadow.camera, { left: -12, right: 12, top: 12, bottom: -12, near: 1, far: 40 })
    sun.shadow.bias = -0.0004
    scene.add(sun)

    // Desk, floating like the DESK video's slab, with a sage mat.
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(80, 80), new THREE.ShadowMaterial({ opacity: 0.1 }))
    floor.rotation.x = -Math.PI / 2; floor.position.y = -1.8; floor.receiveShadow = true
    scene.add(floor)
    const desk = rbox(15.5, 0.45, 9, 0.18, clay(0xe6e4df)); desk.position.y = -0.225; scene.add(desk)
    const mat = rbox(12.4, 0.04, 6.6, 0.02, clay(0xdce4d7)); mat.position.y = 0.02; scene.add(mat)

    // Laptop: the only place the question is readable.
    const laptop = new THREE.Group(); laptop.position.set(-4.4, 0.04, 2.3); laptop.rotation.y = 0.42; scene.add(laptop)
    const shell = clay(0xd9d8d3)
    const base = rbox(2.8, 0.12, 1.9, 0.05, shell); base.position.y = 0.06; laptop.add(base)
    const keys = rbox(2.4, 0.015, 1.0, 0.006, clay(0xcdccc7)); keys.position.set(0, 0.125, 0.1); laptop.add(keys)
    const hinge = new THREE.Group(); hinge.position.set(0, 0.12, -0.93); hinge.rotation.x = -0.2; laptop.add(hinge)
    const lid = rbox(2.8, 1.85, 0.09, 0.04, shell); lid.position.y = 0.925; hinge.add(lid)
    const screenCanvas = document.createElement('canvas'); screenCanvas.width = 1024; screenCanvas.height = 640
    const sctx = screenCanvas.getContext('2d')!
    const screenTex = new THREE.CanvasTexture(screenCanvas); screenTex.colorSpace = THREE.SRGBColorSpace; screenTex.anisotropy = 8
    const display = new THREE.Mesh(new THREE.PlaneGeometry(2.56, 1.6), new THREE.MeshBasicMaterial({ map: screenTex, toneMapped: false }))
    display.position.set(0, 0.95, 0.05); hinge.add(display)

    let screenKey = ''
    const drawScreen = (mode: 'question' | 'answer', n: number) => {
      const key = `${mode}:${n}`
      if (key === screenKey) return
      screenKey = key
      sctx.fillStyle = '#FFFDF8'; sctx.fillRect(0, 0, 1024, 640)
      sctx.fillStyle = '#C5050C'; sctx.fillRect(0, 92, 1024, 5)
      sctx.fillStyle = '#1E1C1A'; sctx.font = '900 40px "Red Hat Display", sans-serif'
      sctx.fillText(mode === 'question' ? 'Call slip' : 'Answer', 56, 66)
      sctx.fillStyle = '#57524B'; sctx.font = '400 30px "Courier Prime", monospace'
      const tag = mode === 'question' ? 'on this laptop' : `${run.sources} source${run.sources === 1 ? '' : 's'}`
      sctx.fillText(tag, 1024 - 56 - sctx.measureText(tag).width, 66)
      sctx.fillStyle = '#1E1C1A'
      if (mode === 'question') {
        sctx.font = '700 46px "Courier Prime", monospace'
        wrap(sctx, run.question.slice(0, n) + (n < run.question.length ? '_' : ''), 56, 180, 912, 62, 7)
      } else {
        sctx.font = '400 36px "Courier Prime", monospace'
        wrap(sctx, run.answer.slice(0, n), 56, 160, 912, 50, 7)
        sctx.fillStyle = '#57524B'; sctx.font = '700 28px "Courier Prime", monospace'
        wrap(sctx, run.citation, 56, 596, 912, 34, 1)
      }
      screenTex.needsUpdate = true
    }
    drawScreen('question', 0)
    void document.fonts.ready.then(() => { screenKey = ''; drawScreen('question', 0) })

    // Burrow, as a flat card standee (C's art, unchanged).
    const standee = new THREE.Group(); standee.position.set(-6.5, 0.04, 3.5); standee.rotation.y = 0.75; scene.add(standee)
    const card = rbox(1.35, 1.42, 0.05, 0.04, clay(0xfffdf8)); card.position.y = 0.82; standee.add(card)
    const foot = rbox(0.6, 0.06, 0.45, 0.02, clay(0xd9d8d3)); foot.position.y = 0.03; standee.add(foot)
    const burrowCanvas = document.createElement('canvas'); burrowCanvas.width = 512; burrowCanvas.height = 528
    const burrowTex = new THREE.CanvasTexture(burrowCanvas); burrowTex.colorSpace = THREE.SRGBColorSpace
    const img = new Image()
    img.onload = () => { burrowCanvas.getContext('2d')!.drawImage(img, 0, 0, 512, 528); burrowTex.needsUpdate = true }
    img.src = burrowUrl
    const pic = new THREE.Mesh(new THREE.PlaneGeometry(1.2, 1.24), new THREE.MeshBasicMaterial({ map: burrowTex, transparent: true, toneMapped: false }))
    pic.position.set(0, 0.82, 0.03); standee.add(pic)

    // The recorder (wiretap) that sits between the laptop and everything else.
    const R = V(-1.7, 0.04, 1.0)
    const recorder = new THREE.Group(); recorder.position.copy(R); scene.add(recorder)
    const rb = rbox(0.95, 0.5, 0.72, 0.1, clay(0xd3d1cb)); rb.position.y = 0.25; recorder.add(rb)
    const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.12, 28), clay(0x8e9aa6)); lens.rotation.x = Math.PI / 2; lens.position.set(0, 0.27, 0.38); recorder.add(lens)
    const led = new THREE.Mesh(new THREE.SphereGeometry(0.05, 16, 12), new THREE.MeshBasicMaterial({ color: RED })); led.position.set(0.32, 0.52, 0.2); recorder.add(led)
    const recTop = R.clone().add(V(0, 0.62, 0))

    // Four library servers: stacks of books on plinths.
    const xs = [-4.6, -1.55, 1.55, 4.6]
    const bookColors = [0xc9b49a, 0xa8b6c4, 0xb7c3a6, 0xd3b2a6, 0xbfb8cc, 0xd8cba5]
    const bookMats: THREE.MeshStandardMaterial[] = []
    const libTops = run.libraries.map((_, i) => {
      const x = xs[i % xs.length] + (i >= xs.length ? 0.8 : 0)
      const g = new THREE.Group(); g.position.set(x, 0.04, -2.55); scene.add(g)
      const plinth = new THREE.Mesh(new THREE.CylinderGeometry(0.88, 0.98, 0.28, 44), clay(0xdcdad4)); plinth.position.y = 0.14
      plinth.castShadow = true; plinth.receiveShadow = true; g.add(plinth)
      for (let k = 0; k < 6; k++) {
        const m = clay(bookColors[(k + i) % bookColors.length]); m.emissive = new THREE.Color(0xffffff); m.emissiveIntensity = 0; bookMats.push(m)
        const b = rbox(1.2 - k * 0.06, 0.2, 0.82 - k * 0.02, 0.03, m)
        b.position.y = 0.39 + k * 0.215; b.rotation.y = (k % 2 ? 1 : -1) * 0.06 * (k + 1) * 0.5; g.add(b)
      }
      return V(x, 1.85, -2.55)
    })
    const libMid = libTops.reduce((a, v) => a.add(v), V(0, 0, 0)).divideScalar(Math.max(libTops.length, 1))

    // The normal AI service, shown only for the comparison.
    const N = V(5.0, 0.04, 2.5)
    const service = new THREE.Group(); service.position.copy(N); service.scale.setScalar(0.001); scene.add(service)
    const tower = rbox(0.95, 1.65, 0.95, 0.12, clay(0xebcdc8)); tower.position.y = 0.825; service.add(tower)
    const stripe = rbox(0.97, 0.09, 0.97, 0.02, clay(RED)); stripe.position.y = 1.32; service.add(stripe)
    for (let k = 0; k < 3; k++) { const s = rbox(0.6, 0.04, 0.02, 0.01, clay(0xb9a29d)); s.position.set(0, 0.5 + k * 0.2, 0.48); service.add(s) }
    const svcTop = N.clone().add(V(0, 1.8, 0))

    // Paths.
    scene.updateMatrixWorld(true)
    const laptopOut = laptop.localToWorld(V(1.25, 0.25, -0.35))
    const screenAnchor = display.getWorldPosition(V(0, 0, 0))
    const arcs = {
      toRec: makeArc(bezier(laptopOut, recTop, 0.9), SEALED),
      out: libTops.map((t) => makeArc(bezier(recTop, t, 2.4), SEALED, 0.026)),
      back: libTops.map((t) => makeArc(bezier(t, recTop, 1.3, 0.45), SEALED_SOFT, 0.028)),
      home: makeArc(bezier(recTop, laptopOut, 0.6, 0.3), SEALED_SOFT, 0.028),
      plain: makeArc(bezier(recTop, svcTop, 1.7, -0.3), RED),
    }
    for (const a of [arcs.toRec, ...arcs.out, ...arcs.back, arcs.home, arcs.plain]) scene.add(a.tube, a.arrow)

    // Moving things.
    const sealedPacket = rbox(0.34, 0.34, 0.34, 0.07, clay(SEALED)); scene.add(sealedPacket)
    const outPackets = libTops.map(() => { const p = rbox(0.24, 0.24, 0.24, 0.05, clay(SEALED)); scene.add(p); return p })
    const scorePackets = libTops.map(() => { const p = rbox(0.3, 0.16, 0.3, 0.05, clay(SEALED)); scene.add(p); return p })
    const pirPackets = libTops.map(() => { const p = rbox(0.2, 0.2, 0.2, 0.05, clay(0x3b5aa8)); scene.add(p); return p })
    const perLib = Math.max(...run.libraries.map((l) => l.fetched), 0)
    const backInst = new THREE.InstancedMesh(new RoundedBoxGeometry(0.13, 0.13, 0.13, 2, 0.03), clay(SEALED_SOFT), Math.max(libTops.length * perLib, 1))
    backInst.castShadow = true; scene.add(backInst)
    const redPacket = rbox(0.28, 0.28, 0.28, 0.06, clay(RED)); scene.add(redPacket)

    // The question as 384 numbers: a ribbon of bars above the laptop (heights illustrative, count real).
    const bars = new THREE.InstancedMesh(new THREE.BoxGeometry(0.05, 1, 0.05), clay(0x8fa0b8), 384)
    bars.castShadow = true
    const barsAt = laptop.localToWorld(V(0, 2.25, -0.5))
    const rand = mulberry([...run.question].reduce((h, c) => (h * 31 + c.charCodeAt(0)) | 0, 7))
    const heights = Array.from({ length: 384 }, () => 0.12 + 0.95 * Math.abs(rand() * 2 - 1) ** 1.6)
    scene.add(bars)
    const dummy = new THREE.Object3D()

    // The recorder's scanning cone.
    const coneDir = libMid.clone().sub(recTop).normalize()
    const cone = new THREE.Group(); cone.position.copy(recTop)
    cone.quaternion.setFromUnitVectors(V(0, -1, 0), coneDir)
    const coneGeo = new THREE.ConeGeometry(1.5, 3.6, 36, 1, true); coneGeo.translate(0, -1.8, 0) // apex at the lens, opening toward the libraries
    const coneFill = new THREE.Mesh(coneGeo, new THREE.MeshBasicMaterial({ color: SEALED, transparent: true, opacity: 0.07, side: THREE.DoubleSide, depthWrite: false }))
    const coneWire = new THREE.Mesh(coneGeo, new THREE.MeshBasicMaterial({ color: SEALED, wireframe: true, transparent: true, opacity: 0.3 }))
    cone.add(coneFill, coneWire); scene.add(cone)

    // Beats.
    const s = run.stages
    const total = run.libraries.reduce((n, l) => n + l.passages, 0)
    const fetchedAll = run.libraries.reduce((n, l) => n + l.fetched, 0)
    const kb = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)} MB` : `${(n / 1000).toFixed(1)} KB`)
    const scoresBack = run.libraries.reduce((n, l) => n + l.scoreDown, 0)
    const pirUp = run.libraries.reduce((n, l) => n + l.fetchUp, 0), pirDown = run.libraries.reduce((n, l) => n + l.fetchDown, 0)
    const pir = run.fetchMode === 'pir'
    const lapLook = laptop.localToWorld(V(0, 1.0, -0.4))
    const lapCam = laptop.localToWorld(V(2.6, 2.3, 4.2))
    const side = (i: number) => (i < run.libraries.length / 2 ? -30 : 30)
    const rise = (i: number, base = 70) => -(base + (i % 2) * 42)
    const beats: Beat[] = [
      { key: 'typed', word: 'Typed.', dur: 4.6, cam: lapCam, look: lapLook,
        labels: [{ at: screenAnchor, text: 'readable only on this laptop', dx: -30, dy: -250 }] },
      { key: 'numbers', word: 'Numbers.', dur: 4.6, cam: laptop.localToWorld(V(3.4, 3.6, 5.2)), look: laptop.localToWorld(V(0, 1.9, -0.4)),
        labels: [{ at: barsAt, text: 'turned into 384 numbers here (bge-small-en-v1.5)', dx: 90, dy: -120 },
          { at: barsAt, text: `took ${secs(s.embedding)}`, dx: 90, dy: -92, delay: 0.9 }] },
      { key: 'sealed', word: 'Sealed.', dur: 4.6, cam: laptop.localToWorld(V(3.0, 3.2, 4.6)), look: laptop.localToWorld(V(0, 1.8, -0.4)),
        labels: [{ at: barsAt, text: 'locked with a key made for this question only', dx: 90, dy: -120, delay: 1.0, tone: 'sealed' },
          { at: barsAt, text: `sealed in ${secs(s.encrypting)}`, dx: 90, dy: -92, delay: 1.6, tone: 'sealed' }] },
      { key: 'everywhere', word: 'Everywhere.', dur: 6.2, cam: V(8.5, 8.2, 10.5), look: V(-0.4, 0.6, -0.6),
        labels: [
          { at: recTop, text: 'recorder: keeps every byte that leaves', dx: -40, dy: 120, delay: 0.4 },
          ...run.libraries.map((l, i) => ({ at: libTops[i], text: `${l.name}, ${l.passages.toLocaleString()} passages`, dx: side(i), dy: rise(i, 80), delay: 1.2 + i * 0.25 })),
          { at: arcs.out[0].curve.getPointAt(0.5), text: `the same sealed question, ${run.libraries[0]?.sent ?? ''} to each library`, dx: 60, dy: 150, delay: 2.4, tone: 'sealed' as Tone },
        ] },
      { key: 'blind', word: 'Blind.', dur: 6.6, cam: V(0.4, 7.4, 8.8), look: V(0, 1.0, -2.2),
        labels: [
          ...run.libraries.map((l, i) => ({ at: libTops[i], text: `scored all ${l.passages.toLocaleString()}, can't read it${l.scoreDown ? `, ${kb(l.scoreDown)} of locked scores back` : ''}`, dx: side(i), dy: rise(i), delay: 0.3 + i * 0.2 })),
          { at: libMid.clone().add(V(0, -1.6, 1.2)), text: `${total.toLocaleString()} passages scored in ${secs(s.scoring)}`, dx: -150, dy: 90, delay: 1.4 },
          { at: recTop, text: `every score comes back still locked${scoresBack ? `, ${kb(scoresBack)} in all` : ''}`, dx: 40, dy: 130, delay: 3.0, tone: 'sealed' as Tone },
        ] },
      { key: 'ten', word: pir ? 'Private fetch.' : 'Ten.', dur: 7.6, cam: V(6.5, 7.0, 9.0), look: V(-1.2, 0.6, -0.4),
        labels: pir ? [
          { at: recTop, text: `real PIR: ${perLib} sealed requests to each library, ${kb(pirUp)} out`, dx: 40, dy: 130, delay: 0.4, tone: 'sealed' },
          { at: libMid, text: `exactly ${perLib} passages back from every library, ${fetchedAll} in all (${kb(pirDown)})`, dx: -150, dy: -150, delay: 2.4, tone: 'sealed' },
          { at: libMid, text: 'no library learns which passages it sent', dx: -150, dy: -122, delay: 3.2 },
        ] : [
          { at: libMid, text: `exactly ${perLib} from every library, ${fetchedAll} in all`, dx: -150, dy: -150, delay: 0.6, tone: 'sealed' },
          { at: libMid, text: 'read from a full copy, so no library learns which ones', dx: -150, dy: -122, delay: 1.4 },
        ] },
      { key: 'written', word: 'Written.', dur: 5.6, cam: lapCam, look: lapLook,
        labels: [
          { at: screenAnchor, text: `reranked here, best ${Math.min(5, run.sources) || 5} kept as sources`, dx: -30, dy: -250, delay: 0.3 },
          { at: screenAnchor, text: `written here by llama3.2:3b in ${secs(s.answering, 1)}`, dx: -30, dy: -222, delay: 1.0 },
          { at: screenAnchor, text: 'sentences without a source are removed', dx: -30, dy: -194, delay: 1.7 },
        ] },
      { key: 'proven', word: 'Proven.', dur: 6.0, cam: V(3.2, 6.8, 10.0), look: V(-0.8, 0.9, -1.0),
        labels: run.recording ? [
          { at: recTop, text: `searched every byte for: ${run.words.join(', ')}`, dx: -60, dy: 130, delay: 0.4 },
          ...run.libraries.map((l, i) => ({ at: libTops[i], text: l.found === null ? 'not recorded' : `${l.found} of ${l.words} words found`, dx: side(i), dy: rise(i), delay: 1.2 + i * 0.25, tone: 'sealed' as Tone })),
          ...(run.chance ? [{ at: recTop, text: `odds of one showing up by luck: about ${run.chance}`, dx: -60, dy: 158, delay: 2.4 }] : []),
        ] : [{ at: recTop, text: 'recording was off for this question', dx: -60, dy: 130 }] },
    ]
    if (run.plain) {
      const p = run.plain
      const hl = (t: string) => {
        let out = esc(t)
        for (const w of run.words) out = out.replace(new RegExp(`\\b(${w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})\\b`, 'gi'), '<mark>$1</mark>')
        return out
      }
      beats.push({ key: 'compared', word: 'Compared.', dur: 7.0, cam: V(8.2, 5.6, 9.2), look: V(1.6, 0.8, 0.8),
        labels: [
          { at: svcTop, text: `a normal AI service, sent as plain text${p.bytes ? ` (${p.bytes})` : ''}`, dx: -320, dy: -110, delay: 0.6, tone: 'red' },
          { at: svcTop, text: `${p.found} of ${p.words} words found, kept on file`, dx: -320, dy: -82, delay: 1.6, tone: 'red' },
          ...(p.log ? [{ at: svcTop, dx: 40, dy: -40, delay: 2.4, html:
            `<b>its log</b><br>time&nbsp;&nbsp;${esc(p.log.time)}<br>from&nbsp;&nbsp;${esc(p.log.from)}<br>asked&nbsp;“${hl(p.log.asked)}”` }] : []),
        ] })
    }
    beats.push(
      { key: 'honest', word: 'Honest.', dur: 5.0, cam: V(0, 9.5, 11.5), look: V(0, 0.4, -0.8),
        labels: [{ at: libMid, text: 'libraries still see that you asked, when, from where, and how many bytes', dx: -300, dy: -120, delay: 0.4 }] },
      { key: 'end', word: '', dur: 6.0, cam: V(0, 7.5, 21), look: V(0, 3.2, 0), labels: [] },
    )
    setCount(beats.length)
    // What the presenter says at each step, with this question's real numbers.
    const names = run.libraries.map((l) => l.name)
    const list = names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0] ?? 'the library'
    const found = run.libraries.map((l) => l.found ?? 0)
    const big = run.libraries[0]
    const EXPLAIN: Record<string, string> = {
      typed: `You type a question. Right now it exists in exactly one place: this laptop. The text itself will never leave it.`,
      numbers: `An embedding model on the laptop turns the question into 384 numbers that capture its meaning. These numbers, not your words, are what gets searched. This took ${secs(s.embedding)}.`,
      sealed: `The 384 numbers go into a locked box: they are encrypted with a fresh one-time key made for this question only. The key stays on the laptop. Locking took ${secs(s.encrypting)}.`,
      everywhere: `The same locked box goes to all ${names.length} libraries in parallel (${list}), ${run.libraries[0]?.sent ?? ''} each, every time. Sending it only to the "right" library would give away the topic. A recorder on the network keeps a copy of every byte that leaves.`,
      blind: `Each library combines the locked numbers with its own table of passage embeddings${big ? ` (${big.passages.toLocaleString()} rows for ${big.name})` : ''} and gets one locked relevance score per passage, without seeing inside. It scores every passage the same way, so it can't tell which ones scored high. All ${total.toLocaleString()} scores come back still locked${scoresBack ? `, ${kb(scoresBack)} in all` : ''}. Only the laptop has the key.`,
      ten: pir
        ? `The laptop unlocks the scores and picks the ${perLib} best from each library. Then it fetches them with real PIR (private information retrieval): ${perLib} requests to each library in a form the library can't read, ${kb(pirUp)} out and ${kb(pirDown)} back. It is always exactly ${perLib} per library, ${fetchedAll} in all, even if fewer were relevant, so neither the count nor the request gives anything away. Fetching took ${secs(s.fetching)}.`
        : `The laptop unlocks the scores and picks the ${perLib} best from each library. It reads them from a full copy of each library's passages downloaded earlier, so no library learns which ones were used. Always exactly ${perLib} per library, ${fetchedAll} in all.`,
      written: `Local models write the answer. A reranker on the laptop reorders all ${fetchedAll} passages and keeps the best ${Math.min(5, run.sources) || 5}, Llama writes the answer from them, and a checker removes any sentence the sources don't support. A 988 or 911 notice is added when a question needs one. Writing took ${secs(s.answering, 1)}.`,
      proven: run.recording
        ? `Now the check. The recorder searches every byte that left this laptop for the words in your question: ${run.words.join(', ')}. Words found at the libraries: ${found.join(', ')}.${run.chance ? ` The odds of one showing up by luck are about ${run.chance}.` : ''}`
        : `Traffic recording was off for this question, so there is nothing to search this time.`,
      compared: run.plain
        ? `For contrast, the same question went to a normal AI service as plain text. The recorder found ${run.plain.found} of ${run.plain.words} of your words, and the service wrote your question, your address and the time into its own log.`
        : '',
      honest: `What the libraries still see: that a question was asked, when, from which address, and the sizes of what was sent. Hiding the words doesn't hide the fact that someone asked.`,
      end: `Blindspot. Four libraries answered, and none of them could read the question.`,
    }
    const RIGHT = new Set(['typed', 'numbers', 'sealed', 'written'])
    setSteps(beats.map((b) => ({ key: b.key, word: b.word || 'Blindspot', explain: EXPLAIN[b.key] ?? '', side: RIGHT.has(b.key) ? 'right' : 'left' })))
    const idx = (k: string) => beats.findIndex((b) => b.key === k)
    const B = { typed: idx('typed'), numbers: idx('numbers'), sealed: idx('sealed'), everywhere: idx('everywhere'), blind: idx('blind'),
      ten: idx('ten'), written: idx('written'), proven: idx('proven'), compared: idx('compared') }

    // Apply the scene state for beat b at local time t. Pure: going back works.
    const apply = (b: number, t: number) => {
      const T = reduce ? 99 : t
      // screen
      if (b <= B.typed) drawScreen('question', Math.floor(seg(T, 0.5, 0.5 + run.question.length / 26) * run.question.length))
      else if (b < B.written) drawScreen('question', run.question.length)
      else if (b === B.written) drawScreen('answer', Math.floor(seg(T, 0.6, 0.6 + run.answer.length / 70) * run.answer.length))
      else drawScreen('answer', run.answer.length)
      // bars
      const grow = b === B.numbers ? ease(seg(T, 0.3, 1.8)) : b === B.sealed ? 1 : 0
      const fold = b === B.sealed ? ease(seg(T, 0.3, 1.4)) : 0
      bars.visible = grow > 0 && fold < 1
      if (bars.visible) {
        for (let i = 0; i < 384; i++) {
          const col = i % 32, row = Math.floor(i / 32)
          const x = (col - 15.5) * 0.075 * (1 - fold), z = (row - 5.5) * 0.05 * (1 - fold)
          dummy.position.set(barsAt.x + x, barsAt.y + (heights[i] * grow * (1 - fold)) / 2, barsAt.z + z)
          dummy.scale.set(1 - fold * 0.8, Math.max(heights[i] * grow * (1 - fold), 0.001), 1 - fold * 0.8)
          dummy.updateMatrix(); bars.setMatrixAt(i, dummy.matrix)
        }
        bars.instanceMatrix.needsUpdate = true
      }
      // sealed packet
      sealedPacket.visible = (b === B.sealed && T > 0.9) || (b === B.everywhere && T < 1.0)
      if (b === B.sealed) { sealedPacket.position.copy(barsAt).add(V(0, 0.2, 0)); sealedPacket.scale.setScalar(ease(seg(T, 0.9, 1.6)) || 0.001) }
      if (b === B.everywhere) {
        const u = ease(seg(T, 0, 1.0)); sealedPacket.scale.setScalar(1)
        sealedPacket.position.copy(u < 0.25 ? barsAt.clone().lerp(laptopOut, u / 0.25) : arcs.toRec.curve.getPointAt((u - 0.25) / 0.75))
      }
      // outbound arcs and packets
      arcs.toRec.set(b < B.everywhere ? 0 : b === B.everywhere ? seg(T, 0.2, 1.0) : 1)
      arcs.out.forEach((a, i) => {
        a.set(b < B.everywhere ? 0 : b === B.everywhere ? seg(T, 1.0, 2.2) : 1)
        const u = b === B.everywhere ? ease(seg(T, 1.1, 2.8)) : 0
        outPackets[i].visible = u > 0 && u < 1
        if (outPackets[i].visible) outPackets[i].position.copy(a.curve.getPointAt(u))
      })
      // libraries scoring
      const glow = b === B.blind ? 0.22 * (0.5 + 0.5 * Math.sin(t * 5)) * seg(T, 0.2, 0.8) : 0
      for (const m of bookMats) m.emissiveIntensity = glow
      // the locked scores travel back (Blind), then the return path stays
      arcs.back.forEach((a) => a.set(b < B.blind ? 0 : b === B.blind ? seg(T, 2.2, 3.0) : 1))
      arcs.home.set(b < B.blind ? 0 : b === B.blind ? seg(T, 2.8, 3.4) : 1)
      scorePackets.forEach((p, i) => {
        const u = b === B.blind && !reduce ? ease(seg(T, 3.0 + i * 0.1, 5.4 + i * 0.1)) : 0
        p.visible = u > 0 && u < 1
        if (p.visible) p.position.copy(u < 0.78 ? arcs.back[i].curve.getPointAt(u / 0.78) : arcs.home.curve.getPointAt((u - 0.78) / 0.22))
      })
      // private fetch: sealed PIR requests go out first
      pirPackets.forEach((p, i) => {
        const u = b === B.ten && pir && !reduce ? ease(seg(T, 0.3 + i * 0.08, 2.0 + i * 0.08)) : 0
        p.visible = u > 0 && u < 1
        if (p.visible) p.position.copy(arcs.out[i].curve.getPointAt(u))
      })
      // then exactly the fetched count comes back from every library
      let k = 0
      run.libraries.forEach((l, i) => {
        for (let j = 0; j < perLib; j++, k++) {
          const start = (pir ? 2.2 : 1.0) + j * 0.24 + i * 0.06
          const u = b === B.ten && !reduce ? seg(T, start, start + 2.0) : 0
          const show = j < l.fetched && u > 0 && u < 1
          if (show) dummy.position.copy(u < 0.78 ? arcs.back[i].curve.getPointAt(u / 0.78) : arcs.home.curve.getPointAt((u - 0.78) / 0.22))
          dummy.scale.setScalar(show ? 1 : 0.0001); dummy.updateMatrix(); backInst.setMatrixAt(k, dummy.matrix)
        }
      })
      backInst.instanceMatrix.needsUpdate = true
      // scanning cone
      cone.visible = b === B.proven && run.recording
      if (cone.visible) {
        const o = seg(T, 0.2, 0.9)
        ;(coneFill.material as THREE.MeshBasicMaterial).opacity = 0.07 * o
        ;(coneWire.material as THREE.MeshBasicMaterial).opacity = 0.3 * o
        cone.rotation.set(0, 0, 0)
        cone.quaternion.setFromUnitVectors(V(0, -1, 0), coneDir)
        cone.rotateOnAxis(V(0, 0, 1), Math.sin(t * 1.4) * 0.35)
      }
      // normal service
      const svc = B.compared < 0 ? 0 : b < B.compared ? 0 : b === B.compared ? ease(seg(T, 0, 0.9)) : 1
      service.scale.setScalar(Math.max(svc, 0.001))
      arcs.plain.set(B.compared < 0 || b < B.compared ? 0 : b === B.compared ? seg(T, 0.9, 2.0) : 1)
      const ru = b === B.compared ? ease(seg(T, 1.0, 2.6)) : 0
      redPacket.visible = ru > 0 && ru < 1
      if (redPacket.visible) redPacket.position.copy(arcs.plain.curve.getPointAt(ru))
    }

    // Labels, drawn in HTML over the canvas and pinned to 3D points.
    type LiveLabel = Label & { el: HTMLDivElement; line: SVGLineElement; dot: SVGCircleElement }
    let live: LiveLabel[] = []
    const buildLabels = (list: Label[]) => {
      layer.querySelectorAll('.sim-label').forEach((n) => n.remove())
      svg.innerHTML = ''
      live = list.map((l) => {
        const el = document.createElement('div')
        el.className = `sim-label sim-${l.tone ?? 'ink'}${l.html ? ' sim-card' : ''}`
        if (l.html) el.innerHTML = l.html
        layer.appendChild(el)
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line')
        const dot = document.createElementNS('http://www.w3.org/2000/svg', 'circle')
        dot.setAttribute('r', '3.5')
        svg.append(line, dot)
        return { ...l, el, line, dot }
      })
    }
    const tmp = V(0, 0, 0)
    const drawLabels = (t: number, w: number, h: number) => {
      const placed: { x0: number; x1: number; y0: number; y1: number }[] = []
      const origin = box.getBoundingClientRect()
      box.parentElement?.parentElement?.querySelectorAll<HTMLElement>('.sim-step').forEach((c) => {
        const r = c.getBoundingClientRect()
        if (r.bottom > origin.top && r.top < origin.bottom) placed.push({ x0: r.left - origin.left - 10, x1: r.right - origin.left + 10, y0: r.top - origin.top - 10, y1: r.bottom - origin.top + 10 })
      })
      for (const l of live) {
        const on = (reduce ? 99 : t) - (l.delay ?? 0)
        if (!l.html) {
          // Set the text first so the label is measured at its real width.
          const n = Math.floor(on * 48)
          const txt = l.text ?? ''
          l.el.textContent = `• ${txt.slice(0, Math.max(0, n))}`
          l.el.dataset.typing = n < txt.length ? '1' : ''
        }
        tmp.copy(l.at).project(camera)
        const ax = (tmp.x * 0.5 + 0.5) * w, ay = (-tmp.y * 0.5 + 0.5) * h
        const narrow = w < 640
        const lw = Math.min(Math.max(l.el.offsetWidth, l.html ? 0 : (l.text?.length ?? 0) * (narrow ? 7.3 : 8.6)), w - 24), lh = Math.max(l.el.offsetHeight, 22)
        const left = l.dx < 0 && !l.html
        const raw = ax + l.dx * (narrow ? 0.4 : 1)
        const lx = left ? Math.min(Math.max(raw, lw + 12), w - 12) : Math.min(Math.max(raw, 12), w - lw - 12)
        let ly = Math.min(Math.max(ay + l.dy * (narrow ? 0.6 : 1), 56 + lh / 2), h - 64 - lh / 2)
        // Step up past any label already placed this frame, so labels never sit on each other.
        const x0 = left ? lx - lw : lx, x1 = left ? lx : lx + lw
        const top = 56 + lh / 2, bottom = h - 64 - lh / 2
        const hitAt = (y: number) => placed.find((r) => x0 < r.x1 + 8 && x1 > r.x0 - 8 && y - lh / 2 < r.y1 + 4 && y + lh / 2 > r.y0 - 4)
        const settle = (y: number, dir: -1 | 1) => {
          for (let guard = 0; guard < 14; guard++) {
            const hit = hitAt(y)
            if (!hit) return y
            y = dir < 0 ? hit.y0 - 4 - lh / 2 : hit.y1 + 4 + lh / 2
            if (y < top || y > bottom) return null
          }
          return null
        }
        ly = settle(ly, -1) ?? settle(ly, 1) ?? ly
        if (on > 0) placed.push({ x0, x1, y0: ly - lh / 2, y1: ly + lh / 2 })
        const visible = on > 0 && tmp.z < 1
        l.el.style.opacity = visible ? '1' : '0'
        l.el.style.transform = `translate(${lx}px, ${ly}px) translate(${left ? '-100%' : '0'}, -50%)`
        for (const [k, v] of [['x1', ax], ['y1', ay], ['x2', lx], ['y2', ly]] as const) l.line.setAttribute(k, String(v))
        l.dot.setAttribute('cx', String(ax)); l.dot.setAttribute('cy', String(ay))
        const o = visible ? String(Math.min(1, on * 3)) : '0'
        l.line.style.opacity = o; l.dot.style.opacity = o
      }
    }

    // Scroll drives everything: which step is on screen, and how far through it you are.
    // Each step owns STEP of scroll; the camera moves in the first 30%, the step plays out by 80%, then holds.
    const scrollEl = scroller.current!
    // Inline, the page itself scrolls: progress is how far the top of this block has gone above the viewport.
    const progress = () => (inline ? Math.max(0, -scrollEl.getBoundingClientRect().top) : scrollEl.scrollTop)
    const scrollTo = (top: number) => {
      const behavior = reduce ? 'auto' : 'smooth'
      if (inline) window.scrollTo({ top: window.scrollY + scrollEl.getBoundingClientRect().top + top, behavior })
      else scrollEl.scrollTo({ top, behavior })
    }
    let onScreen = !inline
    const io = new IntersectionObserver(([en]) => { onScreen = en.isIntersecting }, { rootMargin: '200px 0px' })
    if (inline) io.observe(scrollEl)
    const STEP = () => box.clientHeight * 1.6
    const fit = (pos: THREE.Vector3, look: THREE.Vector3) => {
      const a = camera.aspect
      const k = a < 1.25 ? Math.min(2.2, 1.35 / a) : 1
      return look.clone().add(pos.clone().sub(look).multiplyScalar(k))
    }
    let cur = -1
    let aim = -1, aimUntil = 0 // where repeated key presses are heading, so quick presses add up
    const enter = (n: number) => {
      cur = n
      buildLabels(beats[cur].labels)
      setBeat(cur); setCaption(beats[cur].word); setEnded(beats[cur].key === 'end')
    }
    ctl.current = {
      go: (d: number) => {
        const base = aim >= 0 && performance.now() < aimUntil ? aim : Math.max(cur, 0)
        const n = d === 0 ? 0 : Math.max(0, Math.min(beats.length - 1, base + d))
        aim = n; aimUntil = performance.now() + 1400
        scrollTo(n === 0 && d === 0 ? 0 : (n + 0.6) * STEP())
      },
    }

    const resize = () => {
      const w = box.clientWidth, h = box.clientHeight
      renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix()
      svg.setAttribute('viewBox', `0 0 ${w} ${h}`)
    }
    const ro = new ResizeObserver(resize); ro.observe(box); resize()

    const clock = new THREE.Clock()
    let raf = 0, elapsed = 0
    let sf = -1   // the scroll position the scene is showing: it eases toward the real one, so wheel ticks never jerk the camera
    const camPos = V(0, 0, 0), camLook = V(0, 0, 0)
    const frame = () => {
      const dt = Math.min(clock.getDelta(), 0.1)
      elapsed += dt
      if (!onScreen) { raf = requestAnimationFrame(frame); return }   // nothing to draw while it is scrolled out of view
      const target = Math.min(Math.max(progress() / STEP(), 0), beats.length - 0.001)
      if (sf < 0 || reduce) sf = target
      else { sf += (target - sf) * (1 - Math.exp(-dt * 7)); if (Math.abs(target - sf) < 0.0008) sf = target }
      const f = sf
      const n = Math.floor(f), local = f - n
      if (n !== cur) enter(n)
      const t = seg(local, 0.06, 0.55) * beats[n].dur
      const to = fit(beats[n].cam, beats[n].look)
      if (n === 0) { camPos.copy(to); camLook.copy(beats[0].look) } else {
        const e = ease(seg(local, 0, 0.25))
        camPos.lerpVectors(fit(beats[n - 1].cam, beats[n - 1].look), to, e)
        camLook.lerpVectors(beats[n - 1].look, beats[n].look, e)
      }
      // Slide the frame away from the explanation card, so the card never covers what it explains.
      const sideOf = (k: number) => (beats[k].key === 'end' ? 0 : RIGHT.has(beats[k].key) ? 1 : -0.55)
      const w = box.clientWidth, h = box.clientHeight
      const shift = w < 900 ? 0 : 0.14 * w * (n === 0 ? sideOf(0) : sideOf(n - 1) + (sideOf(n) - sideOf(n - 1)) * ease(seg(local, 0, 0.25)))
      camera.setViewOffset(w, h, shift, 0, w, h)
      const drift = reduce ? 0 : Math.sin(elapsed * 0.18) * 0.05
      camera.position.copy(camLook).add(camPos.clone().sub(camLook).applyAxisAngle(V(0, 1, 0), drift)); camera.lookAt(camLook)
      apply(n, t)
      renderer.render(scene, camera)
      drawLabels(t, box.clientWidth, box.clientHeight)
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)

    return () => {
      cancelAnimationFrame(raf); ro.disconnect(); io.disconnect()
      layer.querySelectorAll('.sim-label').forEach((n) => n.remove()); svg.innerHTML = ''
      scene.traverse((o) => {
        const m = o as THREE.Mesh
        m.geometry?.dispose()
        const mats = Array.isArray(m.material) ? m.material : m.material ? [m.material] : []
        mats.forEach((x) => { (x as THREE.MeshBasicMaterial).map?.dispose(); x.dispose() })
      })
      renderer.dispose()
    }
  }, [run, inline])

  useEffect(() => {
    if (inline) return   // inline, the arrow keys and space keep scrolling the page
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose?.()
      else if (e.key === ' ' || e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === 'PageDown') { e.preventDefault(); ctl.current.go(1) }
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp' || e.key === 'PageUp') { e.preventDefault(); ctl.current.go(-1) }
      else if (e.key === 'Home' || e.key === 'r' || e.key === 'R') { e.preventDefault(); ctl.current.go(0) }
    }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { window.removeEventListener('keydown', onKey); document.body.style.overflow = prev }
  }, [onClose, inline])

  return (
    <div ref={scroller} className={inline ? 'sim-root relative bg-[#ECEBE7] text-[#1E1C1A]' : 'sim-root fixed inset-0 z-50 overflow-y-auto overscroll-contain bg-[#ECEBE7]'}
      {...(inline ? { role: 'region' } : { role: 'dialog', 'aria-modal': true })}
      aria-label="How your question went through the pipeline, step by step in 3D">
      <div className="relative" style={{ height: `calc(${count} * 160dvh + 100dvh)` }}>
        <div className="sticky top-0 h-[100dvh] w-full overflow-hidden">
          <div ref={host} className="absolute inset-0">
            <canvas ref={canvasRef} className="block h-full w-full" />
            <svg ref={lines} className="sim-lines pointer-events-none absolute inset-0 h-full w-full" />
            <div ref={overlay} className="pointer-events-none absolute inset-0 overflow-hidden" />
          </div>
          {caption && (
            <p key={beat} className="sim-caption pointer-events-none absolute inset-x-0 bottom-[13%] px-4 text-center font-display text-[44px] leading-none font-black tracking-[-0.02em] text-[#1E1C1A] sm:text-[76px]">
              {caption}
            </p>
          )}
          {ended && (
            <div className="sim-caption pointer-events-none absolute inset-x-0 top-[12%] text-center">
              <p className="font-display text-[48px] leading-none font-black tracking-[-0.02em] text-badger sm:text-[84px]">Blindspot</p>
              <p className="typed mt-3 text-[15px] text-graphite sm:text-[17px]">Ask privately. Prove it.</p>
              {inline && onRestart && (
                <button onClick={onRestart} className="press pointer-events-auto mt-6 h-11 rounded-[2px] bg-badger px-5 font-display text-[15px] font-bold text-white">Ask another question</button>
              )}
            </div>
          )}
          <div className="absolute inset-x-0 top-0 z-20 flex items-center justify-between gap-4 bg-gradient-to-b from-[#ECEBE7] to-transparent px-5 pt-4 pb-6">
            <p className="max-w-[60ch] truncate text-[14px] text-graphite"><span className="font-display font-black text-ink">Watch it run</span>&nbsp;&nbsp;“{run.question}”</p>
            {!inline && <button onClick={onClose} className="shrink-0 rounded-[2px] bg-ink px-3 py-1.5 font-display text-[13px] font-bold text-card">Close</button>}
          </div>
          <div className="typed absolute inset-x-0 bottom-0 z-20 flex flex-wrap items-center justify-between gap-3 px-5 pb-4 text-[13px] text-graphite">
            <span>Step {beat + 1} of {count}</span>
            <span className="hidden sm:inline">{inline ? 'Keep scrolling to move through the steps' : 'Scroll at your own pace   Space or ↓: next step   ↑: back   Esc: close'}</span>
            <span className="flex gap-2">
              <button onClick={() => ctl.current.go(-1)} className="rounded-[2px] border border-graphite/40 bg-card/70 px-2.5 py-1 text-ink">Back</button>
              <button onClick={() => ctl.current.go(1)} className="rounded-[2px] bg-badger px-2.5 py-1 font-bold text-white">Next step</button>
            </span>
          </div>
        </div>

        {steps.map((st, i) => st.explain && (
          // Each step owns one band of scroll; its card slides in, stays put while the step plays, then hands off.
          <div key={st.key} className={`pointer-events-none absolute z-10 w-[min(430px,calc(100vw-32px))] ${st.side === 'right' ? 'right-4 sm:right-8' : 'left-4 sm:left-8'}`}
            style={{ top: `calc(${i} * 160dvh)`, height: '160dvh' }}>
            <section aria-label={`Step ${i + 1}: ${st.word}`} className="sim-step pointer-events-auto sticky top-[16dvh]" style={{ marginTop: i === 0 ? '30dvh' : '70dvh' }}>
              <p className="typed text-[13px] text-graphite">Step {i + 1} of {count}</p>
              <h3 className="mt-1 font-display text-[22px] leading-7 font-black text-ink">{st.word.replace(/\.$/, '')}</h3>
              <p className="mt-2 text-[15px] leading-[22px] text-ink">{st.explain}</p>
              {i === 0 && <p className="typed mt-3 text-[13px] text-graphite">Scroll to move through each step.</p>}
            </section>
          </div>
        ))}
      </div>
    </div>
  )
}
