import { useEffect, useMemo, useState } from 'react'
import { Button, Table, message } from 'antd'
import { PlusOutlined, RobotOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { batchAgents, deleteAgent, getAgent, listAgents, listModels, OPTIONS_PAGE, publishAgent, type AgentDetail, type AgentRow, type ModelRow } from '../api'
import { usePagedList } from '../hooks/usePagedList'
import { useQueryState } from '../hooks/useQueryState'
import { useBatchAction } from '../hooks/useBatchAction'
import ListPage from '../components/layout/ListPage'
import PageHeader from '../components/layout/PageHeader'
import EmptyState from '../components/common/EmptyState'
import BatchActionBar from '../components/common/BatchActionBar'
import BatchResultModal from '../components/common/BatchResultModal'
import AgentFilters, { type AgentFilterValues } from '../components/agents/AgentFilters'
import PublishModal from '../components/agents/PublishModal'
import { buildAgentColumns } from '../components/agents/agentColumns'
import { errorText } from '../utils/errors'

const DEFAULTS: AgentFilterValues = { q: undefined, status: undefined, model_id: undefined, tool_id: undefined, kb_id: undefined, prompt_template_id: undefined }

// 智能体列表：筛选（URL 同步）+ 服务端排序 + 行选择批量发布 / 下线 / 删除；名称进详情页，新增与编辑进装配页，
// 行上的发布先取详情再开发布弹窗（差异与预检要用草稿、线上两份快照）。
export default function Agents() {
  const navigate = useNavigate()
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const [models, setModels] = useState<ModelRow[]>([])
  const [publishing, setPublishing] = useState<AgentDetail | null>(null)
  const list = usePagedList<AgentRow>(listAgents, {
    filters,
    selectable: true,
    emptyText: <EmptyState description="还没有智能体。先配置模型，再创建智能体并发布，之后才能对话。" action={{ label: '新增智能体', onClick: () => navigate('/agents/new') }} />,
  })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload() })

  useEffect(() => { listModels(OPTIONS_PAGE).then((p) => setModels(p.items)).catch(() => setModels([])) }, [])

  const act = async (fn: () => Promise<unknown>, fallback: string) => {
    try { await fn(); list.reload() } catch (e) { message.error(errorText(e, fallback)) }
  }
  const openPublish = (a: AgentRow) => getAgent(a.id).then(setPublishing).catch((e) => message.error(errorText(e, '加载智能体失败')))
  const onPublish = async (note?: string) => {
    if (!publishing) return
    try {
      const r = await publishAgent(publishing.id, note)
      message.success(r.publish_result === 'unchanged' ? '草稿与线上一致，无需发布' : `已发布，线上为 v${r.published_version}`)
      setPublishing(null)
      list.reload()
    } catch (e) { message.error(errorText(e, '发布失败')); throw e }
  }
  const columns = useMemo(() => buildAgentColumns({
    sortProps: list.sortProps,
    onChat: (a) => navigate(`/chat?agent=${a.id}`),
    onPublish: openPublish,
    onEdit: (a) => navigate(`/agents/${a.id}/edit`),
    onDelete: (a) => act(() => deleteAgent(a.id), '删除失败'),
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [list.sortProps])
  const nameOf = (id: number) => list.items.find((a) => a.id === id)?.name

  return (
    <ListPage
      header={<PageHeader icon={<RobotOutlined />} title="智能体管理" description="提示词、模型、工具与知识库的组合。保存只改草稿，发布后才对外生效；每次发布生成一个可回滚的版本。" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/agents/new')}>新增智能体</Button>} />}
      filters={<AgentFilters values={filters} onChange={setFilters} onReset={resetFilters} onRefresh={list.reload} models={models} loading={list.loading} />}
      batch={
        <BatchActionBar
          count={list.selectedKeys.length}
          onClear={list.clearSelection}
          running={batch.running}
          actions={[
            { key: 'publish', label: '批量发布', confirm: `发布选中的 ${list.selectedKeys.length} 个智能体？草稿有改动的生成新版本并上线，与线上一致的不变`, run: () => batch.run(() => batchAgents(list.selectedKeys, 'publish'), '已发布') },
            { key: 'offline', label: '批量下线', confirm: `下线选中的 ${list.selectedKeys.length} 个智能体？对话、API Key 与工作流都不能再调用，重新发布即恢复`, run: () => batch.run(() => batchAgents(list.selectedKeys, 'offline'), '已下线') },
            { key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${list.selectedKeys.length} 个智能体？会话与运行记录会一并删除`, run: () => batch.run(() => batchAgents(list.selectedKeys, 'delete'), '已删除') },
          ]}
        />
      }
    >
      <Table rowKey="id" {...list.tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      <PublishModal agent={publishing} onClose={() => setPublishing(null)} onPublish={onPublish} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={nameOf} />
    </ListPage>
  )
}
