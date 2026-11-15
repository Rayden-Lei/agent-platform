import { useEffect, useState } from 'react'
import { Info } from 'lucide-react'
import { Label } from '@/components/shadcn/label'
import { Textarea } from '@/components/shadcn/textarea'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
// 弹窗只认这几个字段：列表页传 WorkflowRow、编辑器传画布当前状态，两边各自映射一次，
// 不让组件依赖某一个页面的行类型（编辑器里的"草稿修订号"与"节点数"来自画布，不是列表行）
export interface WorkflowPublishTarget {
  name: string
  draftVersion: number // 草稿修订号（每保存一次 +1）
  publishedVersion: number | null // 线上版本号；从未发布为 null
  nodeCount: number // 草稿的节点数
}

// 工作流发布确认弹窗（docs/15 FR-075）：发布说明 + 这次发布要带走什么。
// 与智能体的 PublishModal 不同，这里不做字段级差异：工作流的对外行为就是一张图，
// 用文字说清"草稿修订号 → 新版本号、节点数变化"比把两份 graph JSON 摆出来更能看懂；
// 完整的图对比在编辑器的测试运行里做（那里能直接跑）。
// 请求由页面注入（组件不发请求），失败时页面提示、弹窗保持打开便于重试。
interface Props {
  target: WorkflowPublishTarget | null // 非空即打开
  onClose: () => void
  onPublish: (note?: string) => Promise<void>
}

export default function WorkflowPublishModal({ target, onClose, onPublish }: Props) {
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => { if (target) setNote('') }, [target])
  if (!target) return null

  // 从未发布过：这次发布就是 v1，没有"线上版本"可比
  const firstPublish = target.publishedVersion === null
  const submit = async () => {
    setSubmitting(true)
    try { await onPublish(note.trim() || undefined) } catch { /* 页面已提示错误，弹窗保持打开 */ } finally { setSubmitting(false) }
  }

  return (
    <Modal
      open
      size="lg"
      title={firstPublish ? `发布：${target.name}（首次发布）` : `发布：${target.name}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" size="md" onClick={onClose}>取消</Button>
          <Button variant="primary" size="md" disabled={submitting} onClick={submit}>
            {submitting ? '发布中…' : '发布'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-start gap-2 rounded-lg border border-border bg-secondary px-3 py-2">
          <Info className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="text-[12.5px] leading-snug text-foreground">
            {firstPublish
              ? '发布后这个工作流才能被运行、作为对话目标、挂定时任务或被 API Key 调用。'
              : `当前线上是 v${target.publishedVersion}；发布后草稿（修订 ${target.draftVersion}）成为新版本，定时任务与 API 调用方随即改用新版本。`}
          </span>
        </div>

        <div className="grid grid-cols-3 gap-2 text-[13px]">
          <div className="rounded-lg border border-border px-3 py-2">
            <div className="text-[11.5px] text-muted-foreground">草稿修订</div>
            <div className="mt-0.5">v{target.draftVersion}</div>
          </div>
          <div className="rounded-lg border border-border px-3 py-2">
            <div className="text-[11.5px] text-muted-foreground">线上版本</div>
            <div className="mt-0.5">{firstPublish ? '未发布' : `v${target.publishedVersion}`}</div>
          </div>
          <div className="rounded-lg border border-border px-3 py-2">
            <div className="text-[11.5px] text-muted-foreground">节点数</div>
            <div className="mt-0.5">{target.nodeCount}</div>
          </div>
        </div>

        <div>
          <Label htmlFor="wf-publish-note" className="text-[12.5px]">发布说明（可选，进版本历史）</Label>
          <Textarea id="wf-publish-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={200}
            placeholder="这次改了什么，例如：新增审核节点、调整知识库检索条数" className="mt-1.5 min-h-[72px] text-[13px]" />
        </div>

        {!firstPublish && (
          <p className="m-0 text-[12px] leading-snug text-muted-foreground">
            草稿与线上一致时发布会返回"无需发布"，不会生成空版本。发布后可随时在详情页的版本历史里回滚。
          </p>
        )}
      </div>
    </Modal>
  )
}
