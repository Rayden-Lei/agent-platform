import { Button, Result, Spin } from 'antd'
import type { SharePhase } from '../../hooks/useShareAccess'

// 分享访客页的状态页（docs/15 3.6）：加载中、链接不存在或已关闭、已过期、智能体已下线、分享不可用、需要登录、其他错误。
// 文案只说访客能做什么，不提内部原因（如"创建者已停用"）。
interface Props {
  phase: SharePhase
  message?: string | null
  onRetry: () => void
  onLogin: () => void
}

const TEXT: Partial<Record<SharePhase, { status: 'info' | 'warning' | '404' | '403' | 'error'; title: string; sub: string }>> = {
  closed: { status: '404', title: '链接不存在或已关闭', sub: '请向分享者确认链接是否正确，或请他重新开启分享' },
  expired: { status: 'warning', title: '链接已过期', sub: '请联系分享者延长有效期或发一个新链接' },
  offline: { status: 'warning', title: '智能体已下线', sub: '分享者重新发布后即可继续使用' },
  unavailable: { status: '403', title: '分享暂时不可用', sub: '请联系分享者' },
  login: { status: 'info', title: '需要登录', sub: '这个分享链接只对平台用户开放，登录后会回到这里' },
}

export default function ShareStatus({ phase, message, onRetry, onLogin }: Props) {
  const wrap = (node: React.ReactNode) => <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>{node}</div>
  if (phase === 'loading') return wrap(<Spin size="large" />)
  const t = TEXT[phase]
  if (!t) return wrap(<Result status="error" title="加载失败" subTitle={message || '请稍后重试'} extra={<Button type="primary" onClick={onRetry}>重试</Button>} />)
  return wrap(<Result status={t.status} title={t.title} subTitle={t.sub} extra={phase === 'login' ? <Button type="primary" onClick={onLogin}>去登录</Button> : undefined} />)
}
