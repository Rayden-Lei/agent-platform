import { CircleCheck, CircleX, Play, Trash2, TriangleAlert } from 'lucide-react'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import NodeConfigForm, { type NodeFormValues } from './NodeConfigForm'
import VariableFormFields from '../../components/workflows/VariableFormFields'
import type { WorkflowVariableDecl } from '../../api'
import Button from '../../components/ui/Button'
import Badge from '../../components/ui/Badge'

// 工作流编辑器右侧面板：节点配置与连线分支值（改动即写回，没有"应用"按钮）/ 测试运行。
// 从 WorkflowEditor 拆出（docs/15 WF-01 时该文件已近 300 行）；状态都在编辑器页面里，这里只渲染与回调。
interface Props {
  selectedNode: any
  selectedEdge: any
  edgeSourceType?: string
  nodeError?: string // 当前节点表单校验不过的原因（不写回节点、保存会被拦）
  nodeValues: NodeFormValues
  onNodeChange: (patch: Partial<NodeFormValues>) => void
  nodeErrorField?: string | null
  agents: any[]
  tools: any[]
  kbs: any[]
  // 当前选中工具的参数声明：有声明时按字段渲染输入项（docs/17），没有才退回 JSON 文本框
  toolParams?: any
  edgeLabel: string
  onEdgeLabelChange: (value: string) => void // 随输入直接写回连线，与节点配置一致
  onDelete: () => void // 走 React Flow 的 deleteElements，和 Backspace 一样先过删除确认
  testVariables: WorkflowVariableDecl[]
  testInputs: Record<string, unknown>
  onTestInputsChange: (values: Record<string, unknown>) => void
  testing: boolean
  testResult: any
  onTest: () => void
}

const TITLE = 'mb-3 flex items-center gap-1.5 text-[14px] font-semibold'

function Notice({ tone, title, detail }: { tone: 'success' | 'warning' | 'error'; title: string; detail?: string }) {
  const look = {
    success: { border: 'border-[rgba(22,163,74,.35)] bg-[rgba(22,163,74,.10)]', icon: <CircleCheck className="mt-0.5 size-3.5 shrink-0 text-[#15803D]" /> },
    warning: { border: 'border-[rgba(217,119,6,.35)] bg-[rgba(217,119,6,.10)]', icon: <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-[#B45309]" /> },
    error: { border: 'border-destructive/30 bg-destructive/5', icon: <CircleX className="mt-0.5 size-3.5 shrink-0 text-destructive" /> },
  }[tone]
  return (
    <div className={`flex items-start gap-2 rounded-lg border px-2.5 py-2 ${look.border}`}>
      {look.icon}
      <div className="min-w-0 text-[12.5px]">
        <div>{title}</div>
        {detail && <div className="mt-0.5 break-words text-muted-foreground">{detail}</div>}
      </div>
    </div>
  )
}

export default function ConfigPanel(p: Props) {
  const isLoopEdge = p.edgeSourceType === 'loop'
  return (
    <div className="flex min-h-0 flex-col">
      <div className="shrink-0">
        {p.selectedNode ? (
          <>
            <div className={TITLE}>节点配置 · {p.selectedNode.data.label}</div>
            <NodeConfigForm
              nodeType={p.selectedNode.data.nodeType}
              values={p.nodeValues}
              onChange={p.onNodeChange}
              errorField={p.nodeErrorField}
              agents={p.agents}
              tools={p.tools}
              kbs={p.kbs}
              toolParams={p.toolParams}
            />
            {p.nodeError && (
              <div className="mt-2">
                <Notice tone="error" title={`${p.nodeError}：改正前不会写回节点，保存会被拦下`} />
              </div>
            )}
            <div className="mt-3">
              <Button variant="danger" size="sm" icon={<Trash2 />} onClick={p.onDelete}>删除节点</Button>
            </div>
          </>
        ) : p.selectedEdge ? (
          <>
            <div className={TITLE}>连线配置 · {isLoopEdge ? '循环分支' : p.edgeSourceType === 'parallel' ? '并行分支' : '条件分支'}</div>
            {p.edgeSourceType === 'parallel' ? (
              <p className="m-0 text-[13px] text-muted-foreground">并行节点的出边不需要分支值，每条出边就是一条并发分支。</p>
            ) : (
              <div className="flex flex-col gap-1.5">
                <Label className="text-[12.5px]">{isLoopEdge ? '分支值(loop=回环 / exit=退出)' : '分支值(true/false)'}</Label>
                <Input
                  value={p.edgeLabel}
                  onChange={(e) => p.onEdgeLabelChange(e.target.value)}
                  placeholder={isLoopEdge ? 'loop 或 exit' : 'true 或 false'}
                  className="h-8 text-[12.5px]"
                />
              </div>
            )}
            <div className="mt-3">
              <Button variant="danger" size="sm" icon={<Trash2 />} onClick={p.onDelete}>删除连线</Button>
            </div>
          </>
        ) : (
          <p className="m-0 py-5 text-center text-[13px] text-muted-foreground">点击画布中的节点或连线<br />在右侧进行配置</p>
        )}
      </div>

      <div className="my-4 border-t border-border" />

      {/* 测试运行区：输入工作流入参后试跑，不保存到工作流定义 */}
      <div className="shrink-0">
        <div className={TITLE}><Play className="size-3.5" /> 测试运行</div>
        {/* 入参表单由开始节点的变量声明生成（docs/15 WF-04）：不再让用户手写 JSON 字典 */}
        <VariableFormFields variables={p.testVariables} values={p.testInputs} onChange={p.onTestInputsChange} idPrefix="test-wf" />
        <Button variant="primary" size="sm" block className="mt-2" icon={<Play />} disabled={p.testing} onClick={p.onTest}>
          {p.testing ? '运行中…' : '运行'}
        </Button>

        {p.testResult && (
          <div className="mt-3 flex flex-col gap-2">
            {p.testResult.status === 'success' ? (
              <>
                <Notice tone="success" title="运行成功" />
                <div className="text-[12px] font-semibold">输出：</div>
                <pre className="m-0 max-h-[120px] overflow-auto rounded-md border border-border bg-secondary p-2 font-mono text-[12px] text-foreground">{JSON.stringify(p.testResult.output, null, 2)}</pre>
                {p.testResult.steps?.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {p.testResult.steps.map((s: string, i: number) => <Badge key={i} tone="neutral">{s}</Badge>)}
                  </div>
                )}
              </>
            ) : p.testResult.status === 'awaiting_review' ? (
              <Notice tone="warning" title="等待人工审核" detail={JSON.stringify(p.testResult.interrupt)} />
            ) : (
              <Notice tone="error" title="运行失败" detail={p.testResult.error} />
            )}
          </div>
        )}
      </div>
    </div>
  )
}
