import { useEffect, useState } from 'react'
import { Button, Drawer, Popconfirm, Table, Tag, Typography, message } from 'antd'
import { getPromptTemplateVersions, rollbackPromptTemplate, OPTIONS_PAGE, type PromptTemplateRow, type PromptTemplateVersionRow } from '../../api'

// 模板版本历史抽屉：查看每个版本的内容与变量，回滚到任一历史版本（回滚也产生新版本）。

interface Props {
  template: PromptTemplateRow | null
  open: boolean
  onClose: () => void
  onRolledBack: () => void
}

export default function VersionsDrawer({ template, open, onClose, onRolledBack }: Props) {
  const [versions, setVersions] = useState<PromptTemplateVersionRow[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open || !template) return
    setLoading(true)
    getPromptTemplateVersions(template.id, OPTIONS_PAGE)
      .then((page) => setVersions(page.items))
      .catch((e: any) => message.error(e.response?.data?.detail || '加载版本失败'))
      .finally(() => setLoading(false))
  }, [open, template?.id])

  const rollback = async (versionId: number) => {
    if (!template) return
    try {
      await rollbackPromptTemplate(template.id, versionId)
      message.success('已回滚，版本号 +1')
      onRolledBack()
      onClose()
    } catch (e: any) { message.error(e.response?.data?.detail || '回滚失败') }
  }

  return (
    <Drawer title={'版本历史：' + (template?.name || '')} open={open} onClose={onClose} width={640}>
      <Table
        size="small"
        rowKey="id"
        loading={loading}
        dataSource={versions}
        pagination={false}
        expandable={{
          expandedRowRender: (v) => (
            <div>
              <pre style={{ background: '#f8fafc', padding: 8, borderRadius: 6, fontSize: 12, whiteSpace: 'pre-wrap', margin: 0 }}>{v.content}</pre>
              <div style={{ marginTop: 6 }}>
                {v.variables.length ? v.variables.map((x) => <Tag key={x.name}>{x.name}{x.required ? ' *' : ''}</Tag>) : <Typography.Text type="secondary">无变量</Typography.Text>}
              </div>
            </div>
          ),
        }}
        columns={[
          { title: '版本', dataIndex: 'version', width: 100, render: (v: number) => <>v{v} {template?.version === v && <Tag color="green">当前</Tag>}</> },
          { title: '时间', dataIndex: 'created_at', render: (v: string) => new Date(v).toLocaleString() },
          { title: '变量数', dataIndex: 'variables', width: 80, render: (vars: PromptTemplateVersionRow['variables']) => vars.length },
          {
            title: '操作', width: 100, render: (_: unknown, v: PromptTemplateVersionRow) => (
              <Popconfirm title={'回滚到 v' + v.version + '？'} onConfirm={() => rollback(v.id)} disabled={template?.version === v.version}>
                <Button size="small" disabled={template?.version === v.version}>回滚</Button>
              </Popconfirm>
            ),
          },
        ]}
      />
    </Drawer>
  )
}
