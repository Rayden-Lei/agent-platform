import type { SkillRow } from '../../api'
import type { DataColumn } from '../table/DataTable'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import EnableSwitch from '../common/EnableSwitch'
import TimeCell from '../common/TimeCell'

interface Options {
  onOpen: (skill: SkillRow) => void
  onToggle: (skill: SkillRow) => Promise<unknown>
  onEdit: (skill: SkillRow) => void
  onDelete: (skill: SkillRow) => void
}

// 技能列表列定义：显示名打开详情抽屉；name 是模型 load_skill 唯一能传的标识，用等宽小号字单独成列；
// 常驻 / 按需是「正文进不进每轮提示词」的分野，用徽章而不是大色块，保持与提示词模板页同一密度。
export function buildSkillColumns({ onOpen, onToggle, onEdit, onDelete }: Options): DataColumn<SkillRow>[] {
  return [
    { key: 'id', header: 'ID', width: 64, sortable: true, cell: (r) => <span style={{ color: 'var(--fg-muted)' }}>{r.id}</span> },
    {
      key: 'display_name', header: '显示名', sortable: true, primary: true, width: 180,
      cell: (r) => (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onOpen(r) }}
          className="relative after:absolute after:-inset-y-1.5 after:content-[''] hover:underline text-left truncate max-w-full"
          style={{ color: 'var(--fg)', fontWeight: 550 }}
          title={r.display_name}
        >
          {r.display_name}
        </button>
      ),
    },
    {
      key: 'name', header: 'name', width: 156, hideOnMobile: true,
      cell: (r) => (
        <span
          className="block truncate"
          title="模型调用 load_skill 时唯一能传的标识"
          style={{ color: 'var(--fg-muted)', fontFamily: '"SF Mono",Consolas,monospace', fontSize: 11.5 }}
        >
          {r.name}
        </span>
      ),
    },
    {
      key: 'always_on', header: '加载方式', width: 96, hideOnMobile: true,
      cell: (r) => (r.always_on
        ? <Badge tone="accent" title="正文每轮都进系统提示词">常驻</Badge>
        : <Badge tone="neutral" title="只在「可用技能」目录里露 name 与描述，模型需要时才加载正文">按需</Badge>),
    },
    { key: 'is_enabled', header: '启用', width: 76, cell: (r) => <EnableSwitch checked={r.is_enabled} onToggle={() => onToggle(r)} /> },
    { key: 'version', header: '版本', width: 68, sortable: true, hideOnMobile: true, cell: (r) => `v${r.version}` },
    {
      key: 'agents_count', header: '智能体', width: 76, align: 'right', hideOnMobile: true,
      // 智能体列表不支持按技能筛选，这里只显示数量，不做跳转
      cell: (r) => (r.agents_count
        ? <span title={`${r.agents_count} 个智能体绑定了该技能`}>{r.agents_count}</span>
        : <span style={{ color: 'var(--fg-subtle)' }}>0</span>),
    },
    { key: 'updated_at', header: '更新时间', width: 168, sortable: true, hideOnMobile: true, cell: (r) => <TimeCell value={r.updated_at} /> },
    {
      key: 'actions', header: '操作', width: 150, pinRight: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button size="sm" variant="secondary" onClick={() => onEdit(r)}>编辑</Button>
          {/* 仍被智能体绑定时后端 409，提示里带绑定数 */}
          <InlineConfirm message="确定删除？仍被智能体绑定时会被拒绝" danger onConfirm={() => onDelete(r)}>
            <Button size="sm" variant="danger">删除</Button>
          </InlineConfirm>
        </span>
      ),
    },
  ]
}
