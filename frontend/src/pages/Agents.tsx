import { useEffect, useMemo, useState } from 'react'
import { Button, Table, message } from 'antd'
import { PlusOutlined, RobotOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { batchAgents, deleteAgent, listAgents, listModels, OPTIONS_PAGE, publishAgent, type AgentRow, type ModelRow } from '../api'
import { usePagedList } from '../hooks/usePagedList'
import { useQueryState } from '../hooks/useQueryState'
import { useBatchAction } from '../hooks/useBatchAction'
import ListPage from '../components/layout/ListPage'
import PageHeader from '../components/layout/PageHeader'
import EmptyState from '../components/common/EmptyState'
import BatchActionBar from '../components/common/BatchActionBar'
import BatchResultModal from '../components/common/BatchResultModal'
import AgentFilters, { type AgentFilterValues } from '../components/agents/AgentFilters'
import AgentForm from '../components/agents/AgentForm'
import { buildAgentColumns } from '../components/agents/agentColumns'
import { errorText } from '../utils/errors'

const DEFAULTS: AgentFilterValues = { q: undefined, status: undefined, model_id: undefined }

// 智能体列表：筛选（URL 同步）+ 服务端排序 + 行选择批量发布 / 删除；名称进详情页，模型 / 模板可跳转。
export default function Agents() {
  const navigate = useNavigate()
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const [models, setModels] = useState<ModelRow[]>([])
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<AgentRow | null>(null)
  const list = usePagedList<AgentRow>(listAgents, {
    filters,
    selectable: true,
    emptyText: <EmptyState description="还没有智能体。先配置模型，再创建智能体并发布，之后才能对话。" action={{ label: '新增智能体', onClick: () => { setEditing(null); setFormOpen(true) } }} />,
  })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload() })

  useEffect(() => { listModels(OPTIONS_PAGE).then((p) => setModels(p.items)).catch(() => setModels([])) }, [])

  const act = async (fn: () => Promise<unknown>, fallback: string) => {
    try { await fn(); list.reload() } catch (e) { message.error(errorText(e, fallback)) }
  }
  const columns = useMemo(() => buildAgentColumns({
    sortProps: list.sortProps,
    onChat: (a) => navigate(`/chat?agent=${a.id}`),
    onPublish: (a) => act(() => publishAgent(a.id), '发布失败'),
    onEdit: (a) => { setEditing(a); setFormOpen(true) },
    onDelete: (a) => act(() => deleteAgent(a.id), '删除失败'),
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [list.sortProps])
  const nameOf = (id: number) => list.items.find((a) => a.id === id)?.name

  return (
    <ListPage
      header={<PageHeader icon={<RobotOutlined />} title="智能体管理" description="提示词、模型、工具与知识库的组合；发布后才能对话，发布会生成版本快照。" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setFormOpen(true) }}>新增智能体</Button>} />}
      filters={<AgentFilters values={filters} onChange={setFilters} onReset={resetFilters} onRefresh={list.reload} models={models} loading={list.loading} />}
      batch={
        <BatchActionBar
          count={list.selectedKeys.length}
          onClear={list.clearSelection}
          running={batch.running}
          actions={[
            { key: 'publish', label: '批量发布', confirm: `发布选中的 ${list.selectedKeys.length} 个智能体？每个都会生成新版本`, run: () => batch.run(() => batchAgents(list.selectedKeys, 'publish'), '已发布') },
            { key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${list.selectedKeys.length} 个智能体？会话与运行记录会一并删除`, run: () => batch.run(() => batchAgents(list.selectedKeys, 'delete'), '已删除') },
          ]}
        />
      }
    >
      <Table rowKey="id" {...list.tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      <AgentForm open={formOpen} editing={editing} onClose={() => setFormOpen(false)} onSaved={list.reload} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={nameOf} />
    </ListPage>
  )
}
