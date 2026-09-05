import { useState } from 'react'
import { Button, Modal, Popconfirm, Space, Table, Tag, message } from 'antd'
import { getAgentVersions, rollbackAgent, type AgentDetail, type AgentVersionRow } from '../../api'
import { usePagedList } from '../../hooks/usePagedList'
import { FieldDiff } from '../common/DiffView'
import EmptyState from '../common/EmptyState'
import JsonView from '../common/JsonView'
import TimeCell from '../common/TimeCell'
import { errorText } from '../../utils/errors'

// 版本历史：每个发布快照可展开看内容、与当前配置字段级对比、回滚（回滚也产生新版本）。
const FIELD_LABELS: Record<string, string> = {
  name: '名称', description: '描述', system_prompt: '系统提示词', model_id: '模型', params: '模型参数', kb_ids: '知识库', tool_ids: '工具',
  workflow_id: '工作流', prompt_template_id: '提示词模板', prompt_template_version: '模板版本', prompt_variables: '模板变量',
}
const SNAPSHOT_FIELDS = Object.keys(FIELD_LABELS)

interface Props { agent: AgentDetail; onChanged: () => void }

export default function AgentVersionsTab({ agent, onChanged }: Props) {
  const list = usePagedList<AgentVersionRow>((params) => getAgentVersions(agent.id, params), { pageSize: 10, emptyText: <EmptyState description="还没有发布版本；发布后会生成快照，可在此对比与回滚。" /> })
  const [compare, setCompare] = useState<AgentVersionRow | null>(null)
  const current = Object.fromEntries(SNAPSHOT_FIELDS.map((k) => [k, (agent as unknown as Record<string, unknown>)[k]]))

  const rollback = async (v: AgentVersionRow) => {
    try {
      await rollbackAgent(agent.id, v.id)
      message.success(`已回滚到 v${v.version}，生成新版本`)
      list.reload()
      onChanged()
    } catch (e) { message.error(errorText(e, '回滚失败')) }
  }

  return (
    <>
      <Table
        size="small"
        rowKey="id"
        {...list.tableProps}
        expandable={{ expandedRowRender: (v) => <JsonView title="快照" value={v.snapshot} maxHeight={320} /> }}
        columns={[
          { title: '版本', dataIndex: 'version', width: 100, render: (v: number) => <Space size={4}>v{v}{v === agent.version && <Tag color="green">当前</Tag>}</Space> },
          { title: '发布时间', dataIndex: 'created_at', width: 180, render: (v: string) => <TimeCell value={v} /> },
          { title: '模型', width: 100, render: (_, v) => `#${(v.snapshot as { model_id?: number }).model_id ?? '-'}` },
          { title: '模板', width: 120, render: (_, v) => { const s = v.snapshot as { prompt_template_id?: number; prompt_template_version?: number }; return s.prompt_template_id ? `#${s.prompt_template_id} v${s.prompt_template_version}` : '手填' } },
          {
            title: '操作', width: 200,
            render: (_, v) => (
              <Space size={4}>
                <Button size="small" onClick={() => setCompare(v)}>与当前对比</Button>
                <Popconfirm title={`回滚到 v${v.version}？当前配置会被覆盖并生成新版本`} onConfirm={() => rollback(v)}>
                  <Button size="small">回滚</Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <Modal title={compare ? `v${compare.version} 与当前配置的差异` : ''} open={!!compare} onCancel={() => setCompare(null)} footer={null} width={860} destroyOnHidden>
        {compare && <FieldDiff before={compare.snapshot as Record<string, unknown>} after={current} labels={FIELD_LABELS} />}
      </Modal>
    </>
  )
}
