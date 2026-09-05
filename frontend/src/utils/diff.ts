// 文本行级 diff（LCS），给版本对比用；对象快照走字段级 diff 只列变更字段。纯函数，不依赖 UI。
export type DiffOp = 'equal' | 'add' | 'remove'
export interface DiffLine { op: DiffOp; text: string }

export function diffLines(oldText: string, newText: string): DiffLine[] {
  const a = oldText.split('\n')
  const b = newText.split('\n')
  const n = a.length
  const m = b.length
  // dp[i][j] = a[i:] 与 b[j:] 的 LCS 长度
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const out: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ op: 'equal', text: a[i] }); i++; j++ }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ op: 'remove', text: a[i] }); i++ }
    else { out.push({ op: 'add', text: b[j] }); j++ }
  }
  while (i < n) out.push({ op: 'remove', text: a[i++] })
  while (j < m) out.push({ op: 'add', text: b[j++] })
  return out
}

export interface FieldChange { field: string; before: unknown; after: unknown }

// 空值归一：undefined / null / {} / [] / '' 视为同一种"空"，旧快照缺键与当前值为空对象不算差异
function normalize(value: unknown): unknown {
  if (value === undefined || value === null || value === '') return null
  if (Array.isArray(value) && value.length === 0) return null
  if (typeof value === 'object' && !Array.isArray(value) && Object.keys(value as object).length === 0) return null
  return value
}

// 对象快照的字段级差异：只列值不同的字段（深比较用 JSON 序列化，快照都是可序列化数据）
export function diffFields(before: Record<string, unknown>, after: Record<string, unknown>, fields?: string[]): FieldChange[] {
  const keys = fields ?? Array.from(new Set([...Object.keys(before || {}), ...Object.keys(after || {})]))
  return keys
    .filter((k) => JSON.stringify(normalize(before?.[k])) !== JSON.stringify(normalize(after?.[k])))
    .map((k) => ({ field: k, before: before?.[k], after: after?.[k] }))
}
