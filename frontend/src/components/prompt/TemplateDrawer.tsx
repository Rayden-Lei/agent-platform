import { Button, Descriptions, Drawer, Skeleton, Space, Table, Tabs, Tag, Tooltip, Typography } from 'antd'
import { getPromptTemplate, getPromptTemplateAgents, type PromptTemplateRow } from '../../api'
import { useAsyncData } from '../../hooks/useAsyncData'
import ErrorState from '../common/ErrorState'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import EmptyState from '../common/EmptyState'
import TemplateVersionsTab from './TemplateVersionsTab'
import TemplateRenderTab from './TemplateRenderTab'

// 模板详情抽屉：内容与变量 / 版本历史（对比、回滚）/ 绑定的智能体（标出用的是旧版）/ 渲染预览；编辑在头部。
interface Props { template: PromptTemplateRow | null; onClose: () => void; onEdit: (t: PromptTemplateRow) => void; onChanged: () => void }

export default function TemplateDrawer({ template, onClose, onEdit, onChanged }: Props) {
  const id = template?.id ?? 0
  const detail = useAsyncData(() => getPromptTemplate(id), [id, template?.version], { auto: !!template, errorText: '加载模板失败' })
  const agents = useAsyncData(() => getPromptTemplateAgents(id), [id, template?.version], { auto: !!template, errorText: '加载绑定智能体失败' })
  const t = detail.data
  return (
    <Drawer title={template ? `模板：${template.name}` : ''} open={!!template} onClose={onClose} width={760} destroyOnHidden
      extra={t && <Button type="primary" onClick={() => onEdit(t)}>编辑</Button>}>
      {detail.error ? <ErrorState compact message={detail.error} onRetry={() => detail.reload()} /> : !t ? <Skeleton active /> : (
        <Tabs size="small" items={[
          {
            key: 'content', label: '内容', children: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <Descriptions size="small" bordered column={3} items={[
                  { key: 'version', label: '版本', children: `v${t.version}` },
                  { key: 'creator', label: '创建人', children: t.created_by_username || '-' },
                  { key: 'updated', label: '更新时间', children: <TimeCell value={t.updated_at} /> },
                  { key: 'desc', label: '描述', span: 3, children: t.description || '-' },
                ]} />
                <div>
                  <Typography.Text strong>变量声明（{t.variables.length}）</Typography.Text>
                  {t.variables.length ? (
                    <Table size="small" rowKey="name" pagination={false} style={{ marginTop: 8 }} dataSource={t.variables} columns={[
                      { title: '变量', dataIndex: 'name', width: 160, render: (v: string, r) => <span>{v}{r.required && <span style={{ color: '#dc2626' }}> *</span>}</span> },
                      { title: '说明', dataIndex: 'description', render: (v?: string) => v || '-' },
                      { title: '默认值', dataIndex: 'default', width: 160, render: (v?: string | null) => (v ? <Typography.Text code>{v}</Typography.Text> : '-') },
                    ]} />
                  ) : <div style={{ marginTop: 6 }}><Typography.Text type="secondary">无变量，内容按原文使用</Typography.Text></div>}
                </div>
                <div>
                  <Typography.Text strong>内容</Typography.Text>
                  <pre style={{ background: '#f8fafc', border: '1px solid #e5e7eb', borderRadius: 6, padding: 12, whiteSpace: 'pre-wrap', margin: '8px 0 0', fontSize: 13 }}>{t.content}</pre>
                </div>
              </div>
            ),
          },
          { key: 'versions', label: '版本历史', children: <TemplateVersionsTab template={t} onRolledBack={() => { detail.reload(); agents.reload(); onChanged() }} /> },
          {
            key: 'agents', label: `绑定智能体（${agents.data?.length ?? t.agents_count ?? 0}）`, children: agents.error ? <ErrorState compact message={agents.error} onRetry={() => agents.reload()} /> : agents.data?.length ? (
              <Space direction="vertical" size={6}>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>智能体发布时固化模板版本；标"旧版"的需要重新发布才用到当前 v{t.version}。</Typography.Text>
                {agents.data.map((a) => (
                  <span key={a.id}>
                    <ResourceLink type="agent" id={a.id} name={a.name} showIcon /> <StatusTag domain="agent" value={a.status} />
                    {a.prompt_template_version !== null && <Tag style={{ marginLeft: 6 }}>v{a.prompt_template_version}</Tag>}
                    {a.outdated && <Tooltip title="已发布版本用的是旧模板，重新发布后生效"><Tag color="warning">旧版</Tag></Tooltip>}
                  </span>
                ))}
              </Space>
            ) : <EmptyState description="没有智能体绑定该模板；在智能体表单里打开「使用模板」即可" />,
          },
          { key: 'render', label: '渲染预览', children: <TemplateRenderTab template={t} /> },
        ]} />
      )}
    </Drawer>
  )
}
