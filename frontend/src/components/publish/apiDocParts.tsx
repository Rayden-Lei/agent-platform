import type { ReactNode } from 'react'
import { useState } from 'react'
import { ChevronDown, Copy } from 'lucide-react'
import { copyText } from '../../utils/clipboard'
import Button from '../ui/Button'
import type { DocRow } from './apiSnippets'

// "API 调用"卡片的展示件（智能体 PB-02 与工作流 WF-06 共用）：行内代码 + 复制、代码块、两列文档表、折叠段落。
// 只是展示，不含任何请求与业务逻辑。

// 行内代码 + 复制：原来 antd 的 Typography.Text copyable
export function CodeText({ children, copy }: { children: string; copy?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <code className="select-all break-all rounded bg-secondary px-1.5 py-0.5 font-mono text-[12.5px] text-foreground">{children}</code>
      {copy && (
        <Button size="sm" variant="ghost" aria-label="复制" onClick={() => copyText(children, '')}><Copy className="size-3.5" /></Button>
      )}
    </span>
  )
}

// 代码块 + 右上角复制；深色底用语义 token（bg-foreground / text-background），不写死色值
export function Snippet({ code, label }: { code: string; label: string }) {
  return (
    <div className="relative">
      <div className="absolute right-2 top-2">
        <Button size="sm" variant="secondary" icon={<Copy className="size-3.5" />} onClick={() => copyText(code, label)}>复制</Button>
      </div>
      <pre className="m-0 max-h-[360px] overflow-auto rounded-lg bg-foreground px-3.5 py-3 pr-20 font-mono text-[12px] leading-relaxed text-background">{code}</pre>
    </div>
  )
}

// 两列文档表（端点 / 字段 / 事件 / 错误码），固定几行，用原生 table
export function DocTable({ rows, first }: { rows: DocRow[]; first: string }) {
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <table className="w-full border-collapse text-[13.5px]">
        <thead className="bg-secondary">
          <tr>
            <th className="w-[260px] px-3 py-2 text-left text-[12.5px] font-medium text-muted-foreground">{first}</th>
            <th className="px-3 py-2 text-left text-[12.5px] font-medium text-muted-foreground">说明</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t border-border align-top">
              <td className="px-3 py-2"><code className="break-all font-mono text-[12.5px] text-foreground">{r.name}</code></td>
              <td className="px-3 py-2 text-muted-foreground">{r.desc}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// 折叠段落：原来 antd Collapse，展开状态自己管（shadcn 没有 accordion 组件）
export function Disclosure({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-[13px] font-medium text-foreground hover:bg-accent"
      >
        {title}
        <ChevronDown className={`size-4 shrink-0 text-muted-foreground transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>
      {open && <div className="border-t border-border p-2">{children}</div>}
    </div>
  )
}
