import { Alert, Button, Descriptions, Drawer, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import type { ApiKeyRow, ApiKeyScopeItem } from '../../api'
import type { ResourceType } from '../../constants/resources'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { QuotaCell } from './apiKeyColumns'

// API Key 详情抽屉：授权范围、配额与用量、来源白名单全文、限速、归属与时间；密钥本身不可再查看。
interface Props { apiKey: ApiKeyRow | null; onClose: () => void; onEdit: (k: ApiKeyRow) => void }

// 授权的资源逐个给跳转链接；已删除的资源没有详情可跳，标"已删除"
function ScopeList({ type, items }: { type: ResourceType; items: ApiKeyScopeItem[] }) {
  if (!items.length) return <Typography.Text type="secondary">无</Typography.Text>
  return <Space size={[8, 4]} wrap>{items.map((x) => (x.name === null ? <Tag key={x.id}>已删除 #{x.id}</Tag> : <ResourceLink key={x.id} type={type} id={x.id} name={x.name} showIcon />))}</Space>
}

export default function ApiKeyDrawer({ apiKey: k, onClose, onEdit }: Props) {
  return (
    <Drawer title={k ? `API Key：${k.name}` : ''} open={!!k} onClose={onClose} width={640} destroyOnHidden extra={k && <Button type="primary" onClick={() => onEdit(k)}>编辑</Button>}>
      {k && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {!k.agent_ids.length && !k.workflow_ids.length && !k.kb_ids.length && (
            <Alert type="warning" showIcon message="这个 Key 没有授权任何资源，调用一律被拒" description="它是作用域上线（2026-10-05）之前建的；点右上角“编辑”授权要调用的智能体或工作流后即可使用。" />
          )}
          <Descriptions size="small" bordered column={1} title="授权范围" items={[
            { key: 'agents', label: '可调用的智能体', children: <ScopeList type="agent" items={k.scope.agents} /> },
            { key: 'workflows', label: '可运行的工作流', children: <ScopeList type="workflow" items={k.scope.workflows} /> },
            { key: 'kbs', label: '检索放行的知识库', children: <ScopeList type="kb" items={k.scope.knowledge_bases} /> },
          ]} />
          <Descriptions size="small" bordered column={2} items={[
            { key: 'prefix', label: 'Key 前缀', children: <span style={{ fontFamily: 'monospace' }}>{k.key_prefix}…</span> },
            { key: 'status', label: '状态', children: <StatusTag domain="enabled" value={k.is_enabled} /> },
            { key: 'quota', label: '配额 / 已用', span: 2, children: <QuotaCell used={k.used} quota={k.quota} /> },
            { key: 'rate', label: '每分钟限速', children: k.rate_limit_per_minute === 0 ? '服务端默认' : k.rate_limit_per_minute },
            { key: 'owner', label: '归属', children: k.username || '-' },
            { key: 'last', label: '最后使用', children: <TimeCell value={k.last_used_at} /> },
            { key: 'created', label: '创建时间', children: <TimeCell value={k.created_at} /> },
          ]} />
          <div>
            <Typography.Text strong>允许的来源 IP（{k.allowed_ips.length ? k.allowed_ips.length + ' 条' : '不限制'}）</Typography.Text>
            <div style={{ marginTop: 8 }}>
              {k.allowed_ips.length ? <Space size={4} wrap>{k.allowed_ips.map((ip) => <Tag key={ip} style={{ fontFamily: 'monospace' }}>{ip}</Tag>)}</Space> : <Typography.Text type="secondary">任何来源都可使用；建议生产环境限定 CIDR</Typography.Text>}
            </div>
          </div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            密钥明文只在生成时显示一次，无法找回；泄露时请删除并重新生成。通过该 Key 发起的运行在<Link to="/runs?source=api_key">运行记录</Link>里按"API Key"来源筛选。
          </Typography.Text>
        </div>
      )}
    </Drawer>
  )
}
