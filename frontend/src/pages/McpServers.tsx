import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Plug, Plus } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import {
  batchMcpServers, deleteMcpServer, disableAllMcpTools, enableAllMcpTools, getMcpServer, listMcpServers,
  syncAndEnableMcpServer, syncMcpServer, toggleMcpServer, toggleTool,
  type McpServerDetail, type McpServerRow,
} from '../api'
import { usePagedList } from '../hooks/usePagedList'
import { useQueryState } from '../hooks/useQueryState'
import { useBatchAction } from '../hooks/useBatchAction'
import { useOpenParam } from '../hooks/useOpenParam'
import ListPage from '../components/layout/ListPage'
import PageHeader from '../components/layout/PageHeader'
import FilterBar from '../components/layout/FilterBar'
import SearchInput from '../components/common/SearchInput'
import EmptyState from '../components/common/EmptyState'
import BatchActionBar from '../components/common/BatchActionBar'
import BatchResultModal from '../components/common/BatchResultModal'
import McpServerForm from '../components/mcp/McpServerForm'
import McpServerDrawer from '../components/mcp/McpServerDrawer'
import { buildMcpColumns } from '../components/mcp/mcpColumns'
import DataTable from '../components/table/DataTable'
import Button from '../components/ui/Button'
import { errorText } from '../utils/errors'

type Filters = { q?: string; is_enabled?: string }
const DEFAULTS: Filters = { q: undefined, is_enabled: undefined }
const ENABLED_OPTIONS = [{ value: 'true', label: '启用' }, { value: 'false', label: '停用' }]

// MCP 连接器（docs/17 §5）：登记外部 MCP server，把它的 tools 同步成本地工具。
// 同步出来的工具就是 tools 表的一行（type='mcp'），因此在工具页能直接看到、能绑到智能体上，
// 也走同一道执行闸门与审计 —— 这一页只负责"服务器"这一层（地址、凭据、白名单、同步）。
export default function McpServers() {
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<McpServerRow | null>(null)
  const [current, setCurrent] = useState<McpServerDetail | null>(null)
  // 同步要连远端，可能几秒：记下正在同步的那一行，按钮显示"同步中…"
  const [syncingId, setSyncingId] = useState<number | null>(null)
  // 一键启用 / 停用全部工具：单行操作，不加 spinner 就看不出点没点上
  const [bulkRunning, setBulkRunning] = useState(false)
  const openCreate = () => { setEditing(null); setFormOpen(true) }
  const empty = (
    <EmptyState
      description="还没有 MCP 服务器。登记一个外部 MCP server 后，它的工具会同步进平台，智能体可以像用普通工具一样用。"
      action={{ label: '新增服务器', onClick: openCreate }}
    />
  )
  const list = usePagedList<McpServerRow>(listMcpServers, { filters, selectable: true, emptyText: empty })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload() })

  // 刷新详情失败时不能静默关掉抽屉：用户会以为"服务器刚被谁删了"。
  // 只在 404（确实不存在）时关闭，其余错误提示一句并保留现有内容。
  const reloadAll = () => {
    list.reload()
    if (!current) return
    getMcpServer(current.id)
      .then(setCurrent)
      .catch((e) => {
        const status = (e as { response?: { status?: number } })?.response?.status
        if (status === 404) setCurrent(null)
        else toast.error(errorText(e, '刷新服务器详情失败'))
      })
  }

  const openDetail = async (r: McpServerRow) => {
    try { setCurrent(await getMcpServer(r.id)) } catch (e) { toast.error(errorText(e, '加载服务器失败')) }
  }

  // 同步结果要逐项说清：新建几个、更新几个、停用几个。
  // 只报"同步成功"的话，用户不知道新工具默认是停用的，会以为没生效。
  const onSync = async (r: McpServerRow | McpServerDetail) => {
    setSyncingId(r.id)
    try {
      const res = await syncMcpServer(r.id)
      const parts = [`共 ${res.total} 个远端工具`]
      if (res.created) parts.push(`新建 ${res.created} 个（默认停用）`)
      if (res.updated) parts.push(`更新 ${res.updated} 个`)
      if (res.disabled) parts.push(`停用 ${res.disabled} 个（远端已移除）`)
      toast.success('同步完成：' + parts.join('，'))
      await reloadAll()
    } catch (e) {
      // 502 带远端的具体原因（连不上 / 协议错），原样上屏比"同步失败"有用
      toast.error(errorText(e, '同步失败'))
      list.reload()
    } finally {
      setSyncingId(null)
    }
  }

  // 同步 + 一键启用：新建服务器后的标准动作。两步并一步，省掉"同步完发现工具全是停用的"这一愣
  const onSyncAndEnable = async (r: McpServerRow | McpServerDetail) => {
    setSyncingId(r.id)
    try {
      const res = await syncAndEnableMcpServer(r.id)
      toast.success(`同步完成：共 ${res.tools_total} 个工具，已启用 ${res.enabled_tools} 个` +
        (res.disabled ? `，停用 ${res.disabled} 个（远端已移除）` : ''))
      await reloadAll()
    } catch (e) {
      toast.error(errorText(e, '同步失败'))
    } finally {
      setSyncingId(null)
    }
  }

  // 一键启用 / 停用该服务器的全部工具
  const onBulkToggle = async (enabled: boolean) => {
    if (!current) return
    setBulkRunning(true)
    try {
      const res = enabled ? await enableAllMcpTools(current.id) : await disableAllMcpTools(current.id)
      toast.success(res.changed ? `已${enabled ? '启用' : '停用'} ${res.changed} 个工具` : '状态已经是目标值，没有变化')
      await reloadAll()
    } catch (e) {
      toast.error(errorText(e, enabled ? '批量启用失败' : '批量停用失败'))
    } finally {
      setBulkRunning(false)
    }
  }

  // 单个工具开关：与工具页读的是同一份 is_enabled，不存在状态歧义
  const onToggleTool = async (toolId: number) => {
    try {
      await toggleTool(toolId)
      if (current) setCurrent(await getMcpServer(current.id))
      list.reload()
    } catch (e) {
      toast.error(errorText(e, '切换失败'))
    }
  }

  const onToggle = async (r: McpServerRow) => { await toggleMcpServer(r.id); reloadAll() }
  const onDelete = async (r: McpServerRow) => {
    try { await deleteMcpServer(r.id); if (current?.id === r.id) setCurrent(null); list.reload() } catch (e) { toast.error(errorText(e, '删除失败')) }
  }
  const onEdit = (r: McpServerRow) => { setEditing(r); setFormOpen(true) }

  // 深链 /mcp-servers?open=3 打开详情抽屉
  useOpenParam((id) => {
    getMcpServer(id).then(setCurrent).catch((e) => toast.error(errorText(e, '服务器不存在')))
  })

  const columns = useMemo(
    () => buildMcpColumns({ onOpen: openDetail, onToggle, onSync, onEdit, onDelete, syncingId }),
    [syncingId],  // eslint-disable-line react-hooks/exhaustive-deps
  )

  return (
    <ListPage
      header={
        <PageHeader
          icon={<Plug />}
          title="MCP 连接器"
          description="登记外部 MCP server，把它的工具同步进平台。只支持 HTTP / SSE 传输；同步出的工具默认停用，需要人工启用后才对模型可见。"
          extra={<Button variant="primary" size="md" icon={<Plus />} onClick={openCreate}>新增服务器</Button>}
        />
      }
      filters={
        <FilterBar onReset={resetFilters} onRefresh={list.reload} loading={list.loading}
          activeCount={Object.values(filters).filter(Boolean).length}>
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索名称 / 描述" />
          <Select value={filters.is_enabled ?? 'all'} onValueChange={(v) => setFilters({ is_enabled: v === 'all' ? undefined : v })}>
            <SelectTrigger size="sm" className="h-8 w-[100px] text-[13px]" aria-label="状态"><SelectValue placeholder="状态" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              {ENABLED_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </FilterBar>
      }
      batch={<BatchActionBar count={list.selectedKeys.length} onClear={list.clearSelection} running={batch.running} actions={[
        { key: 'enable', label: '批量启用', run: () => batch.run(() => batchMcpServers(list.selectedKeys, 'enable'), '已启用') },
        { key: 'disable', label: '批量停用', confirm: `停用选中的 ${list.selectedKeys.length} 个服务器？它们的工具也会一并停用`, run: () => batch.run(() => batchMcpServers(list.selectedKeys, 'disable'), '已停用') },
        { key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${list.selectedKeys.length} 个服务器？同步出的工具会保留但全部停用`, run: () => batch.run(() => batchMcpServers(list.selectedKeys, 'delete'), '已删除') },
      ]} />}
    >
      <DataTable
        columns={columns}
        rows={list.items}
        rowKey={(r) => r.id}
        loading={list.loading}
        error={list.error}
        empty={empty}
        onRetry={list.reload}
        page={list.page}
        pageSize={list.pageSize}
        total={list.total}
        onPageChange={list.load}
        sort={list.sort}
        onSortChange={list.setSort}
        selectable
        selectedKeys={list.selectedKeys}
        onSelectionChange={list.setSelectedKeys}
      />
      <McpServerForm open={formOpen} editing={editing} onClose={() => setFormOpen(false)} onSaved={reloadAll} />
      <McpServerDrawer
        server={current}
        onClose={() => setCurrent(null)}
        onEdit={(s) => { setCurrent(null); onEdit(s) }}
        onSync={onSync}
        onSyncAndEnable={onSyncAndEnable}
        onToggleTool={onToggleTool}
        onBulkToggle={onBulkToggle}
        syncing={syncingId === current?.id}
        bulkRunning={bulkRunning}
      />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((s) => s.id === id)?.name} />
    </ListPage>
  )
}
