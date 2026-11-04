import { useEffect, useRef, useState } from 'react'
import type { Citation, ToolStep } from './types'

// 思考过程：折叠成一行，进行中显示呼吸脉冲与实时计时；点开看模型的实际推理与步骤。
//
// 数据来源：后端 reasoning 事件（模型的 reasoning_content / thinking），逐 token 累积成整段。
// 不是所有模型都给推理内容——没有时展开区只列步骤（检索命中数、工具调用），
// 摘要行也相应改成"调用了 N 个工具"，不假称"思考"。
interface Props {
  citations?: Citation[]
  tools?: ToolStep[]
  reasoning?: string
  running?: boolean
}

const CHEVRON = (
  <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
    <path d="M6 9l6 6 6-6" />
  </svg>
)

export default function ThinkingTrace({ citations, tools, reasoning, running }: Props) {
  const [open, setOpen] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const startRef = useRef<number>(0)
  const doneMsRef = useRef<number | null>(null)

  const hasCitations = Array.isArray(citations) && citations.length > 0
  const hasTools = Array.isArray(tools) && tools.length > 0
  const hasReasoning = !!reasoning && reasoning.length > 0
  const toolCount = tools?.length ?? 0

  // 计时：进行中每 100ms 刷新；结束后记下总时长，摘要行显示"N.N 秒"
  useEffect(() => {
    if (running) {
      startRef.current = Date.now()
      doneMsRef.current = null
      setElapsed(0)
      const t = window.setInterval(() => setElapsed((Date.now() - startRef.current) / 1000), 100)
      return () => {
        window.clearInterval(t)
        doneMsRef.current = Date.now() - startRef.current
      }
    }
    if (doneMsRef.current === null && startRef.current) {
      doneMsRef.current = Date.now() - startRef.current
    }
  }, [running])

  // 三者都没有：不渲染这一行
  if (!hasReasoning && !hasCitations && !hasTools && !running) return null

  // 摘要：有推理内容才说"思考了 N 秒"，否则只说做了什么
  const summary = hasReasoning
    ? (running ? '正在思考' : `思考了 ${((doneMsRef.current ?? elapsed * 1000) / 1000).toFixed(1)} 秒`)
    : [
        hasCitations ? `检索 ${citations!.length} 条` : '',
        toolCount ? `调用 ${toolCount} 个工具` : '',
      ].filter(Boolean).join(' · ') || '已处理'

  // 有推理内容时默认展开，让用户看到模型在想什么；纯步骤则默认收起
  const expanded = open || (hasReasoning && running)

  return (
    <div className="self-start max-w-full">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={expanded}
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
        <span>{summary}</span>
        {running && hasReasoning && (
          <span className="text-[11px]" style={{ color: 'var(--fg-subtle)', fontVariantNumeric: 'tabular-nums' }}>
            {elapsed.toFixed(1)}s
          </span>
        )}
        <span className="flex items-center" style={{ color: 'var(--fg-subtle)', transform: expanded ? 'rotate(180deg)' : 'none', transition: 'transform .18s' }}>
          {CHEVRON}
        </span>
      </button>

      {expanded && (
        <div
          className="mt-[7px] ml-0.5 pl-3 text-[12.5px] leading-[1.75]"
          style={{ borderLeft: '1px solid var(--border)', color: 'var(--fg-muted)' }}
        >
          {/* 模型的真实推理：斜体 + 更淡的颜色，和回答正文区分开 */}
          {hasReasoning && (
            <div className="whitespace-pre-wrap italic mb-1.5" style={{ color: 'var(--fg-muted)' }}>{reasoning}</div>
          )}
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
