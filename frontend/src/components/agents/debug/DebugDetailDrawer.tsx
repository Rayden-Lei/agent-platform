import { Descriptions, Drawer, Empty, Space, Tabs, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import type { TraceHit, TraceStep } from '../../../api'
import type { Msg } from '../../chat/types'
import HitCard from '../../trace/HitCard'
import TraceStepList from '../../trace/TraceStepList'
import { formatCost, formatNumber } from '../../../utils/format'
import { formatDuration } from '../../../utils/time'

// 调试回答的详情（docs/15 3.4）：概览（耗时、成本、Token、运行记录）/ 召回（按知识库分组的命中与分数）/
// 实际发给模型的系统提示词 / 调用链（每次模型调用与工具执行的入参与结果）。数据都来自这条回答的流式事件，不另发请求。
const SOURCE_LABEL: Record<string, string> = { inline: '编辑器当前内容', draft: '已保存的草稿', live: '线上版本' }

function Recall({ steps, contents }: { steps: TraceStep[]; contents: Map<number, string> }) {
  if (!steps.length) return <Empty description="这个配置没有绑定知识库，本轮没有检索" />
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {steps.map((step) => {
        const hits = (step.output || []) as TraceHit[]
        return (
          <div key={step.id}>
            <Space size={8} wrap style={{ marginBottom: 8 }}>
              <Typography.Text strong>{step.name}</Typography.Text>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>查询「{step.input?.query}」· 候选 {step.meta?.candidate_count ?? 0} · 返回 {hits.length} · {formatDuration(step.duration_ms)}</Typography.Text>
              {step.meta?.acl_rejected > 0 && <Tag color="warning">鉴权剔除 {step.meta.acl_rejected}</Tag>}
              {step.meta?.kb_denied && <Tag color="warning">当前角色无权检索这个库</Tag>}
              {step.meta?.rerank_mode && <Tag>{step.meta.rerank_mode === 'model' ? '重排模型' : '词法重排'}</Tag>}
            </Space>
            {hits.length ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {hits.map((h, i) => (
                  <HitCard key={h.chunk_id} rank={i + 1} docName={h.doc_name} docId={h.doc_id} score={h.score} content={contents.get(h.chunk_id)}
                    vectorScore={h.vector_score} keywordScore={h.keyword_score} rerankScore={h.rerank_score} location={h.location} />
                ))}
              </div>
            ) : <Typography.Text type="secondary">没有命中片段</Typography.Text>}
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
  return (
    <Drawer title="调试详情" open={!!msg} onClose={onClose} width={720} destroyOnHidden>
      {msg && (
        <Tabs size="small" items={[
          {
            key: 'overview', label: '概览', children: (
              <Descriptions size="small" bordered column={2} items={[
                { key: 'source', label: '调试对象', children: m ? SOURCE_LABEL[m.config_source] ?? m.config_source : '-' },
                { key: 'model', label: '模型', children: m?.model_name ?? '-' },
                { key: 'first', label: '首字', children: m?.first_token_ms != null ? formatDuration(m.first_token_ms) : '无文本输出' },
                { key: 'latency', label: '总耗时', children: m ? formatDuration(m.latency_ms) : '-' },
                { key: 'retrieval', label: '检索耗时', children: m ? formatDuration(m.retrieval_ms) : '-' },
                { key: 'cost', label: '成本', children: formatCost(m?.cost) },
                { key: 'tokens', label: 'Token', span: 2, children: msg.usage?.total_tokens ? `${formatNumber(msg.usage.total_tokens)}（输入 ${formatNumber(msg.usage.prompt_tokens ?? 0)} / 输出 ${formatNumber(msg.usage.completion_tokens ?? 0)}）` : '-' },
                { key: 'run', label: '运行记录', span: 2, children: msg.runId ? <Link to={`/runs/${msg.runId}`}>#{msg.runId}（来源：调试，运营统计不计）</Link> : '-' },
              ]} />
            ),
          },
          { key: 'recall', label: `召回（${steps.filter((s) => s.type === 'retrieve').length}）`, children: <Recall steps={steps.filter((s) => s.type === 'retrieve')} contents={contents} /> },
          {
            key: 'prompt', label: '提示词', children: msg.prompt ? (
              <div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>实际发给模型的系统提示词（含注入的参考片段）；另带 {msg.prompt.history_count} 条历史消息</Typography.Text>
                <pre style={{ background: '#f8fafc', border: '1px solid #e5e7eb', borderRadius: 6, padding: 12, whiteSpace: 'pre-wrap', margin: '8px 0 0', fontSize: 13 }}>{msg.prompt.system_prompt}</pre>
              </div>
            ) : <Empty description="没有收到提示词（请求在建流前就失败了）" />,
          },
          { key: 'trace', label: `调用链（${steps.length}）`, children: <TraceStepList steps={steps} /> },
        ]} />
      )}
    </Drawer>
  )
}
