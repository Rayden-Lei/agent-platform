import { Card, List, Skeleton, Typography } from 'antd'
import type { KbAccessChange, KbAccessInput } from '../../api'
import { statusLabel } from '../../constants/status'
import { formatDateTime } from '../../utils/time'
import EmptyState from '../common/EmptyState'
import ErrorState from '../common/ErrorState'

// 访问权限的变更记录（新的在前）：谁、什么时候、从什么改成什么。只接收 props。
interface Props {
  changes: KbAccessChange[] | null
  total?: number
  error?: string | null
  onRetry: () => void
}

const describe = (p: KbAccessInput | null) => {
  if (!p) return ''
  if (p.is_public) return '公开'
  const roles = p.visible_roles.filter((r) => r !== 'admin').map((r) => statusLabel('role', r))
  return roles.length ? `仅管理员与${roles.join('、')}` : '仅管理员'
}

export default function KbAccessLog({ changes, total, error, onRetry }: Props) {
  const shown = changes?.length ?? 0
  return (
    <Card size="small" title="变更记录" extra={total !== undefined && total > shown ? <Typography.Text type="secondary" style={{ fontSize: 12 }}>显示最近 {shown} 条，共 {total} 条</Typography.Text> : null}>
      {error ? <ErrorState compact message={error} onRetry={onRetry} /> : !changes ? <Skeleton active /> : changes.length === 0 ? (
        <EmptyState description="还没有记录：2026-10-05 起记录建库与每次修改，之前建的库从下一次修改开始有记录" />
      ) : (
        <List size="small" dataSource={changes} renderItem={(c) => (
          <List.Item>
            <span>
              <Typography.Text type="secondary" style={{ marginRight: 12 }}>{formatDateTime(c.created_at)}</Typography.Text>
              <Typography.Text strong style={{ marginRight: 12 }}>{c.username || '-'}</Typography.Text>
              {c.action === 'create' ? `建库，初始为${describe(c.after)}` : `${describe(c.before)} → ${describe(c.after)}`}
            </span>
          </List.Item>
        )} />
      )}
    </Card>
  )
}
