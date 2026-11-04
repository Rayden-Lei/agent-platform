import { useState } from 'react'
import { toast } from 'sonner'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { getPromptTemplateVersions, rollbackPromptTemplate, OPTIONS_PAGE, type PromptTemplateRow, type PromptTemplateVersionRow } from '../../api'
import { useAsyncData } from '../../hooks/useAsyncData'
import { Skeleton } from '@/components/shadcn/skeleton'
import { TextDiff } from '../common/DiffView'
import ErrorState from '../common/ErrorState'
import EmptyState from '../common/EmptyState'
import TimeCell from '../common/TimeCell'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import InlineConfirm from '../ui/InlineConfirm'

// 版本历史页签：展开看该版本内容与变量，"与当前对比"做行级 diff，回滚到任一历史版本（回滚也产生新版本）。
// 每行下面挂一段可展开的详情，本质不是表格（没有可比的多列数据），用原生行列表渲染。
interface Props { template: PromptTemplateRow; onRolledBack: () => void }

export default function TemplateVersionsTab({ template, onRolledBack }: Props) {
  const versions = useAsyncData(() => getPromptTemplateVersions(template.id, OPTIONS_PAGE), [template.id, template.version], { errorText: '加载版本失败' })
  const [diffId, setDiffId] = useState<number | null>(null)
  const [expanded, setExpanded] = useState<number[]>([])
  const toggleRow = (id: number) => setExpanded((keys) => (keys.includes(id) ? keys.filter((k) => k !== id) : [...keys, id]))
  // 点"与当前对比"时顺手展开该行，diff 就在展开区里，不用再点一次展开箭头
  const toggleDiff = (v: PromptTemplateVersionRow) => {
    setDiffId(diffId === v.id ? null : v.id)
    setExpanded((keys) => (keys.includes(v.id) ? keys : [...keys, v.id]))
  }
  const rollback = async (v: PromptTemplateVersionRow) => {
    try { await rollbackPromptTemplate(template.id, v.id); toast.success(`已回滚到 v${v.version} 的内容，版本号 +1`); onRolledBack() } catch (e) { toast.error(e instanceof Error ? e.message : '回滚失败') }
  }
  if (versions.error) return <ErrorState compact message={versions.error} onRetry={() => versions.reload()} />
  const items = versions.data?.items ?? []
  if (versions.loading && !versions.data) {
    return (
      <div className="flex flex-col gap-2">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex items-center gap-3">
            <Skeleton className="h-3 w-14" />
            <Skeleton className="h-3 w-32" />
            <Skeleton className="h-3 flex-1" />
          </div>
        ))}
      </div>
    )
  }
  if (!items.length) return <EmptyState description="还没有历史版本：每次保存内容或变量都会留下一个版本" />

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      {items.map((v, i) => {
        const isCurrent = template.version === v.version
        const open = expanded.includes(v.id)
        return (
          <div key={v.id} className={i ? 'border-t border-border' : undefined}>
            <div className="flex flex-wrap items-center gap-3 px-3 py-2 text-[13.5px]">
              <button
                type="button"
                aria-label={open ? '收起' : '展开'}
                aria-expanded={open}
                onClick={() => toggleRow(v.id)}
                className="flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
              </button>
              <span className="flex items-center gap-1.5 font-medium">v{v.version}{isCurrent && <Badge tone="success">当前</Badge>}</span>
              <span className="text-[12.5px] text-muted-foreground"><TimeCell value={v.created_at} /></span>
              <span className="text-[12.5px] text-muted-foreground">变量 {v.variables.length}</span>
              <span className="text-[12.5px] text-muted-foreground">{v.content.length} 字符</span>
              <span className="ml-auto flex items-center gap-1.5">
                <Button size="sm" variant="secondary" disabled={isCurrent} onClick={() => toggleDiff(v)}>{diffId === v.id ? '看原文' : '与当前对比'}</Button>
                {isCurrent ? (
                  <Button size="sm" variant="secondary" disabled>回滚</Button>
                ) : (
                  <InlineConfirm message={`回滚到 v${v.version}？会生成新版本，已绑定的智能体重新保存草稿并发布后才用到它`} onConfirm={() => rollback(v)}>
                    <Button size="sm" variant="secondary">回滚</Button>
                  </InlineConfirm>
                )}
              </span>
            </div>

            {open && (
              <div className="flex flex-col gap-2 border-t border-border bg-secondary/60 px-3 py-2.5">
                {diffId === v.id ? (
                  <div className="flex flex-col gap-1.5">
                    <span className="text-[12.5px] text-muted-foreground">v{v.version} → 当前 v{template.version}（− 为该版本有、当前没有的行）</span>
                    <TextDiff before={v.content} after={template.content || ''} />
                  </div>
                ) : (
                  <pre className="m-0 whitespace-pre-wrap rounded-md bg-card p-2 text-[12.5px] leading-relaxed text-foreground">{v.content}</pre>
                )}
                <div className="flex flex-wrap items-center gap-1.5">
                  {v.variables.length
                    ? v.variables.map((x) => <Badge key={x.name}>{x.name}{x.required ? ' *' : ''}</Badge>)
                    : <span className="text-[12.5px] text-muted-foreground">无变量</span>}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
