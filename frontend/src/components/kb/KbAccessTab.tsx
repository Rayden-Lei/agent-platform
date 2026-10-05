import { useEffect, useState } from 'react'
import { Alert, Button, Card, Select, Space, Switch, Typography } from 'antd'
import { CheckCircleFilled, CloseCircleFilled } from '@ant-design/icons'
import type { KbAccess, KbAccessChange, KbAccessInput, KnowledgeBaseDetail } from '../../api'
import { statusOptions } from '../../constants/status'
import ResourceLink from '../common/ResourceLink'
import KbAccessLog from './KbAccessLog'

// 知识库详情的"访问权限"页签（docs/15 KB-01）：改规则（保存即生效，不用重新解析）、各身份能否检索的直白说明、
// "已发布却让调用者检索不到"的智能体提醒、变更记录。取数与保存都在 KbDetail 页面，本组件只接收 props。
interface Props {
  kb: KnowledgeBaseDetail
  myRole?: string
  saving: boolean
  onSave: (policy: KbAccessInput) => void
  changes: KbAccessChange[] | null
  changesTotal?: number
  changesError?: string | null
  onRetryChanges: () => void
}

// "谁能检索"逐行说明；文字说的是对话与检索评测里的实际效果，不是抽象的权限名词
const WHO: { key: keyof KbAccess; label: string; yes: string; no: string }[] = [
  { key: 'admin', label: '管理员', yes: '始终能检索、能管理', no: '' },
  { key: 'developer', label: '开发者', yes: '能在管理页看到、编辑、检索这个知识库', no: '看不到这个知识库，管理页和检索评测都是"不存在"' },
  { key: 'caller', label: '调用者', yes: '对话时智能体能引用这个知识库', no: '对话时智能体引用不到这个知识库（回答里不会出现它的内容）' },
  { key: 'anonymous', label: '匿名访客', yes: '通过分享链接对话时能引用（分享功能上线后）', no: '通过分享链接对话时引用不到' },
]

export default function KbAccessTab({ kb, myRole, saving, onSave, changes, changesTotal, changesError, onRetryChanges }: Props) {
  const [isPublic, setIsPublic] = useState(kb.is_public)
  const [roles, setRoles] = useState<string[]>(kb.visible_roles || [])
  // 保存成功后详情会重新取回，以服务端的值为准
  useEffect(() => { setIsPublic(kb.is_public); setRoles(kb.visible_roles || []) }, [kb.is_public, kb.visible_roles])
  const dirty = isPublic !== kb.is_public || (!isPublic && [...roles].sort().join() !== [...(kb.visible_roles || [])].sort().join())
  // 非管理员不能把自己排除在外：服务端同样拦（400），这里提前说明原因
  const shutsMeOut = myRole !== 'admin' && !isPublic && !roles.includes(myRole || '')
  const blindAgents = kb.access.caller ? [] : kb.agents.filter((a) => a.in_live && a.status === 'published')

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      {blindAgents.length > 0 && (
        <Alert type="warning" showIcon message="以下已发布的智能体线上版本绑定了本库，但调用者检索不到它"
          description={<Space wrap>{blindAgents.map((a) => <ResourceLink key={a.id} type="agent" id={a.id} name={a.name} showIcon />)}</Space>} />
      )}
      <Card size="small" title="访问规则">
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space><Switch checked={isPublic} onChange={setIsPublic} /><span>公开（所有角色可见）</span></Space>
          {!isPublic && (
            <div>
              <div style={{ marginBottom: 6 }}>可见角色（管理员始终可见）</div>
              <Select mode="multiple" style={{ width: 360, maxWidth: '100%' }} value={roles} onChange={setRoles} placeholder="选择可访问的角色" options={statusOptions('role')} />
            </div>
          )}
          {shutsMeOut && <Alert type="error" showIcon message="不能把自己的角色排除在外：保存后你将看不到、也改不回这个知识库" />}
          <Space>
            <Button type="primary" loading={saving} disabled={!dirty || shutsMeOut} onClick={() => onSave({ is_public: isPublic, visible_roles: isPublic ? [] : roles })}>保存</Button>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>保存后立即生效，已入库的切片不用重新解析</Typography.Text>
          </Space>
        </Space>
      </Card>
      <Card size="small" title="现在谁能检索">
        <Space direction="vertical" size={8}>
          {WHO.map((w) => (
            <span key={w.key}>
              {kb.access[w.key] ? <CheckCircleFilled style={{ color: '#16a34a' }} /> : <CloseCircleFilled style={{ color: '#dc2626' }} />}
              <Typography.Text strong style={{ margin: '0 8px' }}>{w.label}</Typography.Text>
              <Typography.Text type="secondary">{kb.access[w.key] ? w.yes : w.no}</Typography.Text>
            </span>
          ))}
        </Space>
      </Card>
      <KbAccessLog changes={changes} total={changesTotal} error={changesError} onRetry={onRetryChanges} />
    </Space>
  )
}
