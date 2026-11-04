import { diffFields, diffLines } from '../../utils/diff'
import JsonView from './JsonView'

// 版本对比：文本走行级 diff（左旧右新的统一视图），对象快照只列变更字段。
export function TextDiff({ before, after }: { before: string; after: string }) {
  const lines = diffLines(before || '', after || '')
  if (lines.every((l) => l.op === 'equal')) return <span className="text-[13px] text-muted-foreground">内容无差异</span>
  return (
    <pre className="diff-view">
      {lines.map((l, i) => (
        <div key={i} className={`diff-line diff-${l.op}`}>
          <span className="diff-sign">{l.op === 'add' ? '+' : l.op === 'remove' ? '−' : ' '}</span>{l.text}
        </div>
      ))}
    </pre>
  )
}

export function FieldDiff({ before, after, labels }: { before: Record<string, unknown>; after: Record<string, unknown>; labels?: Record<string, string> }) {
  const changes = diffFields(before, after)
  if (!changes.length) return <span className="text-[13px] text-muted-foreground">两个版本没有差异</span>
  return (
    <div className="flex flex-col gap-3">
      {changes.map((c) => (
        <div key={c.field}>
          <span className="text-[13px] font-semibold">{labels?.[c.field] ?? c.field}</span>
          <div className="mt-1 grid grid-cols-2 gap-2">
            <JsonView title="旧值" value={c.before} maxHeight={160} />
            <JsonView title="新值" value={c.after} maxHeight={160} />
          </div>
        </div>
      ))}
    </div>
  )
}
