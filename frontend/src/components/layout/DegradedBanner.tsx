import { useMemo, useState } from 'react'
import { TriangleAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/shadcn/popover'
import { useSystemStatus } from '../../hooks/useSystemStatus'
import type { DegradedItem } from '../../api'

// 全局降级提示（2026-11-06 第三版）。
//
// 演进：横贯全宽的橙色横幅（v1，占一整行、右侧大半空白）→ 紧凑横幅（v2，还是占一条，
// 使用者仍嫌占位置）→ 现在的顶栏角标：平时只在顶栏右侧一个黄色小圆点，
// 点开才弹出一小块面板列出细节。不占页面任何一行。
//
// 关闭（X）仍按内容签名记住，同一批降级在当前会话内不再打扰。
const ENTRY: Record<string, { to: string; label: string }> = {
  embedding: { to: '/knowledge-bases', label: '去配置' },
  rerank: { to: '/knowledge-bases', label: '去知识库' },
  model_breaker: { to: '/models', label: '去模型' },
  scheduler: { to: '/schedules', label: '去定时任务' },
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
  const [open, setOpen] = useState(false)
  if (!items.length || dismissed === signature) return null

  const close = () => {
    sessionStorage.setItem('degraded-dismissed', signature)
    setDismissed(signature)
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`系统有 ${items.length} 项能力未完全就绪，点开查看`}
          title={`系统有 ${items.length} 项能力未完全就绪`}
          className="relative flex h-9 items-center rounded-lg px-1.5 transition-colors hover:bg-accent"
        >
          <TriangleAlert className="size-4 text-[#B45309]" />
          {/* 数量角标：单项时只一个小圆点（不显示数字，避免看着像"1 条未读"）；
              多项才显示数字。2026-11-07 缩小：原来 h-4/min-w-4 视觉上比图标还抢眼。 */}
          <span
            className="absolute right-0 top-0.5 flex items-center justify-center rounded-full text-[9px] font-semibold leading-none text-white"
            style={{
              background: '#B45309',
              height: items.length > 1 ? 12 : 5,
              minWidth: items.length > 1 ? 12 : 5,
              paddingInline: items.length > 1 ? 3 : 0,
            }}
          >
            {items.length > 1 ? items.length : ''}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[420px] p-0">
        <div className="flex items-center justify-between gap-3 border-b border-border px-3.5 py-2.5">
          <span className="text-[13px] font-medium">系统能力状态</span>
          <button
            type="button"
            aria-label="不再提示"
            onClick={close}
            className="rounded p-1 text-[11.5px] text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            本会话不再提示
          </button>
        </div>
        <ul className="m-0 flex max-h-[50vh] list-none flex-col overflow-y-auto p-0">
          {items.map((i: DegradedItem, idx) => (
            <li key={idx} className="flex flex-col gap-1 border-b border-border px-3.5 py-2.5 last:border-b-0">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="text-[12.5px] font-medium" style={{ color: 'var(--fg)' }}>{TITLE[i.item] ?? i.item}</span>
                {ENTRY[i.item] && (
                  <Link
                    to={ENTRY[i.item].to}
                    className="text-[11.5px] text-primary hover:underline"
                    onClick={() => setOpen(false)}
                  >
                    {ENTRY[i.item].label}
                  </Link>
                )}
              </div>
              <div className="break-words text-[11.5px] leading-relaxed" style={{ color: 'var(--fg-muted)' }}>
                {i.message}
              </div>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  )
}
