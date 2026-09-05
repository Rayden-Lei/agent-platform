import { useMemo, useState } from 'react'
import { Button, Select, Table, message } from 'antd'
import { PlusOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { batchModels, deleteModel, getModel, getModelUsage, listModels, testModel, toggleModel, type ModelRow } from '../api'
import { useAuth } from '../store/auth'
import { usePagedList } from '../hooks/usePagedList'
import { useQueryState } from '../hooks/useQueryState'
import { useBatchAction } from '../hooks/useBatchAction'
import { useOpenParam } from '../hooks/useOpenParam'
import { useAsyncData } from '../hooks/useAsyncData'
import { useSystemStatus } from '../hooks/useSystemStatus'
import { statusOptions } from '../constants/status'
import ListPage from '../components/layout/ListPage'
import PageHeader from '../components/layout/PageHeader'
import FilterBar from '../components/layout/FilterBar'
import SearchInput from '../components/common/SearchInput'
import EmptyState from '../components/common/EmptyState'
import BatchActionBar from '../components/common/BatchActionBar'
import BatchResultModal from '../components/common/BatchResultModal'
import ModelForm from '../components/models/ModelForm'
import ModelDrawer from '../components/models/ModelDrawer'
import { buildModelColumns } from '../components/models/modelColumns'
import { errorText } from '../utils/errors'

type Filters = { q?: string; provider?: string; is_enabled?: string }
const DEFAULTS: Filters = { q: undefined, provider: undefined, is_enabled: undefined }
const ENABLED_OPTIONS = [{ value: 'true', label: '启用' }, { value: 'false', label: '停用' }]

// 模型管理：筛选 / 排序 / 启停开关 / 批量启停删除 / 连通测试 / 详情抽屉（?open= 深链）；熔断状态来自共享的系统状态轮询（30 秒）。
export default function Models() {
  const role = useAuth((s) => s.user?.role)
  const canManage = role === 'admin'
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<ModelRow | null>(null)
  const [current, setCurrent] = useState<ModelRow | null>(null)
  const [testingId, setTestingId] = useState<number | null>(null)
  const { status, refresh } = useSystemStatus(30000)
  const breakers = useMemo(() => Object.fromEntries((status?.model_breakers ?? []).map((b) => [b.model_id, b])), [status])
  const usage = useAsyncData(async () => Object.fromEntries((await getModelUsage({ days: 7 })).items.map((u) => [u.model_id, u])), [])
  const list = usePagedList<ModelRow>(listModels, { filters, selectable: canManage, emptyText: <EmptyState description="还没有接入模型。新增一个 OpenAI 兼容端点后，智能体才能对话。" action={canManage ? { label: '新增模型', onClick: () => { setEditing(null); setFormOpen(true) } } : undefined} /> })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload() })
  // ?open= 深链：列表可能还没加载完或该模型不在当前筛选内，直接取详情打开
  useOpenParam((id) => { const row = list.items.find((m) => m.id === id); if (row) setCurrent(row); else getModel(id).then(setCurrent).catch((e) => message.error(errorText(e, '模型不存在或无权查看'))) })

  // 连通测试：结果直接提示；成功会关闭该模型的熔断，测完刷新一次系统状态
  const onTest = async (record: ModelRow) => {
    setTestingId(record.id)
    try {
      const res = await testModel(record.id)
      if (res.data.ok) message.success(`连通正常：${res.data.reply || ''}`)
      else message.error(`连通失败：${res.data.error || '未知错误'}`)
    } catch (e) { message.error(errorText(e, '测试失败')) } finally { setTestingId(null); refresh() }
  }
  const onToggle = async (m: ModelRow) => { await toggleModel(m.id); list.reload() }
  const onDelete = async (m: ModelRow) => { try { await deleteModel(m.id); list.reload() } catch (e) { message.error(errorText(e, '删除失败')) } }
  const onEdit = (m: ModelRow) => { setEditing(m); setFormOpen(true) }
  const columns = useMemo(() => buildModelColumns({ sortProps: list.sortProps, breakers, usage: usage.data ?? {}, testingId, canManage, onOpen: setCurrent, onToggle, onTest, onEdit, onDelete }), [list.sortProps, breakers, usage.data, testingId, canManage]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ListPage
      header={<PageHeader icon={<ThunderboltOutlined />} title="模型管理" description="LLM 接入配置；价格用于成本统计，连续失败会触发熔断，连通测试成功即恢复。" extra={canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setFormOpen(true) }}>新增模型</Button>} />}
      filters={
        <FilterBar onReset={resetFilters} onRefresh={() => { list.reload(); usage.reload(true); refresh() }} loading={list.loading}>
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索名称 / 模型名" />
          <Select allowClear placeholder="提供商" style={{ width: 130 }} value={filters.provider} onChange={(v) => setFilters({ provider: v })} options={statusOptions('provider')} />
          <Select allowClear placeholder="状态" style={{ width: 100 }} value={filters.is_enabled} onChange={(v) => setFilters({ is_enabled: v })} options={ENABLED_OPTIONS} />
        </FilterBar>
      }
      batch={<BatchActionBar count={list.selectedKeys.length} onClear={list.clearSelection} running={batch.running} actions={[
        { key: 'enable', label: '批量启用', run: () => batch.run(() => batchModels(list.selectedKeys, 'enable'), '已启用') },
        { key: 'disable', label: '批量停用', confirm: `停用选中的 ${list.selectedKeys.length} 个模型？绑定它们的智能体将无法对话`, run: () => batch.run(() => batchModels(list.selectedKeys, 'disable'), '已停用') },
        { key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${list.selectedKeys.length} 个模型？`, run: () => batch.run(() => batchModels(list.selectedKeys, 'delete'), '已删除') },
      ]} />}
    >
      <Table rowKey="id" {...list.tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      <ModelForm open={formOpen} editing={editing} onClose={() => setFormOpen(false)} onSaved={() => { list.reload(); setCurrent(null) }} />
      <ModelDrawer model={current} breaker={current ? breakers[current.id] : undefined} testing={testingId === current?.id} canManage={canManage} onClose={() => setCurrent(null)} onTest={onTest} onEdit={onEdit} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((m) => m.id === id)?.name} />
    </ListPage>
  )
}
