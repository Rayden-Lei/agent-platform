import { useMemo, useState } from 'react'
import { Alert } from 'antd'
import { Link } from 'react-router-dom'
import { useSystemStatus } from '../../hooks/useSystemStatus'

// 全局降级横幅：/system/status.degraded 非空时显示在顶栏下方，每项给出对应入口；关闭后本会话内不再出现（按内容签名）。
const ENTRY: Record<string, { to: string; label: string }> = {
  embedding: { to: '/knowledge-bases', label: '知识库' },
  rerank: { to: '/knowledge-bases', label: '知识库' },
  model_breaker: { to: '/models', label: '模型' },
  scheduler: { to: '/schedules', label: '定时任务' },
}

export default function DegradedBanner() {
  const { status } = useSystemStatus()
  const items = status?.degraded ?? []
  const signature = useMemo(() => items.map((i) => i.item + ':' + i.message).join('|'), [items])
  const [dismissed, setDismissed] = useState<string | null>(() => sessionStorage.getItem('degraded-dismissed'))
  if (!items.length || dismissed === signature) return null
  return (
    <Alert
      banner
      type="warning"
      showIcon
      closable
      onClose={() => { sessionStorage.setItem('degraded-dismissed', signature); setDismissed(signature) }}
      message={
        <span>
          系统有 {items.length} 项能力在降级运行：
          {items.map((i, idx) => (
            <span key={idx} style={{ marginLeft: 8 }}>
              {i.message}
              {ENTRY[i.item] && <Link to={ENTRY[i.item].to} style={{ marginLeft: 4 }}>去{ENTRY[i.item].label}</Link>}
              {idx < items.length - 1 && '；'}
            </span>
          ))}
        </span>
      }
    />
  )
}
