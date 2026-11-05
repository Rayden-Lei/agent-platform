import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import type { WorkflowVariableDecl } from '../../api'

// 按开始节点的变量声明生成输入项（docs/15 WF-04）：运行弹窗、编辑器测试运行、定时任务表单共用。
// 声明是唯一依据——用户只需要填该填的东西，不再手写 JSON 字典，也不必靠约定知道下游要什么 key。

interface Props {
  variables: WorkflowVariableDecl[]
  values: Record<string, unknown>
  onChange: (values: Record<string, unknown>) => void
  disabled?: boolean
  idPrefix?: string
}

const TYPES: Record<WorkflowVariableDecl['type'], string> = { text: '文本', number: '数字', integer: '整数', boolean: '布尔' }

export default function VariableFormFields({ variables, values, onChange, disabled, idPrefix = 'wf-var' }: Props) {
  if (!variables.length) {
    return <p className="m-0 text-[12.5px] text-muted-foreground">该工作流的开始节点没有声明输入变量，直接运行即可。</p>
  }
  const set = (name: string, v: unknown) => onChange({ ...values, [name]: v })
  return (
    <div className="flex flex-col gap-3">
      {variables.map((v) => {
        const id = `${idPrefix}-${v.name}`
        const required = v.required
        return (
          <div key={v.name} className="flex flex-col gap-1.5">
            <Label htmlFor={id} className="text-[12.5px]">
              {v.name}
              <span className="ml-1 font-normal text-muted-foreground">（{TYPES[v.type]}{required ? '，必填' : '，可选'}）</span>
            </Label>
            {v.type === 'boolean' ? (
              <select
                id={id}
                value={String(values[v.name] ?? v.default ?? '')}
                disabled={disabled}
                onChange={(e) => set(v.name, e.target.value === '' ? undefined : e.target.value === 'true')}
                className="h-8 w-full rounded-md border border-border-strong bg-transparent px-2 text-[12.5px] text-foreground outline-none focus-visible:border-ring"
              >
                <option value="">{required ? '请选择' : '不填'}</option>
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            ) : (
              <Input
                id={id}
                type={v.type === 'text' ? 'text' : 'number'}
                value={String(values[v.name] ?? v.default ?? '')}
                disabled={disabled}
                onChange={(e) => set(v.name, e.target.value)}
                placeholder={v.description || (required ? '必填' : `可选${v.default != null ? '，默认 ' + String(v.default) : ''}`)}
                className="h-8 text-[12.5px]"
              />
            )}
            {v.description && <p className="m-0 text-[11.5px] text-muted-foreground">{v.description}</p>}
          </div>
        )
      })}
    </div>
  )
}
