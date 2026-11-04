import { useEffect, useRef, useState } from 'react'
import type { Citation, ToolStep } from './types'

// 思考过程：折叠成一行，进行中显示呼吸脉冲与实时计时；点开看步骤明细。
// 不再用时间线堆叠——过程信息不该比回答更抢眼。
//
// 注意：后端目前没有下发模型推理内容（只有 delta / citations / tool_call / tool_result），
// 所以展开区展示的是"做了哪些步骤"，不是模型的原始思维链。要展示推理文本需要后端补一个事件。
interface Props {
  citations?: Citation[]
  tools?: ToolStep[]
  running?: boolean
}

const CHEVRON = (
  <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 9l6 6 6-6" />
  </svg>
)

export default function ThinkingTrace({ citations, tools, running }: Props) {
  const [open, setOpen] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const startRef = useRef<number>(0)

  const hasCitations = Array.isArray(citations) && citations.length > 0
  const hasTools = Array.isArray(tools) && tools.length > 0
  const stepCount = (hasCitations ? 1 : 0) + (tools?.length ?? 0)

  // 进行中显示秒数：从开始计时，结束后停在总时长
  useEffect(() => {
    if (running) {
      startRef.current = Date.now()
      setElapsed(0)
      const t = window.setInterval(() => setElapsed((Date.now() - startRef.current) / 1000), 100)
      return () => window.clearInterval(t)
    }
  }, [running])

  // 既没有步骤也不在思考：不渲染这一行
  if (!hasCitations && !hasTools && !running) return null

  return (
    <div className="self-start max-w-full">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-[7px] text-[12.5px] select-none"
        style={{ color: running ? 'var(--fg)' : 'var(--fg-muted)' }}
      >
        <span
          className="w-1.5 h-1.5 rounded-full shrink-0"
          style={{
            background: running ? 'var(--accent)' : 'var(--fg-subtle)',
            animation: running ? 'breathe 1.6s ease-in-out infinite' : 'none',
          }}
        />
        <span>{running ? '思考中…' : `思考了 ${stepCount} 步`}</span>
        {running && <span className="text-[11px]" style={{ color: 'var(--fg-subtle)', fontVariantNumeric: 'tabular-nums' }}>{elapsed.toFixed(1)}s</span>}
        <span className="flex items-center" style={{ color: 'var(--fg-subtle)', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .18s' }}>
          {CHEVRON}
        </span>
      </button>

      {open && (
        <div
          className="mt-[7px] ml-0.5 pl-3 text-[12.5px] leading-[1.75] rounded-lg py-2.5 pr-3"
          style={{ borderLeft: '1px solid var(--border)', color: 'var(--fg-muted)' }}
        >
          {hasCitations && (
            <div className="flex items-center gap-1.5">
              <span style={{ color: 'var(--accent)' }}>检索知识库</span>
              <span>命中 {citations!.length} 条相关片段</span>
            </div>
          )}
          {hasTools && tools!.map((t) => (
            <div key={t.id ?? t.name} className="flex items-center gap-1.5">
              <span style={{ color: 'var(--fg)' }}>{t.name}</span>
              <span style={{ color: 'var(--fg-subtle)' }}>
                {t.status === 'running' ? '执行中…' : t.status === 'error' ? '执行出错' : '已完成'}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
