import type { ReactNode } from 'react'
import { cn } from 'cn'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/shadcn/tabs'
import { Skeleton } from '@/components/shadcn/skeleton'
import { getPromptTemplate, getPromptTemplateAgents, type PromptTemplateRow } from '../../api'
import { useAsyncData } from '../../hooks/useAsyncData'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import ErrorState from '../common/ErrorState'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import EmptyState from '../common/EmptyState'
import TemplateVersionsTab from './TemplateVersionsTab'
import TemplateRenderTab from './TemplateRenderTab'

// 模板详情抽屉：内容与变量 / 版本历史（对比、回滚）/ 绑定的智能体（标出用的是旧版）/ 渲染预览；编辑在头部。
// 多段内容用页签分开，抽屉整高、正文滚动。
interface Props { template: PromptTemplateRow | null; onClose: () => void; onEdit: (t: PromptTemplateRow) => void; onChanged: () => void }

// 定义列表里的一个字段：wide 占满一行（描述这类长内容）
function Cell({ label, wide, children }: { label: string; wide?: boolean; children: ReactNode }) {
  return (
    <div className={cn('flex flex-col gap-0.5 bg-card px-3 py-2', wide && 'col-span-3')}>
      <dt className="text-[12.5px] text-muted-foreground">{label}</dt>
      <dd className="m-0 text-[13.5px]">{children}</dd>
    </div>
  )
}

export default function TemplateDrawer({ template, onClose, onEdit, onChanged }: Props) {
  const id = template?.id ?? 0
  const detail = useAsyncData(() => getPromptTemplate(id), [id, template?.version], { auto: !!template, errorText: '加载模板失败' })
  const agents = useAsyncData(() => getPromptTemplateAgents(id), [id, template?.version], { auto: !!template, errorText: '加载绑定智能体失败' })
  const t = detail.data
  return (
    <Drawer
      open={!!template}
      title={template ? `模板：${template.name}` : ''}
      onClose={onClose}
      width={760}
      extra={t && <Button variant="primary" onClick={() => onEdit(t)}>编辑</Button>}
    >
      {detail.error ? <ErrorState compact message={detail.error} onRetry={() => detail.reload()} /> : !t ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-3 w-1/2" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <Tabs defaultValue="content" className="gap-3">
          <TabsList variant="line" className="w-full justify-start">
            <TabsTrigger value="content" className="flex-none px-2.5">内容</TabsTrigger>
            <TabsTrigger value="versions" className="flex-none px-2.5">版本历史</TabsTrigger>
            <TabsTrigger value="agents" className="flex-none px-2.5">绑定智能体（{agents.data?.length ?? t.agents_count ?? 0}）</TabsTrigger>
            <TabsTrigger value="render" className="flex-none px-2.5">渲染预览</TabsTrigger>
          </TabsList>

          <TabsContent value="content" className="flex flex-col gap-3">
            <dl className="m-0 grid grid-cols-3 gap-px overflow-hidden rounded-lg border border-border bg-border">
              <Cell label="版本">v{t.version}</Cell>
              <Cell label="创建人">{t.created_by_username || '-'}</Cell>
              <Cell label="更新时间"><TimeCell value={t.updated_at} /></Cell>
              <Cell label="描述" wide>{t.description || '-'}</Cell>
            </dl>

            <div className="flex flex-col gap-2">
              <span className="text-[13px] font-medium">变量声明（{t.variables.length}）</span>
              {t.variables.length ? (
                <div className="overflow-hidden rounded-lg border border-border">
                  <table className="w-full border-collapse text-[13.5px]">
                    <thead className="bg-secondary">
                      <tr>
                        <th className="w-[160px] px-2 py-1.5 text-left text-[12.5px] font-medium text-muted-foreground">变量</th>
                        <th className="px-2 py-1.5 text-left text-[12.5px] font-medium text-muted-foreground">说明</th>
                        <th className="w-[160px] px-2 py-1.5 text-left text-[12.5px] font-medium text-muted-foreground">默认值</th>
                      </tr>
                    </thead>
                    <tbody>
                      {t.variables.map((v) => (
                        <tr key={v.name} className="border-t border-border">
                          <td className="px-2 py-1.5">{v.name}{v.required && <span className="text-destructive"> *</span>}</td>
                          <td className="px-2 py-1.5">{v.description || '-'}</td>
                          <td className="px-2 py-1.5">
                            {v.default
                              ? <code className="rounded bg-secondary px-1.5 py-0.5 text-[12.5px]">{v.default}</code>
                              : '-'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <span className="text-[12.5px] text-muted-foreground">无变量，内容按原文使用</span>}
            </div>

            <div className="flex flex-col gap-2">
              <span className="text-[13px] font-medium">内容</span>
              <pre className="m-0 whitespace-pre-wrap rounded-lg border border-border bg-secondary p-3 text-[13px] leading-relaxed text-foreground">{t.content}</pre>
            </div>
          </TabsContent>

          <TabsContent value="versions">
            <TemplateVersionsTab template={t} onRolledBack={() => { detail.reload(); agents.reload(); onChanged() }} />
          </TabsContent>

          <TabsContent value="agents">
            {agents.error ? <ErrorState compact message={agents.error} onRetry={() => agents.reload()} /> : agents.data?.length ? (
              <div className="flex flex-col gap-1.5">
                <span className="text-[12.5px] text-muted-foreground">智能体保存草稿时按模板当前版本渲染；标"旧版"的要重新保存草稿并发布，才用到当前 v{t.version}。</span>
                {agents.data.map((a) => (
                  <span key={a.id} className="flex flex-wrap items-center gap-1.5">
                    <ResourceLink type="agent" id={a.id} name={a.name} showIcon /> <StatusTag domain="agent" value={a.status} />
                    {a.prompt_template_version !== null && <Badge>v{a.prompt_template_version}</Badge>}
                    {a.outdated && (
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <span><Badge tone="warning">旧版</Badge></span>
                        </TooltipTrigger>
                        <TooltipContent>草稿用的是旧模板版本，重新保存草稿并发布后生效</TooltipContent>
                      </Tooltip>
                    )}
                  </span>
                ))}
              </div>
            ) : <EmptyState description="没有智能体绑定该模板；在智能体表单里打开「使用模板」即可" />}
          </TabsContent>

          <TabsContent value="render">
            <TemplateRenderTab template={t} />
          </TabsContent>
        </Tabs>
      )}
    </Drawer>
  )
}
