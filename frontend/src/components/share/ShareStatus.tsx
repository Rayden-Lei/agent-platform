import { Ban, Clock, Loader2, LogIn, RefreshCw, ServerOff, TriangleAlert } from 'lucide-react'
import type { SharePhase } from '../../hooks/useShareAccess'
import Button from '../ui/Button'

// 分享访客页的状态页（docs/15 3.6）：加载中、链接不存在或已关闭、已过期、智能体已下线、分享不可用、需要登录、其他错误。
// 文案只说访客能做什么，不提内部原因（如"创建者已停用"）。
interface Props {
  phase: SharePhase
  message?: string | null
  onRetry: () => void
  onLogin: () => void
}

type Tone = 'muted' | 'warning' | 'danger'
const TEXT: Partial<Record<SharePhase, { icon: typeof Ban; tone: Tone; title: string; sub: string }>> = {
  closed: { icon: Ban, tone: 'muted', title: '链接不存在或已关闭', sub: '请向分享者确认链接是否正确，或请他重新开启分享' },
  expired: { icon: Clock, tone: 'warning', title: '链接已过期', sub: '请联系分享者延长有效期或发一个新链接' },
  offline: { icon: ServerOff, tone: 'warning', title: '智能体已下线', sub: '分享者重新发布后即可继续使用' },
  unavailable: { icon: TriangleAlert, tone: 'warning', title: '分享暂时不可用', sub: '请联系分享者' },
  login: { icon: LogIn, tone: 'muted', title: '需要登录', sub: '这个分享链接只对平台用户开放，登录后会回到这里' },
}

// 状态图标：静音灰 / 警示黄 / 失败红，只用语义 token
const TONE_CLASS: Record<Tone, string> = {
  muted: 'bg-secondary text-muted-foreground',
  warning: 'bg-secondary text-foreground',
  danger: 'bg-destructive/10 text-destructive',
}

export default function ShareStatus({ phase, message, onRetry, onLogin }: Props) {
  const wrap = (node: React.ReactNode) => (
    <div className="flex h-full items-center justify-center p-4">{node}</div>
  )
  if (phase === 'loading') {
    return wrap(<Loader2 className="size-8 animate-spin text-muted-foreground" aria-label="加载中" />)
  }
  const t = TEXT[phase]
  if (!t) {
    return wrap(
      <div className="flex max-w-[360px] flex-col items-center gap-3 text-center">
        <span className="flex size-12 items-center justify-center rounded-full bg-destructive/10">
          <TriangleAlert className="size-6 text-destructive" aria-hidden="true" />
        </span>
        <h2 className="m-0 text-[14px] font-semibold text-foreground">加载失败</h2>
        <p className="m-0 text-[12.5px] leading-relaxed text-muted-foreground">{message || '请稍后重试'}</p>
        <Button variant="primary" size="md" icon={<RefreshCw className="size-3.5" />} onClick={onRetry}>重试</Button>
      </div>,
    )
  }
  const Icon = t.icon
  return wrap(
    <div className="flex max-w-[360px] flex-col items-center gap-3 text-center">
      <span className={`flex size-12 items-center justify-center rounded-full ${TONE_CLASS[t.tone]}`}>
        <Icon className="size-6" aria-hidden="true" />
      </span>
      <h2 className="m-0 text-[14px] font-semibold text-foreground">{t.title}</h2>
      <p className="m-0 text-[12.5px] leading-relaxed text-muted-foreground">{t.sub}</p>
      {phase === 'login' && <Button variant="primary" size="md" onClick={onLogin}>去登录</Button>}
    </div>,
  )
}
