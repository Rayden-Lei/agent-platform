import { Typography } from 'antd'
import { diffFields, diffLines } from '../../utils/diff'
import JsonView from './JsonView'

// 版本对比：文本走行级 diff（左旧右新的统一视图），对象快照只列变更字段。
export function TextDiff({ before, after }: { before: string; after: string }) {
  const lines = diffLines(before || '', after || '')
  if (lines.every((l) => l.op === 'equal')) return <Typography.Text type="secondary">内容无差异</Typography.Text>
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
  if (!changes.length) return <Typography.Text type="secondary">两个版本没有差异</Typography.Text>
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {changes.map((c) => (
        <div key={c.field}>
          <Typography.Text strong>{labels?.[c.field] ?? c.field}</Typography.Text>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 4 }}>
            <JsonView title="旧值" value={c.before} maxHeight={160} />
            <JsonView title="新值" value={c.after} maxHeight={160} />
          </div>
        </div>
      ))}
    </div>
  )
}
