import { Button, Dropdown, Space, Tag, Tooltip, Typography } from 'antd'
import { ArrowLeftOutlined, MoreOutlined, RocketOutlined, SaveOutlined } from '@ant-design/icons'
import type { AgentDetail } from '../../../api'
import StatusTag from '../../common/StatusTag'

// 装配页顶栏（钉死）：返回、名称与状态（草稿 / 线上 vN / 未发布修改 / 未保存）、保存、发布、更多（去详情、下线、删除）。
// 发布的是已保存的草稿，有未保存修改时先保存。
interface Props {
  agent: AgentDetail
  dirty: boolean
  saving: boolean
  compact: boolean
  onBack: () => void
  onSave: () => void
  onPublish: () => void
  onOpenDetail: () => void
  onOffline: () => void
  onDelete: () => void
}

export default function EditorHeader({ agent, dirty, saving, compact, onBack, onSave, onPublish, onOpenDetail, onOffline, onDelete }: Props) {
  const canPublish = agent.status !== 'published' || agent.has_unpublished_changes
  const publishLabel = agent.status === 'offline' && !agent.has_unpublished_changes ? '重新上线' : '发布'
  const more = [
    { key: 'detail', label: '去详情页' },
    ...(agent.status === 'published' ? [{ key: 'offline', label: '下线' }] : []),
    { type: 'divider' as const },
    { key: 'delete', label: '删除', danger: true },
  ]
  const onMore = ({ key }: { key: string }) => (key === 'detail' ? onOpenDetail() : key === 'offline' ? onOffline() : onDelete())

  return (
    <div style={{ flexShrink: 0, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, padding: '10px 14px', border: '1px solid #e5e7eb', borderRadius: 10, background: '#fff' }}>
      <Space size={8} style={{ minWidth: 0 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={onBack}>{compact ? '' : '返回'}</Button>
        <Typography.Text strong ellipsis style={{ fontSize: 15, maxWidth: compact ? 120 : 280 }}>{agent.name}</Typography.Text>
        <StatusTag domain="agent" value={agent.status} />
        {!compact && agent.published_version && <Tag>线上 v{agent.published_version}</Tag>}
        {!compact && agent.has_unpublished_changes && <Tooltip title="已保存的草稿与线上版本不同，发布后对外生效"><Tag color="gold">未发布修改</Tag></Tooltip>}
        {dirty && <Tooltip title="浏览器的后退键不会提示，离开前先保存"><Tag color="red">未保存</Tag></Tooltip>}
      </Space>
      <Space size={8}>
        <Button type={dirty ? 'primary' : 'default'} icon={<SaveOutlined />} loading={saving} onClick={onSave}>{compact ? '' : '保存草稿'}</Button>
        <Tooltip title={dirty ? '有未保存的修改：发布的是已保存的草稿，先保存' : canPublish ? undefined : '草稿与线上一致，无需发布'}>
          <Button type={dirty ? 'default' : 'primary'} icon={<RocketOutlined />} disabled={dirty || !canPublish} onClick={onPublish}>{compact ? '' : publishLabel}</Button>
        </Tooltip>
        <Dropdown menu={{ items: more, onClick: onMore }} trigger={['click']}><Button icon={<MoreOutlined />} /></Dropdown>
      </Space>
    </div>
  )
}
