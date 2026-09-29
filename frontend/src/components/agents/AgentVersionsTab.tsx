import { useState } from 'react'
import { Button, Modal, Popconfirm, Space, Table, Tag, Tooltip, message } from 'antd'
import { getAgentVersions, restoreAgentVersion, rollbackAgent, type AgentDetail, type AgentVersionRow } from '../../api'
import { usePagedList } from '../../hooks/usePagedList'
import { FieldDiff } from '../common/DiffView'
import EmptyState from '../common/EmptyState'
import JsonView from '../common/JsonView'
import TimeCell from '../common/TimeCell'
import { errorText } from '../../utils/errors'

// 版本历史（发布语义，docs/15 3.2）：每个发布版本是不可变快照。两种操作语义不同 ——
// 恢复到草稿：草稿 = 该版本，线上不变（日常改版用）；回滚上线：用该版本生成新版本并立即上线，草稿不动（线上出事一键止血）。
const FIELD_LABELS: Record<string, string> = {
  name: '名称', description: '描述', system_prompt: '系统提示词', model_id: '模型', params: '模型参数', kb_ids: '知识库', tool_ids: '工具',
  workflow_id: '工作流', prompt_template_id: '提示词模板', prompt_template_version: '模板版本', prompt_variables: '模板变量',
}
const SNAPSHOT_FIELDS = Object.keys(FIELD_LABELS)

interface Props { agent: AgentDetail; onChanged: () => void }

export default function AgentVersionsTab({ agent, onChanged }: Props) {
  const list = usePagedList<AgentVersionRow>((params) => getAgentVersions(agent.id, params), { pageSize: 10, emptyText: <EmptyState description="还没有发布版本；发布后会生成快照，可在此对比、恢复到草稿或回滚上线。" /> })
  const [compare, setCompare] = useState<AgentVersionRow | null>(null)
  const draft = Object.fromEntries(SNAPSHOT_FIELDS.map((k) => [k, (agent as unknown as Record<string, unknown>)[k]]))

  const done = () => { list.reload(); onChanged() }
  const restore = async (v: AgentVersionRow) => {
    try { await restoreAgentVersion(agent.id, v.id); message.success(`草稿已恢复为 v${v.version}，发布后对外生效`); done() } catch (e) { message.error(errorText(e, '恢复失败')) }
  }
  const rollback = async (v: AgentVersionRow) => {
    try {
      const r = await rollbackAgent(agent.id, v.id)
      message.success(r.publish_result === 'unchanged' ? '线上已是这个版本的内容' : `已回滚上线，线上为 v${r.published_version}（内容同 v${v.version}）`)
      done()
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
          { title: '版本', dataIndex: 'version', width: 110, render: (n: number, v) => <Space size={4}>v{n}{v.is_live && <Tag color="green">线上</Tag>}</Space> },
          { title: '发布时间', dataIndex: 'created_at', width: 170, render: (t: string) => <TimeCell value={t} /> },
          { title: '发布人', dataIndex: 'created_by_username', width: 100, render: (u: string | null) => u || '-' },
          { title: '说明', dataIndex: 'note', ellipsis: true, render: (n: string | null) => n || '-' },
          { title: '模型', dataIndex: 'model_name', width: 140, ellipsis: true, render: (m: string | null, v) => m || `#${(v.snapshot as { model_id?: number }).model_id ?? '-'}（已删除）` },
          { title: '模板', dataIndex: 'prompt_template_name', width: 120, ellipsis: true, render: (t: string | null, v) => (t ? `${t} v${(v.snapshot as { prompt_template_version?: number }).prompt_template_version ?? ''}` : '手填') },
          {
            title: '操作', width: 280,
            render: (_, v) => (
              <Space size={4}>
                <Button size="small" onClick={() => setCompare(v)}>与草稿对比</Button>
                <Popconfirm title={`草稿恢复为 v${v.version}？当前草稿会被覆盖，线上不变`} onConfirm={() => restore(v)}>
                  <Button size="small">恢复到草稿</Button>
                </Popconfirm>
                <Tooltip title={v.is_live ? '已是线上版本' : undefined}>
                  <Popconfirm title={`用 v${v.version} 生成新版本并立即上线？草稿不变`} onConfirm={() => rollback(v)} disabled={v.is_live}>
                    <Button size="small" danger disabled={v.is_live}>回滚上线</Button>
                  </Popconfirm>
                </Tooltip>
              </Space>
            ),
          },
        ]}
      />
      <Modal title={compare ? `v${compare.version} 与当前草稿的差异` : ''} open={!!compare} onCancel={() => setCompare(null)} footer={null} width={860} destroyOnHidden>
        {compare && <FieldDiff before={compare.snapshot as Record<string, unknown>} after={draft} labels={FIELD_LABELS} />}
      </Modal>
    </>
  )
}
