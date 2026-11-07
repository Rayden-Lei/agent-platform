import { useEffect, useState, type ReactNode } from 'react'
import { Copy, FileCode2 } from 'lucide-react'
import { toast } from 'sonner'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import TimeCell from '../common/TimeCell'
import { previewSkill, type SkillPreview, type SkillRow } from '../../api'
import { errorText } from '../../utils/errors'

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
  // 模型视角预览：技能写错最贵的是试错成本（以往要绑到智能体上跑一轮才知道 descriptions
  // 会不会被模型想到、always_on 占多少上下文）。这里点开抽屉就顺手取一次，纯本地计算不花 token
  const [preview, setPreview] = useState<SkillPreview | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const skillId = skill?.id
  useEffect(() => {
    if (!skillId) { setPreview(null); setPreviewError(null); return }
    let alive = true
    previewSkill(skillId)
      .then((p) => { if (alive) { setPreview(p); setPreviewError(null) } })
      .catch((e) => { if (alive) { setPreview(null); setPreviewError(errorText(e, '预览加载失败')) } })
    return () => { alive = false }
  }, [skillId])

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
          {(skill.agents?.length ?? 0) > 0 && (
            <Field label="被绑定">
              <span className="flex flex-wrap gap-1">
                {skill.agents!.map((a) => (
                  <span key={a.id} className="rounded bg-[var(--bg-soft)] px-1.5 py-0.5 text-[11.5px]">
                    {a.name}
                    {a.status !== 'published' && <span className="ml-1 text-muted-foreground">（未发布）</span>}
                  </span>
                ))}
              </span>
            </Field>
          )}
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

        {/* 模型视角：这个技能进提示词的样子 + 每轮开销 + 写错法的提示。
            正文在下面的「正文」段完整展示，这里只回答"模型看到什么、要花多少上下文" */}
        <div className="flex flex-col gap-2 rounded-lg border border-border px-3 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[12px] font-medium">模型看到的</span>
            {preview && (
              <span className="text-[11.5px] text-muted-foreground" title="按字符量粗估，不同厂商分词略有差异">
                每轮约 {preview.per_turn_overhead} token
              </span>
            )}
          </div>
          {previewError && <p className="m-0 text-[12.5px] text-destructive">{previewError}</p>}
          {!preview && !previewError && <p className="m-0 text-[12.5px] text-muted-foreground">加载中…</p>}
          {preview && (
            <>
              {preview.in_catalog ? (
                <div className="flex flex-col gap-1">
                  <span className="text-[11.5px] text-muted-foreground">
                    每轮进提示词的只有这一行（模型据此决定要不要加载）：
                  </span>
                  <code className="rounded bg-[var(--bg-soft)] px-2 py-1 text-[12px] break-words" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>
                    {preview.catalog_line}
                  </code>
                </div>
              ) : (
                <div className="flex flex-col gap-1">
                  <span className="text-[11.5px] text-muted-foreground">
                    常驻：下面这段正文每轮都会被拼进系统提示（约 {preview.tokens.always_on_body} token）
                  </span>
                  <pre className="m-0 max-h-[160px] overflow-auto whitespace-pre-wrap break-words rounded bg-[var(--bg-soft)] px-2 py-1 text-[12px] leading-relaxed" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>
                    {preview.always_on_body}
                  </pre>
                </div>
              )}
              <div className="text-[11.5px] text-muted-foreground">
                模型调 load_skill 时拿到 {preview.tokens.load_skill_result} token 的全文
                （{preview.content_bytes < 1024 ? preview.content_bytes + 'B' : (preview.content_bytes / 1024).toFixed(1) + 'KB'}）
              </div>
              {preview.advice.length > 0 && (
                <ul className="m-0 flex list-disc flex-col gap-0.5 pl-4 text-[12px] text-muted-foreground">
                  {preview.advice.map((a) => <li key={a}>{a}</li>)}
                </ul>
              )}
            </>
          )}
        </div>

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
