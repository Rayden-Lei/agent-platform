import { Button, Descriptions, Drawer, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import type { ApiKeyRow } from '../../api'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { QuotaCell } from './apiKeyColumns'

// API Key 详情抽屉：配额与用量、来源白名单全文、限速、归属与时间；密钥本身不可再查看。
interface Props { apiKey: ApiKeyRow | null; onClose: () => void; onEdit: (k: ApiKeyRow) => void }

export default function ApiKeyDrawer({ apiKey: k, onClose, onEdit }: Props) {
  return (
    <Drawer title={k ? `API Key：${k.name}` : ''} open={!!k} onClose={onClose} width={640} destroyOnHidden extra={k && <Button type="primary" onClick={() => onEdit(k)}>编辑</Button>}>
      {k && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
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
