import { useCallback, useEffect, useRef } from 'react'

// 液态玻璃的位移贴图生成器。
//
// 为什么不能用一张固定贴图：SVG 的 feImage 是按滤镜区域铺的，把方形贴图拉伸到
// 宽高比悬殊的元素（比如 944×82 的输入框）上，边缘的折射图案会被拉成放射状伪影。
// 所以这里按元素实际尺寸逐像素生成：边缘向心收缩、中心不位移。
//
// 为什么 filter 挂在玻璃层而不是 backdrop-filter 上：Chromium 不支持
// backdrop-filter: url(#filter)（实测最大像素差只有 5/255，等于没生效）。
// liquid-glass-react 的做法是 backdrop-filter 只负责模糊，位移滤镜挂在 filter 上。

const SVG_NS = 'http://www.w3.org/2000/svg'

function smoothStep(a: number, b: number, t: number): number {
  const x = Math.max(0, Math.min(1, (t - a) / (b - a)))
  return x * x * (3 - 2 * x)
}

// 生成位移贴图：R 通道存 x 偏移、B 通道存 y 偏移，0.5 表示不位移
function buildDisplacementMap(w: number, h: number): string {
  const width = Math.max(2, Math.round(w))
  const height = Math.max(2, Math.round(h))
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) return ''

  const image = ctx.createImageData(width, height)
  const data = image.data
  const raw = new Float32Array(width * height * 2)
  const minSide = Math.min(width, height)
  let maxAbs = 1e-6

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const nx = x / width - 0.5
      const ny = y / height - 0.5
      // 到最近边的归一化距离：0 在边缘、0.5 在中心
      const edge = Math.min(x, y, width - 1 - x, height - 1 - y) / minSide
      const k = 1 - smoothStep(0, 0.18, edge)
      const dx = -nx * k * 0.55
      const dy = -ny * k * 0.55
      const i = (y * width + x) * 2
      raw[i] = dx
      raw[i + 1] = dy
      if (Math.abs(dx) > maxAbs) maxAbs = Math.abs(dx)
      if (Math.abs(dy) > maxAbs) maxAbs = Math.abs(dy)
    }
  }

  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 2
      const p = (y * width + x) * 4
      data[p] = Math.round((raw[i] / maxAbs) * 127.5 + 127.5)
      data[p + 1] = 128
      data[p + 2] = Math.round((raw[i + 1] / maxAbs) * 127.5 + 127.5)
      data[p + 3] = 255
    }
  }

  ctx.putImageData(image, 0, 0)
  return canvas.toDataURL('image/png')
}

// 全局共享一个 <defs>，所有玻璃元素往里挂自己的 filter
let defsEl: SVGDefsElement | null = null
let filterSeq = 0

function ensureDefs(): SVGDefsElement {
  if (defsEl && defsEl.isConnected) return defsEl
  const svg = document.createElementNS(SVG_NS, 'svg')
  svg.setAttribute('width', '0')
  svg.setAttribute('height', '0')
  svg.setAttribute('aria-hidden', 'true')
  svg.style.position = 'absolute'
  svg.style.pointerEvents = 'none'
  const defs = document.createElementNS(SVG_NS, 'defs')
  svg.appendChild(defs)
  document.body.appendChild(svg)
  defsEl = defs
  return defs
}

export interface LiquidGlassOptions {
  // 位移强度上限；实际值还会按元素短边缩放，避免小元素位移过大
  scale?: number
  // 是否启用（关闭时不生成贴图，节省开销）
  enabled?: boolean
}

// 把液态玻璃效果挂到某个元素上：元素需要带 .lg 类（见 styles/theme.css）
export function useLiquidGlass<T extends HTMLElement>(options: LiquidGlassOptions = {}) {
  const { scale = 34, enabled = true } = options
  const ref = useRef<T | null>(null)
  const filterIdRef = useRef<string | null>(null)

  const rebuild = useCallback(() => {
    const el = ref.current
    if (!el || !enabled) return
    const rect = el.getBoundingClientRect()
    if (rect.width < 8 || rect.height < 8) return

    // 清掉上一次的 filter，避免反复 resize 时泄漏
    if (filterIdRef.current) {
      const old = document.getElementById(filterIdRef.current)
      if (old) old.remove()
    }

    const id = `lg-${++filterSeq}`
    const defs = ensureDefs()
    const filter = document.createElementNS(SVG_NS, 'filter')
    // 滤镜区域必须精确等于元素，否则 feImage 的 100% 会按放大后的区域铺，贴图和元素对不齐
    filter.setAttribute('id', id)
    filter.setAttribute('x', '0%')
    filter.setAttribute('y', '0%')
    filter.setAttribute('width', '100%')
    filter.setAttribute('height', '100%')
    filter.setAttribute('color-interpolation-filters', 'sRGB')

    const feImage = document.createElementNS(SVG_NS, 'feImage')
    feImage.setAttribute('href', buildDisplacementMap(rect.width, rect.height))
    feImage.setAttribute('x', '0')
    feImage.setAttribute('y', '0')
    feImage.setAttribute('width', '100%')
    feImage.setAttribute('height', '100%')
    feImage.setAttribute('preserveAspectRatio', 'none')
    feImage.setAttribute('result', 'MAP')

    const feDisplace = document.createElementNS(SVG_NS, 'feDisplacementMap')
    feDisplace.setAttribute('in', 'SourceGraphic')
    feDisplace.setAttribute('in2', 'MAP')
    // 位移量按短边缩放：80px 高的输入框不该有 17px 的位移
    feDisplace.setAttribute('scale', String(Math.min(scale, Math.round(Math.min(rect.width, rect.height) * 0.28))))
    feDisplace.setAttribute('xChannelSelector', 'R')
    feDisplace.setAttribute('yChannelSelector', 'B')

    filter.appendChild(feImage)
    filter.appendChild(feDisplace)
    defs.appendChild(filter)

    filterIdRef.current = id
    el.style.setProperty('--lg-filter', `url(#${id})`)
  }, [enabled, scale])

  useEffect(() => {
    if (!enabled) return
    rebuild()

    // 尺寸变化要重新生成贴图；用 ResizeObserver 覆盖窗口缩放与内容变化
    let timer: number | undefined
    const ro = new ResizeObserver(() => {
      window.clearTimeout(timer)
      timer = window.setTimeout(rebuild, 180)
    })
    if (ref.current) ro.observe(ref.current)

    return () => {
      window.clearTimeout(timer)
      ro.disconnect()
      if (filterIdRef.current) {
        const old = document.getElementById(filterIdRef.current)
        if (old) old.remove()
        filterIdRef.current = null
      }
    }
  }, [enabled, rebuild])

  return ref
}
