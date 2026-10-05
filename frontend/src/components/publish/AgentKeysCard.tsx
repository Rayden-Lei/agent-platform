import { Button, Card, Table, Typography } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import type { ApiKeyRow } from '../../api'
import EmptyState from '../common/EmptyState'
import ErrorState from '../common/ErrorState'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { QuotaCell } from '../admin/apiKeyColumns'

// "发布渠道"的密钥区（docs/15 3.7.2）：作用域含本智能体的 Key（developer 只看到本人的，服务端过滤）；
// "生成仅限此智能体的 Key"由页面打开预填了作用域的 Key 表单。数据由页面传入，本组件不发请求。
interface Props {
  keys: ApiKeyRow[] | null
  total?: number
  error?: string | null
  onRetry: () => void
  onCreate: () => void
}

export default function AgentKeysCard({ keys, total, error, onRetry, onCreate }: Props) {
  return (
    <Card size="small" title={`可调用本智能体的密钥${total !== undefined ? `（${total}）` : ''}`}
      extra={<Button type="primary" icon={<PlusOutlined />} onClick={onCreate}>生成仅限此智能体的 Key</Button>}>
      {error ? <ErrorState compact message={error} onRetry={onRetry} /> : (
        <Table size="small" rowKey="id" loading={!keys} dataSource={keys ?? []} pagination={false}
          locale={{ emptyText: <EmptyState description="还没有能调用本智能体的 Key；生成一个，交给对接方在服务端使用" /> }}
          columns={[
            { title: '名称', dataIndex: 'name', render: (v: string, r) => <Link to={`/api-keys?open=${r.id}`}>{v}</Link> },
            { title: 'Key 前缀', dataIndex: 'key_prefix', width: 140, render: (v: string) => <Typography.Text style={{ fontFamily: 'monospace' }}>{v}…</Typography.Text> },
            { title: '状态', dataIndex: 'is_enabled', width: 80, render: (v: boolean) => <StatusTag domain="enabled" value={v} /> },
            { title: '配额 / 已用', key: 'quota', width: 170, render: (_, r) => <QuotaCell used={r.used} quota={r.quota} /> },
            { title: '最后使用', dataIndex: 'last_used_at', width: 120, render: (v: string | null) => <TimeCell value={v} mode="relative" /> },
          ]} />
      )}
      {total !== undefined && keys && total > keys.length && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>显示前 {keys.length} 个，全部见 <Link to="/api-keys">API Key 管理</Link></Typography.Text>
      )}
    </Card>
  )
}
