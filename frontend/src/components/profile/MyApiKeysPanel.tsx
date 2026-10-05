import { Alert, Space, Table, Typography } from 'antd'
import { Link } from 'react-router-dom'
import type { ApiKeyRow } from '../../api'
import EmptyState from '../common/EmptyState'
import ErrorState from '../common/ErrorState'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { QuotaCell, ScopeCell } from '../admin/apiKeyColumns'
import { KEY_PLACEHOLDER } from '../publish/apiSnippets'

// 个人中心"我的 API 密钥"（docs/15 OP-03、D-15）：归属本人的 Key，只读。admin / developer 去「API Key 管理」生成与启停；
// 调用者看到的是管理员代发给自己的，要停用或换新找管理员。示例一律用占位符，页面上不出现明文。数据由页面传入。
interface Props {
  keys: ApiKeyRow[] | null
  total?: number
  error?: string | null
  onRetry: () => void
  canManage: boolean
  apiBase: string // 对外地址 + /api/v1
}

export default function MyApiKeysPanel({ keys, total, error, onRetry, canManage, apiBase }: Props) {
  if (error) return <ErrorState compact message={error} onRetry={onRetry} />
  const example = `curl -N ${apiBase}/agents/<智能体 ID>/chat \\\n  -H "Authorization: Bearer ${KEY_PLACEHOLDER}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"message": "你好"}'`
  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Alert type="info" showIcon message={canManage
        ? <>生成、编辑、启停在 <Link to="/api-keys">API Key 管理</Link>；这里只列归属你的 Key。</>
        : '这些 Key 由管理员发放给你：只能调用授权范围内的智能体，要停用或换新请联系管理员。明文只在发放时显示一次，丢了只能重发。'} />
      <Table size="small" rowKey="id" loading={!keys} dataSource={keys ?? []} pagination={false} scroll={{ x: 'max-content' }}
        locale={{ emptyText: <EmptyState description={canManage ? '还没有归属你的 Key' : '管理员还没有给你发放 API Key'} /> }}
        columns={[
          { title: '名称', dataIndex: 'name', render: (v: string, r) => (canManage ? <Link to={`/api-keys?open=${r.id}`}>{v}</Link> : v) },
          { title: 'Key 前缀', dataIndex: 'key_prefix', render: (v: string) => <Typography.Text style={{ fontFamily: 'monospace' }}>{v}</Typography.Text> },
          { title: '状态', dataIndex: 'is_enabled', render: (v: boolean) => <StatusTag domain="enabled" value={v} /> },
          { title: '授权范围', key: 'scope', render: (_, r) => <ScopeCell scope={r.scope} /> },
          { title: '配额 / 已用', key: 'quota', render: (_, r) => <QuotaCell used={r.used} quota={r.quota} /> },
          { title: '最后使用', dataIndex: 'last_used_at', render: (v: string | null) => <TimeCell value={v} mode="relative" /> },
        ]} />
      {total !== undefined && keys && total > keys.length && <Typography.Text type="secondary" style={{ fontSize: 12 }}>只显示最近 {keys.length} 个（共 {total} 个）</Typography.Text>}
      <div>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>调用示例（把 {KEY_PLACEHOLDER} 换成你的 Key，只在服务端调用）：</Typography.Text>
        <pre style={{ background: '#0f172a', color: '#e2e8f0', padding: '10px 12px', borderRadius: 8, fontSize: 12, overflow: 'auto', margin: '4px 0 0' }}>{example}</pre>
      </div>
    </Space>
  )
}
