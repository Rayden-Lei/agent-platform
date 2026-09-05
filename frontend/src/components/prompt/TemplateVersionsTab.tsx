import { useState } from 'react'
import { Button, Popconfirm, Space, Table, Tag, Typography, message } from 'antd'
import { getPromptTemplateVersions, rollbackPromptTemplate, OPTIONS_PAGE, type PromptTemplateRow, type PromptTemplateVersionRow } from '../../api'
import { useAsyncData } from '../../hooks/useAsyncData'
import { TextDiff } from '../common/DiffView'
import ErrorState from '../common/ErrorState'
import TimeCell from '../common/TimeCell'

// 版本历史页签：展开看该版本内容与变量，"与当前对比"做行级 diff，回滚到任一历史版本（回滚也产生新版本）。
interface Props { template: PromptTemplateRow; onRolledBack: () => void }

export default function TemplateVersionsTab({ template, onRolledBack }: Props) {
  const versions = useAsyncData(() => getPromptTemplateVersions(template.id, OPTIONS_PAGE), [template.id, template.version], { errorText: '加载版本失败' })
  const [diffId, setDiffId] = useState<number | null>(null)
  const [expanded, setExpanded] = useState<number[]>([])
  // 点"与当前对比"时顺手展开该行，diff 就在展开区里，不用再点一次展开箭头
  const toggleDiff = (v: PromptTemplateVersionRow) => {
    setDiffId(diffId === v.id ? null : v.id)
    setExpanded((keys) => (keys.includes(v.id) ? keys : [...keys, v.id]))
  }
  const rollback = async (v: PromptTemplateVersionRow) => {
    try { await rollbackPromptTemplate(template.id, v.id); message.success(`已回滚到 v${v.version} 的内容，版本号 +1`); onRolledBack() } catch (e) { message.error(e instanceof Error ? e.message : '回滚失败') }
  }
  if (versions.error) return <ErrorState compact message={versions.error} onRetry={() => versions.reload()} />
  return (
    <Table
      size="small"
      rowKey="id"
      loading={versions.loading && !versions.data}
      dataSource={versions.data?.items ?? []}
      pagination={false}
      expandable={{
        expandedRowKeys: expanded,
        onExpandedRowsChange: (keys) => setExpanded(keys as number[]),
        expandedRowRender: (v) => (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {diffId === v.id ? (
              <div><Typography.Text type="secondary" style={{ fontSize: 12 }}>v{v.version} → 当前 v{template.version}（− 为该版本有、当前没有的行）</Typography.Text><TextDiff before={v.content} after={template.content || ''} /></div>
            ) : (
              <pre style={{ background: '#f8fafc', padding: 8, borderRadius: 6, fontSize: 12, whiteSpace: 'pre-wrap', margin: 0 }}>{v.content}</pre>
            )}
            <div>{v.variables.length ? v.variables.map((x) => <Tag key={x.name}>{x.name}{x.required ? ' *' : ''}</Tag>) : <Typography.Text type="secondary">无变量</Typography.Text>}</div>
          </div>
        ),
      }}
      columns={[
        { title: '版本', dataIndex: 'version', width: 110, render: (n: number) => <Space size={4}>v{n}{template.version === n && <Tag color="success">当前</Tag>}</Space> },
        { title: '时间', dataIndex: 'created_at', width: 170, render: (t: string) => <TimeCell value={t} /> },
        { title: '变量数', dataIndex: 'variables', width: 80, align: 'right', render: (vars: PromptTemplateVersionRow['variables']) => vars.length },
        { title: '内容长度', dataIndex: 'content', width: 90, align: 'right', render: (c: string) => c.length },
        {
          title: '操作', width: 190,
          render: (_, v) => (
            <Space size={4}>
              <Button size="small" disabled={template.version === v.version} onClick={() => toggleDiff(v)}>{diffId === v.id ? '看原文' : '与当前对比'}</Button>
              <Popconfirm title={`回滚到 v${v.version}？会生成新版本，已绑定的智能体需重新发布`} onConfirm={() => rollback(v)} disabled={template.version === v.version}>
                <Button size="small" disabled={template.version === v.version}>回滚</Button>
              </Popconfirm>
            </Space>
          ),
        },
      ]}
    />
  )
}
