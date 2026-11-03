import type { ReactNode } from 'react'

// 状态徽章：替代 antd Tag。色板只保留五种语义，避免各页面自定义颜色导致风格发散。
type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'accent' | 'info'

const TONES: Record<Tone, { bg: string; fg: string }> = {
  neutral: { bg: 'var(--bg-soft)', fg: 'var(--fg-muted)' },
  success: { bg: 'rgba(22,163,74,.14)', fg: '#15803D' },
  warning: { bg: 'rgba(217,119,6,.16)', fg: '#B45309' },
  danger: { bg: 'rgba(220,38,38,.13)', fg: '#B91C1C' },
  accent: { bg: 'var(--accent-soft)', fg: 'var(--accent)' },
  info: { bg: 'rgba(37,99,235,.13)', fg: '#1D4ED8' },
}

// antd Tag 的语义色名 -> 新 tone；StatusTag 等既有组件传进来的是这些名字
const LEGACY: Record<string, Tone> = {
  success: 'success', green: 'success',
  warning: 'warning', orange: 'warning', gold: 'warning', volcano: 'warning',
  error: 'danger', red: 'danger',
  processing: 'info', blue: 'info', geekblue: 'info', cyan: 'info',
  purple: 'accent', magenta: 'accent',
  default: 'neutral',
}

interface Props {
  tone?: Tone | string
  children: ReactNode
  title?: string
}

export default function Badge({ tone = 'neutral', children, title }: Props) {
  const key = (LEGACY[tone] ?? tone) as Tone
  const c = TONES[key] ?? TONES.neutral
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1 px-2 py-[1px] rounded-full text-[11.5px] whitespace-nowrap leading-[18px]"
      style={{ background: c.bg, color: c.fg }}
    >
      {children}
    </span>
  )
}
