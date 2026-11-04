import type { CSSProperties, ReactNode } from 'react'
import { cn } from 'cn'
import { Badge as ShadcnBadge } from '@/components/shadcn/badge'

// 状态徽章：底层是 shadcn Badge，色板固定为五种语义，避免各页面自定义颜色导致风格发散。
type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'accent' | 'info'

const TONES: Record<Tone, CSSProperties> = {
  neutral: { background: 'var(--bg-soft)', color: 'var(--fg-muted)' },
  success: { background: 'rgba(22,163,74,.14)', color: '#15803D' },
  warning: { background: 'rgba(217,119,6,.16)', color: '#B45309' },
  danger: { background: 'rgba(220,38,38,.13)', color: '#B91C1C' },
  accent: { background: 'var(--accent-soft)', color: 'var(--accent)' },
  info: { background: 'rgba(37,99,235,.13)', color: '#1D4ED8' },
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
  const style = TONES[key] ?? TONES.neutral
  return (
    <ShadcnBadge
      variant="outline"
      title={title}
      style={style}
      className={cn('border-transparent rounded-full px-2 py-[1px] text-[11.5px] leading-[18px] font-normal')}
    >
      {children}
    </ShadcnBadge>
  )
}
