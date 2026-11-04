import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/shadcn/tabs'
import Drawer from '../../ui/Drawer'
import Badge from '../../ui/Badge'
import EmptyState from '../../common/EmptyState'
import type { TraceHit, TraceStep } from '../../../api'
import type { Msg } from '../../chat/types'
import HitCard from '../../trace/HitCard'
import TraceStepList from '../../trace/TraceStepList'
import { formatCost, formatNumber } from '../../../utils/format'
import { formatDuration } from '../../../utils/time'

// 调试回答的详情（docs/15 3.4）：概览（耗时、成本、Token、运行记录）/ 召回（按知识库分组的命中与分数）/
// 实际发给模型的系统提示词 / 调用链（每次模型调用与工具执行的入参与结果）。数据都来自这条回答的流式事件，不另发请求。
const SOURCE_LABEL: Record<string, string> = { inline: '编辑器当前内容', draft: '已保存的草稿', live: '线上版本' }

// 概览里的"字段名 + 值"一行：左侧固定宽度的标签，右侧值允许换行与省略
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[96px_1fr] items-start gap-3 border-b border-border px-3 py-2 last:border-b-0">
      <span className="text-[12.5px] leading-5 text-muted-foreground">{label}</span>
      <span className="min-w-0 text-[13px] leading-5 text-foreground">{children}</span>
    </div>
  )
}

function Recall({ steps, contents }: { steps: TraceStep[]; contents: Map<number, string> }) {
  if (!steps.length) return <EmptyState description="这个配置没有绑定知识库，本轮没有检索" />
  return (
    <div className="flex flex-col gap-4">
      {steps.map((step) => {
        const hits = (step.output || []) as TraceHit[]
        return (
          <div key={step.id} className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[13px] font-medium text-foreground">{step.name}</span>
              <span className="text-[12px] text-muted-foreground">
                查询「{step.input?.query}」· 候选 {step.meta?.candidate_count ?? 0} · 返回 {hits.length} · {formatDuration(step.duration_ms)}
              </span>
              {step.meta?.acl_rejected > 0 && <Badge tone="warning">鉴权剔除 {step.meta.acl_rejected}</Badge>}
              {step.meta?.kb_denied && <Badge tone="warning">当前角色无权检索这个库</Badge>}
              {step.meta?.rerank_mode && <Badge tone="neutral">{step.meta.rerank_mode === 'model' ? '重排模型' : '词法重排'}</Badge>}
            </div>
            {hits.length ? (
              <div className="flex flex-col gap-2">
                {hits.map((h, i) => (
                  <HitCard key={h.chunk_id} rank={i + 1} docName={h.doc_name} docId={h.doc_id} score={h.score} content={contents.get(h.chunk_id)}
                    vectorScore={h.vector_score} keywordScore={h.keyword_score} rerankScore={h.rerank_score} location={h.location} />
                ))}
              </div>
            ) : <span className="text-[13px] text-muted-foreground">没有命中片段</span>}
          </div>
        )
      })}
    </div>
  )
}

export default function DebugDetailDrawer({ msg, onClose }: { msg: Msg | null; onClose: () => void }) {
  const steps = msg?.trace ?? []
  // 检索步骤的命中不带正文，按 chunk_id 从这条回答的引用里补
  const contents = new Map((msg?.citations ?? []).map((c) => [c.chunk_id, c.content ?? '']))
  const m = msg?.metrics
  const retrieveSteps = steps.filter((s) => s.type === 'retrieve')
  return (
    <Drawer title="调试详情" open={!!msg} onClose={onClose} width={720}>
      {msg && (
        <Tabs defaultValue="overview" className="gap-3">
          <TabsList className="w-full">
            <TabsTrigger value="overview">概览</TabsTrigger>
            <TabsTrigger value="recall">召回（{retrieveSteps.length}）</TabsTrigger>
            <TabsTrigger value="prompt">提示词</TabsTrigger>
            <TabsTrigger value="trace">调用链（{steps.length}）</TabsTrigger>
          </TabsList>

          <TabsContent value="overview">
            <div className="overflow-hidden rounded-lg border border-border">
              <Field label="调试对象">{m ? SOURCE_LABEL[m.config_source] ?? m.config_source : '-'}</Field>
              <Field label="模型">{m?.model_name ?? '-'}</Field>
              <Field label="首字">{m?.first_token_ms != null ? formatDuration(m.first_token_ms) : '无文本输出'}</Field>
              <Field label="总耗时">{m ? formatDuration(m.latency_ms) : '-'}</Field>
              <Field label="检索耗时">{m ? formatDuration(m.retrieval_ms) : '-'}</Field>
              <Field label="成本">{formatCost(m?.cost)}</Field>
              <Field label="Token">
                {msg.usage?.total_tokens
                  ? `${formatNumber(msg.usage.total_tokens)}（输入 ${formatNumber(msg.usage.prompt_tokens ?? 0)} / 输出 ${formatNumber(msg.usage.completion_tokens ?? 0)}）`
                  : '-'}
              </Field>
              <Field label="运行记录">
                {msg.runId ? <Link to={`/runs/${msg.runId}`} className="text-primary hover:underline">#{msg.runId}（来源：调试，运营统计不计）</Link> : '-'}
              </Field>
            </div>
          </TabsContent>

          <TabsContent value="recall">
            <Recall steps={retrieveSteps} contents={contents} />
          </TabsContent>

          <TabsContent value="prompt">
            {msg.prompt ? (
              <div className="flex flex-col gap-2">
                <span className="text-[12px] text-muted-foreground">
                  实际发给模型的系统提示词（含注入的参考片段）；另带 {msg.prompt.history_count} 条历史消息
                </span>
                <pre className="m-0 max-h-[560px] overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-secondary p-3 text-[13px] leading-relaxed text-foreground">{msg.prompt.system_prompt}</pre>
              </div>
            ) : <EmptyState description="没有收到提示词（请求在建流前就失败了）" />}
          </TabsContent>

          <TabsContent value="trace">
            <TraceStepList steps={steps} />
          </TabsContent>
        </Tabs>
      )}
    </Drawer>
  )
}
