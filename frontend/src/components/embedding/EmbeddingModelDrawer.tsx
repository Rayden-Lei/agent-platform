import type { ReactNode } from 'react'
import { getEmbeddingModel, type EmbeddingModelRow } from '../../api'
import { useAsyncData } from '../../hooks/useAsyncData'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import ErrorState from '../common/ErrorState'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'

// 向量模型详情抽屉：配置信息 + 绑定它的知识库。
// 点名称先看详情、要改再点"编辑"，与对话模型页（ModelDrawer）同一口径 ——
// 原来点名称直接进编辑态，只想确认"这个模型被哪几个知识库绑着"也得先进一张表单。
interface Props {
  model: EmbeddingModelRow | null
  testing: boolean
  canManage: boolean
  indexedDims: number[]
  onClose: () => void
  onTest: (model: EmbeddingModelRow) => void
  onEdit: (model: EmbeddingModelRow) => void
}

// 配置信息的一行：左侧固定宽度标签，右侧值允许换行
function Field({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[130px_1fr] items-start gap-3 border-b border-border px-3 py-2 last:border-b-0">
      <span className="text-[12.5px] leading-5 text-muted-foreground">{label}</span>
      <span className="min-w-0 text-[13px] leading-5 text-foreground">{children}</span>
    </div>
  )
}

export default function EmbeddingModelDrawer({ model, testing, canManage, indexedDims, onClose, onTest, onEdit }: Props) {
  const id = model?.id ?? 0
  // 详情要拿"绑定它的知识库清单"，列表行里只有 kbs_count；?open= 深链时列表里也可能没有这一行
  const detail = useAsyncData(() => getEmbeddingModel(id), [id], { auto: !!model, errorText: '加载向量模型详情失败' })
  const d = detail.data ?? model
  return (
    <Drawer
      open={!!model}
      onClose={onClose}
      width={720}
      title={model ? `向量模型：${model.name}` : ''}
      extra={d && (
        <>
          <Button size="sm" variant="secondary" disabled={testing} onClick={() => onTest(d)}>{testing ? '测试中…' : '连通测试'}</Button>
          <Button size="sm" variant="primary" disabled={!canManage} onClick={() => onEdit(d)}>编辑</Button>
        </>
      )}
    >
      {d && (
        <div className="flex flex-col gap-4">
          <div className="overflow-hidden rounded-lg border border-border">
            <Field label="状态">
              <span className="inline-flex flex-wrap items-center gap-1.5">
                <StatusTag domain="enabled" value={d.is_enabled} />
                {d.kbs_count > 0 && <Badge tone="warning">{d.kbs_count} 个知识库绑定中，不能停用或删除</Badge>}
              </span>
            </Field>
            <Field label="提供商"><StatusTag domain="provider" value={d.provider} /></Field>
            <Field label="模型名"><span className="break-all font-mono text-[12.5px]">{d.model_name}</span></Field>
            <Field label="API 地址"><span className="break-all font-mono text-[12.5px]">{d.api_base}</span></Field>
            <Field label="密钥">{d.has_key ? '已配置（不回显）' : <span className="text-destructive">未配置</span>}</Field>
            <Field label="维度">
              <span className="inline-flex items-center gap-1.5">
                <span className="tabular-nums">{d.dim}</span>
                {/* 超过 pgvector 索引上限的维度检索走顺序扫描：功能正常但慢，详情里要能看出来 */}
                {!indexedDims.includes(d.dim) && <Badge tone="warning">无索引（检索走顺序扫描）</Badge>}
              </span>
            </Field>
            <Field label="单请求条数"><span className="tabular-nums">{d.request_size}</span></Field>
            <Field label="创建人">{d.created_by_username || '-'}</Field>
            <Field label="更新时间"><TimeCell value={d.updated_at} /></Field>
          </div>

          <div className="flex flex-col gap-2">
            <span className="text-[13px] font-medium text-foreground">绑定它的知识库（{d.kbs_count}）</span>
            {detail.error ? <ErrorState compact message={detail.error} onRetry={() => detail.reload()} /> : detail.data?.knowledge_bases.length ? (
              <div className="flex flex-col gap-1">
                {detail.data.knowledge_bases.map((kb) => <ResourceLink key={kb.id} type="kb" id={kb.id} name={kb.name} showIcon />)}
              </div>
            ) : <span className="text-[13px] text-muted-foreground">{detail.loading ? '加载中…' : '没有知识库绑定它'}</span>}
          </div>
        </div>
      )}
    </Drawer>
  )
}
