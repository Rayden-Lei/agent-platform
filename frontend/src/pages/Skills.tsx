import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { BookOpen, Plus, Upload } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import { batchSkills, deleteSkill, getSkill, getSkillStats, listSkills, updateSkill, type ParsedSkill, type SkillInput, type SkillRow } from '../api'
import { usePagedList } from '../hooks/usePagedList'
import { useQueryState } from '../hooks/useQueryState'
import { useBatchAction } from '../hooks/useBatchAction'
import { useAsyncData } from '../hooks/useAsyncData'
import { useOpenParam } from '../hooks/useOpenParam'
import ListPage from '../components/layout/ListPage'
import PageHeader from '../components/layout/PageHeader'
import FilterBar from '../components/layout/FilterBar'
import SearchInput from '../components/common/SearchInput'
import EmptyState from '../components/common/EmptyState'
import BatchActionBar from '../components/common/BatchActionBar'
import BatchResultModal from '../components/common/BatchResultModal'
import SkillForm from '../components/skills/SkillForm'
import SkillDrawer from '../components/skills/SkillDrawer'
import SkillImportModal from '../components/skills/SkillImportModal'
import { buildSkillColumns } from '../components/skills/skillColumns'
import DataTable from '../components/table/DataTable'
import Button from '../components/ui/Button'
import { errorText } from '../utils/errors'

type Filters = { q?: string; always_on?: string; is_enabled?: string }
const DEFAULTS: Filters = { q: undefined, always_on: undefined, is_enabled: undefined }
const ALWAYS_ON_OPTIONS = [{ value: 'false', label: '按需加载' }, { value: 'true', label: '常驻' }]
const ENABLED_OPTIONS = [{ value: 'true', label: '启用' }, { value: 'false', label: '停用' }]

// 技能管理（docs/17 §4）：技能的「操作手册」与提示词模板的「人设」分工不同 ——
// 只把 name + description 放进模型目录，需要时它调 load_skill 取正文；开启常驻才每轮都进提示词。
// 技能没有发布流程：这里的修改立刻对线上智能体生效，所以列表页也把这件事写在页头说明里。
export default function Skills() {
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<SkillRow | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  // 导入解析出的字段：只用于新建态预填，使用者确认后走正常保存（不落库、不另开写入路径）
  const [prefill, setPrefill] = useState<ParsedSkill | null>(null)
  const [current, setCurrent] = useState<SkillRow | null>(null)
  const list = usePagedList<SkillRow>(listSkills, {
    filters,
    selectable: true,
    emptyText: <EmptyState description="还没有技能。把某类任务的固定做法写成 Markdown 操作手册，绑定到智能体后模型会在需要时自己加载。" action={{ label: '新增技能', onClick: () => { setEditing(null); setPrefill(null); setFormOpen(true) } }} />,
  })
  const stats = useAsyncData(() => getSkillStats(), [], { errorText: '加载技能统计失败' })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload(); stats.reload(true) })

  const reloadAll = () => { list.reload(); stats.reload(true) }

  // 列表不下发正文，编辑与查看详情前先取详情
  const openDetail = async (r: SkillRow) => {
    try { setCurrent(r.content !== undefined ? r : await getSkill(r.id)) } catch (e) { toast.error(errorText(e, '加载技能失败')) }
  }
  const openEdit = async (r: SkillRow) => {
    // 编辑已有技能时清掉导入预填：否则上一次导入的字段会盖住这次编辑
    try { setPrefill(null); setEditing(r.content !== undefined ? r : await getSkill(r.id)); setFormOpen(true) } catch (e) { toast.error(errorText(e, '加载技能失败')) }
  }
  const onDelete = async (r: SkillRow) => {
    try { await deleteSkill(r.id); reloadAll() } catch (e) { toast.error(errorText(e, '删除失败')) }
  }
  // 列内启停开关：列表项没有正文，PUT 是整体覆盖，先取详情再原样回写，只翻 is_enabled
  const onToggle = async (r: SkillRow) => {
    const detail = r.content !== undefined ? r : await getSkill(r.id)
    const payload: SkillInput = {
      name: detail.name,
      display_name: detail.display_name,
      description: detail.description,
      content: detail.content || '',
      always_on: detail.always_on,
      is_enabled: !detail.is_enabled,
    }
    await updateSkill(detail.id, payload)
    reloadAll()
  }
  // 深链 /skills?open=3（ResourceLink 跳过来）打开详情抽屉
  useOpenParam((id) => {
    const row = list.items.find((s) => s.id === id)
    if (row) openDetail(row)
    else getSkill(id).then(setCurrent).catch((e) => toast.error(errorText(e, '技能不存在')))
  })

  const columns = useMemo(() => buildSkillColumns({ onOpen: openDetail, onToggle, onEdit: openEdit, onDelete }), []) // eslint-disable-line react-hooks/exhaustive-deps

  const openCreate = () => { setEditing(null); setPrefill(null); setFormOpen(true) }
  // 导入：解析成功后接着打开新建弹窗，字段已填好，使用者确认后才写库
  const onImported = (parsed: ParsedSkill) => {
    setImportOpen(false)
    setEditing(null)
    setPrefill(parsed)
    setFormOpen(true)
  }
  const empty = <EmptyState description="还没有技能。把某类任务的固定做法写成 Markdown 操作手册，绑定到智能体后模型会在需要时自己加载。" action={{ label: '新增技能', onClick: openCreate }} />

  return (
    <ListPage
      header={
        <PageHeader
          icon={<BookOpen />}
          title="技能"
          description="技能的正文是「操作手册」，只在模型判断需要时才加载；提示词模板是「人设」，两者分开。这里的修改立刻对线上智能体生效，不需要重新发布。"
          tags={stats.data ? <span className="text-[12.5px]" style={{ color: 'var(--fg-muted)' }}>共 {stats.data.total} 个，启用 {stats.data.enabled} 个</span> : undefined}
          extra={
            <>
              <Button variant="secondary" size="md" icon={<Upload />} onClick={() => setImportOpen(true)}>导入 SKILL.md</Button>
              <Button variant="primary" size="md" icon={<Plus />} onClick={openCreate}>新增技能</Button>
            </>
          }
        />
      }
      filters={
        <FilterBar onReset={resetFilters} onRefresh={() => { list.reload(); stats.reload(true) }} loading={list.loading}
        activeCount={Object.values(filters).filter(Boolean).length}>
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索名称 / 显示名" />
          <Select value={filters.always_on ?? 'all'} onValueChange={(v) => setFilters({ always_on: v === 'all' ? undefined : v })}>
            <SelectTrigger size="sm" className="h-8 w-[110px] text-[13px]" aria-label="加载方式"><SelectValue placeholder="加载方式" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部加载方式</SelectItem>
              {ALWAYS_ON_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
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
        {
          key: 'delete', label: '批量删除', danger: true,
          confirm: `删除选中的 ${list.selectedKeys.length} 个技能？仍被智能体绑定的会失败并列在结果里`,
          run: () => batch.run(() => batchSkills(list.selectedKeys), '已删除'),
        },
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
      <SkillForm open={formOpen} editing={editing} prefill={prefill} onClose={() => { setFormOpen(false); setPrefill(null) }} onSaved={reloadAll} />
      <SkillImportModal open={importOpen} onClose={() => setImportOpen(false)} onParsed={onImported} />
      <SkillDrawer skill={current} onClose={() => setCurrent(null)} onEdit={(s) => { setCurrent(null); openEdit(s) }} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((s) => s.id === id)?.display_name} />
    </ListPage>
  )
}
