import type { ReactNode } from 'react'
import { Copy, FileCode2 } from 'lucide-react'
import { toast } from 'sonner'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import TimeCell from '../common/TimeCell'
import type { SkillRow } from '../../api'

// 技能详情：列表不下发正文，这里看到的是全文。正文用 <pre> 直接铺在抽屉里（抽屉本身滚动），
// 不再套一层内部滚动容器 —— 页面上出现第二条滚动条是使用者明确反对的。
interface Props {
  skill: SkillRow | null
  onClose: () => void
  onEdit: (skill: SkillRow) => void
}

// 小于 1KB 按字节显示：脚本只有几十字节时「0.0KB」没有信息量
const kbText = (bytes?: number | null) => (bytes == null ? '-' : bytes < 1024 ? bytes + 'B' : (bytes / 1024).toFixed(1) + 'KB')

export default function SkillDrawer({ skill, onClose, onEdit }: Props) {
  if (!skill) return null
  const copyName = async () => {
    try {
      await navigator.clipboard.writeText(skill.name)
      toast.success('已复制 name')
    } catch {
      toast.error('复制失败，请手动选中')
    }
  }
  const resources = skill.resources ?? []

  return (
    <Drawer
      open={!!skill}
      onClose={onClose}
      width={760}
      title={skill.display_name}
      description={'v' + skill.version + ' · ' + (skill.always_on ? '常驻（正文每轮进提示词）' : '按需加载（模型调 load_skill 取正文）')}
      extra={<Button size="sm" variant="secondary" onClick={() => onEdit(skill)}>编辑</Button>}
      footer={<Button variant="primary" size="md" onClick={onClose}>关闭</Button>}
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={skill.is_enabled ? 'success' : 'neutral'}>{skill.is_enabled ? '已启用' : '已停用'}</Badge>
          <Badge tone={skill.always_on ? 'accent' : 'neutral'}>{skill.always_on ? '常驻' : '按需'}</Badge>
          <Badge tone="neutral">{(skill.agents_count ?? 0) + ' 个智能体绑定'}</Badge>
          {resources.length > 0 && <Badge tone="info">{resources.length + ' 个附带资源'}</Badge>}
        </div>

        <div className="flex flex-col gap-2 rounded-lg border border-border px-3 py-2.5">
          <Field label="name">
            <span className="inline-flex items-center gap-1.5 min-w-0">
              <code className="truncate" style={{ fontFamily: '"SF Mono",Consolas,monospace', fontSize: 12 }}>{skill.name}</code>
              <button type="button" onClick={copyName} className="rounded p-0.5 text-muted-foreground hover:bg-accent" aria-label="复制 name">
                <Copy className="size-3.5" />
              </button>
            </span>
          </Field>
          <Field label="描述">{skill.description}</Field>
          <Field label="创建人">{skill.created_by_username || (skill.created_by ? '#' + skill.created_by : '-')}</Field>
          <Field label="创建时间"><TimeCell value={skill.created_at} /></Field>
          <Field label="更新时间"><TimeCell value={skill.updated_at} /></Field>
        </div>

        {resources.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-muted-foreground">脚本资源（模型调 run_skill_script 执行）</span>
            <ul className="m-0 flex list-none flex-col gap-1 rounded-lg border border-border px-2 py-1.5 p-0">
              {resources.map((r) => (
                <li key={r.name} className="flex items-center gap-2">
                  <FileCode2 className="size-3.5 shrink-0 text-muted-foreground" />
                  <code className="min-w-0 flex-1 truncate text-[12.5px]" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>{r.name}</code>
                  {r.missing ? <Badge tone="danger">文件缺失</Badge> : <span className="shrink-0 text-[12px] text-muted-foreground">{kbText(r.size)}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-col gap-1.5">
          <span className="text-[12px] font-medium text-muted-foreground">正文（Markdown 原文）</span>
          <pre
            className="m-0 whitespace-pre-wrap break-words rounded-lg border border-border px-3 py-2.5 text-[12.5px] leading-relaxed"
            style={{ fontFamily: '"SF Mono",Consolas,monospace', color: 'var(--fg)' }}
          >
            {skill.content || ''}
          </pre>
        </div>
      </div>
    </Drawer>
  )
}

// 详情里的一行「标签 : 值」，标签定宽保证多行对齐，行高与列表页一致（不留大间距）
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start gap-3 text-[13px]">
      <span className="w-[68px] shrink-0 text-[12px]" style={{ color: 'var(--fg-muted)' }}>{label}</span>
      <span className="min-w-0 flex-1 break-words">{children}</span>
    </div>
  )
}
