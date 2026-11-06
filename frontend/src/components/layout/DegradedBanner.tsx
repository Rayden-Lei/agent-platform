import { useMemo, useState } from 'react'
import { ChevronDown, TriangleAlert, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useSystemStatus } from '../../hooks/useSystemStatus'
import type { DegradedItem } from '../../api'

// 全局降级提示（2026-11-06 重做）。
//
// 原来是一条横贯全宽的橙色条，把所有降级项的原始技术文案直接铺出来：
//   「系统有 1 项能力在降级运行：未配置 EMBEDDING_API_KEY，检索使用本地 hash 向量，语义召回能力有限 去知识库」
// 问题是：占满一整行、右侧三分之二全是空白；文案是给开发者看的（变量名摆在最前面），
// 使用者看不出「这对我有什么影响」；而且橙色横幅横在那里，看着像故障，实际多数只是没配某项可选能力。
//
// 现在：一条紧凑的通知，每项给「人话标题 + 一句影响 + 去处理的入口」，
// 原始技术原因收进可展开的细节里（要排查的人点开就有，不需要的人不用看）。
// 只有一项时仍然只是一个矮条；多项时按行列出。
const ENTRY: Record<string, { to: string; label: string }> = {
  embedding: { to: '/knowledge-bases', label: '去配置' },
  rerank: { to: '/knowledge-bases', label: '去知识库' },
  model_breaker: { to: '/models', label: '去模型' },
  scheduler: { to: '/schedules', label: '去定时任务' },
  dashboard: { to: '/system-settings', label: '去系统参数' },
  client_ip: { to: '/system-settings', label: '去系统参数' },
  login_guard: { to: '/system-settings', label: '去系统参数' },
  rate_limit: { to: '/system-settings', label: '去系统参数' },
  // 沙箱降级没有对应页面可去（服务器配置问题），只说明原因、不给入口
}

// 人话标题：把「哪个配置项没配」翻译成「哪项能力受影响」
const TITLE: Record<string, string> = {
  embedding: '语义检索精度受限',
  rerank: '检索重排未生效',
  model_breaker: '有模型正处于熔断',
  scheduler: '定时任务不会触发',
  dashboard: '统计看板数据不全',
  client_ip: '来源 IP 校验未生效',
  login_guard: '登录限流未生效',
  rate_limit: '入口限流未生效',
  sandbox: '脚本沙箱已降级',
}

export default function DegradedBanner() {
  const { status } = useSystemStatus()
  const items = status?.degraded ?? []
  const signature = useMemo(() => items.map((i) => i.item + ':' + i.message).join('|'), [items])
  const [dismissed, setDismissed] = useState<string | null>(() => sessionStorage.getItem('degraded-dismissed'))
  const [expanded, setExpanded] = useState(false)
  if (!items.length || dismissed === signature) return null

  const close = () => {
    sessionStorage.setItem('degraded-dismissed', signature)
    setDismissed(signature)
  }

  return (
    <div className="shrink-0 border-b border-[rgba(217,119,6,.22)] bg-[rgba(217,119,6,.07)] px-4 py-1.5 sm:px-5">
      <div className="flex items-start gap-2">
        <TriangleAlert className="mt-[3px] size-3.5 shrink-0 text-[#B45309]" />

        <div className="min-w-0 flex-1">
          {/* 一行标题：几项、能点开看原因 */}
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            className="flex items-center gap-1.5 text-[12.5px] font-medium"
            style={{ color: 'var(--fg)' }}
          >
            {items.length === 1 ? '有 1 项能力未完全就绪' : `有 ${items.length} 项能力未完全就绪`}
            <ChevronDown
              className="size-3 transition-transform"
              style={{ transform: expanded ? 'rotate(180deg)' : 'none', color: 'var(--fg-muted)' }}
            />
          </button>

          {/* 收起时只显示标题 + 第一项的人话摘要，不铺技术文案 */}
          {!expanded && items[0] && (
            <div className="truncate text-[12px]" style={{ color: 'var(--fg-muted)' }}>
              {TITLE[items[0].item] ?? items[0].item}
              {items.length > 1 && ` 等 ${items.length} 项`}
            </div>
          )}

          {/* 展开后逐项：人话标题 + 原始技术原因 + 入口 */}
          {expanded && (
            <ul className="m-0 mt-1 flex list-none flex-col gap-1 p-0">
              {items.map((i: DegradedItem, idx) => (
                <li key={idx} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[12px]">
                  <span className="font-medium" style={{ color: 'var(--fg)' }}>{TITLE[i.item] ?? i.item}</span>
                  <span className="min-w-0 flex-1 break-words" style={{ color: 'var(--fg-muted)' }}>{i.message}</span>
                  {ENTRY[i.item] && (
                    <Link to={ENTRY[i.item].to} className="shrink-0 text-primary hover:underline">{ENTRY[i.item].label}</Link>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        <button
          type="button"
          aria-label="关闭提示"
          onClick={close}
          className="relative shrink-0 rounded p-1 text-muted-foreground hover:bg-black/5 after:absolute after:-inset-2 after:content-['']"
        >
          <X className="size-3.5" />
        </button>
      </div>
    </div>
  )
}
