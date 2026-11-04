import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { CircleCheck, CircleX, Play, TriangleAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { runWorkflow, type WorkflowRow, type WorkflowRunResult } from '../../api'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import JsonView from '../common/JsonView'
import { errorText } from '../../utils/errors'

// 手动运行工作流：输入 JSON 或文本，结果按成功 / 待审核 / 失败展示，并可跳到本次运行记录看节点日志与审核。
interface Props { workflow: WorkflowRow | null; onClose: () => void; onDone?: () => void }

export default function RunWorkflowModal({ workflow, onClose, onDone }: Props) {
  const [input, setInput] = useState('')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<WorkflowRunResult | null>(null)
  useEffect(() => { if (workflow) { setInput(''); setResult(null) } }, [workflow])

  const run = async () => {
    if (!workflow) return
    setRunning(true)
    try {
      setResult(await runWorkflow(workflow.id, { input }))
      onDone?.()
    } catch (e) {
      toast.error(errorText(e, '运行失败'))
    } finally {
      setRunning(false)
    }
  }

  return (
    <Modal
      open={!!workflow}
      size="lg"
      title={workflow ? `运行工作流：${workflow.name}` : ''}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" size="md" onClick={onClose}>关闭</Button>
          <Button variant="primary" size="md" icon={<Play />} disabled={running} onClick={run}>{running ? '运行中…' : '运行'}</Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <p className="m-0 text-[12.5px] leading-relaxed text-muted-foreground">
          输入会作为起始节点的 input；JSON 字符串会被解析为对象，其他内容按文本传入。运行同步等待结束，长流程请到运行记录页跟踪。
        </p>
        <textarea
          rows={3}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder='{"expression": "2+3*4"}'
          className="w-full resize-y rounded-lg border border-border-strong bg-transparent px-3 py-2 font-mono text-[13px] leading-relaxed outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
        />

        {result && (
          <div className="flex flex-col gap-2.5">
            {result.status === 'success' && (
              <div className="flex items-center gap-2 rounded-lg border border-[rgba(22,163,74,.35)] bg-[rgba(22,163,74,.10)] px-3 py-2">
                <CircleCheck className="size-3.5 text-[#15803D]" />
                <span className="text-[13px]">运行成功</span>
              </div>
            )}
            {result.status === 'awaiting_review' && (
              <div className="flex items-start gap-2 rounded-lg border border-[rgba(217,119,6,.35)] bg-[rgba(217,119,6,.10)] px-3 py-2">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-[#B45309]" />
                <div className="text-[13px]">
                  <div>等待人工审核</div>
                  <div className="text-muted-foreground">流程停在人工审核节点，到运行记录里通过或驳回后继续。</div>
                </div>
              </div>
            )}
            {result.status !== 'success' && result.status !== 'awaiting_review' && (
              <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2">
                <CircleX className="mt-0.5 size-3.5 shrink-0 text-destructive" />
                <div className="min-w-0 text-[13px]">
                  <div className="text-destructive">运行失败</div>
                  {result.error && <div className="break-words text-muted-foreground">{result.error}</div>}
                </div>
              </div>
            )}

            {result.run_id && (
              <div className="text-[13px]">
                运行记录：<Link to={`/runs/${result.run_id}`} className="text-primary hover:underline">#{result.run_id}</Link>
                <span className="text-muted-foreground">（节点日志、耗时与 token 在详情页）</span>
              </div>
            )}
            {result.status === 'success' && <JsonView value={result.output} maxHeight={200} />}
            {result.status === 'awaiting_review' && <JsonView value={result.interrupt} maxHeight={160} />}
            {result.steps?.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {result.steps.map((s, i) => <Badge key={i} tone="neutral">{s}</Badge>)}
              </div>
            )}
          </div>
        )}
      </div>
    </Modal>
  )
}
