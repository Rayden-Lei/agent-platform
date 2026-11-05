import { Fragment, useMemo, useState, type ReactNode } from 'react'

// 数据表格：同一份列定义渲染两种形态 —— 桌面是表格、窄屏是卡片。
// 服务端分页与排序（数据量大，前端不做全量排序）；行选择跨页保留。
// 列定义用 TanStack 的 ColumnDef，但通过 DataColumn 收窄成项目口径，避免各页面各写一套 meta。

export interface DataColumn<T> {
  /** 列标识；sortable 时作为服务端排序字段 */
  key: string
  header: ReactNode
  /** 桌面端列宽（px 或 CSS 长度） */
  width?: number | string
  align?: 'left' | 'center' | 'right'
  /** 表头可点，触发服务端排序 */
  sortable?: boolean
  /** 单元格内容 */
  cell: (row: T) => ReactNode
  /** 窄屏卡片里不展示（次要列） */
  hideOnMobile?: boolean
  /** 窄屏卡片里作为标题行展示 */
  primary?: boolean
  /** 窄屏卡片里是否显示字段名，默认显示 */
  hideLabelOnMobile?: boolean
  /** 横向滚动时钉在右边（操作列）。sticky 列之间的偏移由实现按出现顺序算 */
  pinRight?: boolean
}

export interface SortState {
  field?: string
  order?: 'asc' | 'desc'
}

export interface DataTableProps<T> {
  columns: DataColumn<T>[]
  rows: T[]
  rowKey: (row: T) => string | number
  loading?: boolean
  error?: string | null
  empty?: ReactNode
  onRetry?: () => void

  page?: number
  pageSize?: number
  total?: number
  onPageChange?: (page: number, pageSize: number) => void

  sort?: SortState
  onSortChange?: (sort: SortState) => void

  selectable?: boolean
  selectedKeys?: number[]
  onSelectionChange?: (keys: number[]) => void

  onRowClick?: (row: T) => void

  /** 行展开（审计日志看完整 JSON 这类）：返回 null 的行不可展开 */
  expand?: {
    render: (row: T) => ReactNode
    expandable?: (row: T) => boolean
  }
}

const PAGE_SIZE_OPTIONS = [10, 20, 50, 100]

// 排序指示器：未排序时两条灰线，升序/降序高亮一侧
function SortIcon({ state }: { state: 'asc' | 'desc' | false }) {
  const up = state === 'asc'
  const down = state === 'desc'
  return (
    <span className="inline-flex flex-col gap-[2px] ml-1 shrink-0" aria-hidden="true">
      <svg width="8" height="5" viewBox="0 0 8 5" fill="none">
        <path d="M4 0L8 5H0L4 0Z" fill={up ? 'var(--accent)' : 'var(--fg-subtle)'} opacity={up ? 1 : 0.45} />
      </svg>
      <svg width="8" height="5" viewBox="0 0 8 5" fill="none">
        <path d="M4 5L0 0H8L4 5Z" fill={down ? 'var(--accent)' : 'var(--fg-subtle)'} opacity={down ? 1 : 0.45} />
      </svg>
    </span>
  )
}

// 视觉 16×16，用伪元素把可点区域扩到 32×32：表格密集，直接放大按钮会撑开行高。
function Checkbox({ checked, indeterminate, onChange, label }: { checked: boolean; indeterminate?: boolean; onChange: () => void; label: string }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={indeterminate ? 'mixed' : checked}
      aria-label={label}
      onClick={(e) => { e.stopPropagation(); onChange() }}
      className="relative w-4 h-4 rounded-[4px] flex items-center justify-center shrink-0 transition-colors after:absolute after:-inset-2 after:content-['']"
      style={{
        background: checked || indeterminate ? 'var(--accent)' : 'var(--bg-elev)',
        border: `1px solid ${checked || indeterminate ? 'var(--accent)' : 'var(--border-strong)'}`,
      }}
    >
      {indeterminate && !checked ? (
        <span className="block w-2 h-[1.5px] rounded-full" style={{ background: 'var(--accent-fg)' }} />
      ) : checked ? (
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="var(--accent-fg)" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 12l6 6L20 6" />
        </svg>
      ) : null}
    </button>
  )
}

export default function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  error,
  empty,
  onRetry,
  page = 1,
  pageSize = 20,
  total = 0,
  onPageChange,
  sort,
  onSortChange,
  selectable,
  selectedKeys = [],
  onSelectionChange,
  onRowClick,
  expand,
}: DataTableProps<T>) {
  const [expandedKeys, setExpandedKeys] = useState<Array<string | number>>([])
  const canExpand = (row: T) => !!expand && (expand.expandable ? expand.expandable(row) : true)
  const toggleExpand = (key: string | number) => setExpandedKeys((keys) => (keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key]))
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const pageNumbers = useMemo(() => {
    const out: number[] = []
    const start = Math.max(1, Math.min(page - 2, totalPages - 4))
    for (let i = start; i < start + 5 && i <= totalPages; i++) out.push(i)
    return out
  }, [page, totalPages])

  const allSelected = rows.length > 0 && rows.every((r) => selectedKeys.includes(Number(rowKey(r))))
  const someSelected = rows.some((r) => selectedKeys.includes(Number(rowKey(r))))
  const toggleAll = () => {
    if (!onSelectionChange) return
    const visibleIds = rows.map((r) => Number(rowKey(r)))
    if (allSelected) {
      onSelectionChange(selectedKeys.filter((k) => !visibleIds.includes(k)))
    } else {
      onSelectionChange(Array.from(new Set([...selectedKeys, ...visibleIds])))
    }
  }

  // 右侧钉住列的样式：横滚时操作列始终可见。偏移量按其后同类列的宽度累加（这里只有一列，写死 0）
  const pinnedStyle = (c: DataColumn<T>): React.CSSProperties => {
    if (!c.pinRight) return {}
    return {
      position: 'sticky',
      right: 0,
      zIndex: 1,
      background: 'var(--bg-elev)',
      boxShadow: '-8px 0 12px -8px rgba(15,23,42,.18)',
    }
  }

  // ---------- 状态分支 ----------
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-16 rounded-xl" style={{ background: 'var(--bg-elev)', border: '1px solid var(--border)' }}>
        <span className="text-[13px]" style={{ color: 'var(--fg-muted)' }}>加载失败：{error}</span>
        {onRetry && (
          <button type="button" onClick={onRetry} className="text-[13px] px-3 py-1.5 rounded-lg" style={{ background: 'var(--accent)', color: 'var(--accent-fg)' }}>
            重试
          </button>
        )}
      </div>
    )
  }

  if (!loading && rows.length === 0) {
    return (
      <div className="flex items-center justify-center py-16 rounded-xl" style={{ background: 'var(--bg-elev)', border: '1px solid var(--border)' }}>
        <div className="text-[13px]" style={{ color: 'var(--fg-subtle)' }}>{empty ?? '暂无数据'}</div>
      </div>
    )
  }

  const skeletonRows = Array.from({ length: Math.min(pageSize, 8) })

  return (
    <div className="flex flex-col min-h-0 flex-1">
      {/* ---------- 桌面：表格 ---------- */}
      {/* 断点用 lg(1024) 而不是 md(768)：竖握的平板只有 768px，而智能体表宽 1182px、
          模型表也已过千 —— 在 768~1023 之间用表格只能横向拽，卡片反而更好读。
              105 行处注释的「窄屏卡片」同理。 */}
      <div className="hidden lg:block flex-1 min-h-0 overflow-auto rounded-xl" style={{ border: '1px solid var(--border)' }}>
        <table className="w-full border-collapse text-[13.5px]">
          <thead className="sticky top-0 z-[2]">
            <tr style={{ background: 'var(--bg-soft-2)' }}>
              {expand && <th className="w-8 px-2 py-2.5" style={{ borderBottom: '1px solid var(--border)' }} />}
              {selectable && (
                <th className="w-10 px-3 py-2.5 text-left" style={{ borderBottom: '1px solid var(--border)' }}>
                  <Checkbox checked={allSelected} indeterminate={someSelected} onChange={toggleAll} label="全选" />
                </th>
              )}
              {columns.map((c) => {
                const isSorted = sort?.field === c.key
                return (
                  <th
                    key={c.key}
                    className="px-3 py-2.5 font-semibold whitespace-nowrap"
                    style={{
                      width: c.width,
                      textAlign: c.align ?? 'left',
                      color: 'var(--fg-muted)',
                      fontSize: 12.5,
                      borderBottom: '1px solid var(--border)',
                      cursor: c.sortable ? 'pointer' : 'default',
                      userSelect: 'none',
                      ...pinnedStyle(c),
                    }}
                    aria-sort={isSorted ? (sort?.order === 'asc' ? 'ascending' : 'descending') : undefined}
                    onClick={() => {
                      if (!c.sortable || !onSortChange) return
                      onSortChange(isSorted && sort?.order === 'asc' ? { field: c.key, order: 'desc' } : { field: c.key, order: 'asc' })
                    }}
                  >
                    <span className="inline-flex items-center">
                      {c.header}
                      {c.sortable && <SortIcon state={isSorted ? (sort?.order ?? false) : false} />}
                    </span>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {loading
              ? skeletonRows.map((_, i) => (
                  <tr key={`sk-${i}`} style={{ borderBottom: '1px solid var(--border)' }}>
                    {expand && <td className="px-2 py-3" />}
                    {selectable && <td className="px-3 py-3" />}
                    {columns.map((c) => (
                      <td key={c.key} className="px-3 py-3">
                        <span className="block h-3 rounded" style={{ background: 'var(--bg-soft)', width: '60%' }} />
                      </td>
                    ))}
                  </tr>
                ))
              : rows.map((original) => {
                  const rid = String(rowKey(original))
                  const expanded = expandedKeys.includes(rid)
                  return (
                    <Fragment key={rid}>
                    <tr
                      key={rid}
                      className="transition-colors"
                      style={{ borderBottom: '1px solid var(--border)', cursor: onRowClick ? 'pointer' : 'default' }}
                      onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-soft-2)' }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
                      onClick={() => onRowClick?.(original)}
                    >
                      {expand && (
                        <td className="px-2 py-2.5">
                          {canExpand(original) ? (
                            <button
                              type="button"
                              aria-label={expanded ? '收起详情' : '展开详情'}
                              aria-expanded={expanded}
                              onClick={(e) => { e.stopPropagation(); toggleExpand(rid) }}
                              className="relative flex size-5 items-center justify-center rounded text-muted-foreground hover:bg-accent after:absolute after:-inset-1.5 after:content-['']"
                            >
                              <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"
                                style={{ transform: expanded ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}>
                                <path d="M3 1l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                            </button>
                          ) : null}
                        </td>
                      )}
                      {selectable && (
                        <td className="px-3 py-2.5">
                          <Checkbox
                            checked={selectedKeys.includes(Number(rowKey(original)))}
                            onChange={() => {
                              const id = Number(rowKey(original))
                              onSelectionChange?.(selectedKeys.includes(id) ? selectedKeys.filter((k) => k !== id) : [...selectedKeys, id])
                            }}
                            label="选择本行"
                          />
                        </td>
                      )}
                      {columns.map((c) => (
                        <td
                          key={c.key}
                          className="px-3 py-2.5"
                          style={{ textAlign: c.align ?? 'left', color: 'var(--fg)', maxWidth: c.width, ...pinnedStyle(c) }}
                        >
                          {c.cell(original)}
                        </td>
                      ))}
                    </tr>
                    {expand && expanded && (
                      <tr style={{ background: 'var(--bg-soft-2)' }}>
                        <td colSpan={columns.length + (selectable ? 1 : 0) + 1} className="px-4 py-3">
                          {expand.render(original)}
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  )
                })}
          </tbody>
        </table>
      </div>

      {/* ---------- 窄屏：卡片 ---------- */}
      <div className="lg:hidden flex-1 min-h-0 overflow-auto flex flex-col gap-2.5">
        {loading
          ? skeletonRows.slice(0, 4).map((_, i) => (
              <div key={`skc-${i}`} className="rounded-xl p-3.5" style={{ background: 'var(--bg-elev)', border: '1px solid var(--border-strong)' }}>
                <span className="block h-3.5 rounded mb-2.5" style={{ background: 'var(--bg-soft)', width: '45%' }} />
                <span className="block h-3 rounded mb-2" style={{ background: 'var(--bg-soft)', width: '70%' }} />
                <span className="block h-3 rounded" style={{ background: 'var(--bg-soft)', width: '55%' }} />
              </div>
            ))
          : rows.map((row) => {
              const primary = columns.find((c) => c.primary) ?? columns[0]
              // 操作列（pinRight）单独占一行按钮区：它原来混在「字段名 : 值」的行里，
              // 4 个按钮被塞进一个可截断的右对齐窄格，智能体一多、按钮变长就互相挤成省略号。
              // 按钮本来就该占满整行宽度，能并排就并排、放不下换行。
              const actions = columns.find((c) => c.pinRight)
              const rest = columns.filter((c) => c !== primary && c !== actions && !c.hideOnMobile)
              return (
                <div
                  key={String(rowKey(row))}
                  className="rounded-xl overflow-hidden"
                  style={{ background: 'var(--bg-elev)', border: '1px solid var(--border-strong)', boxShadow: 'var(--shadow-card)' }}
                  onClick={() => onRowClick?.(row)}
                >
                  <div className="flex items-start gap-2 px-3.5 pt-3 pb-1.5">
                    {selectable && (
                      <span className="pt-0.5">
                        <Checkbox
                          checked={selectedKeys.includes(Number(rowKey(row)))}
                          onChange={() => {
                            const id = Number(rowKey(row))
                            onSelectionChange?.(selectedKeys.includes(id) ? selectedKeys.filter((k) => k !== id) : [...selectedKeys, id])
                          }}
                          label="选择本行"
                        />
                      </span>
                    )}
                    <div className="min-w-0 flex-1 text-[14.5px] font-semibold" style={{ color: 'var(--fg)' }}>
                      {primary.cell(row)}
                    </div>
                  </div>
                  <div className="px-3.5 pb-2">
                    {rest.map((c) => (
                      <div key={c.key} className="flex items-center justify-between gap-3 py-1">
                        {!c.hideLabelOnMobile && (
                          <span className="text-[12px] shrink-0" style={{ color: 'var(--fg-muted)' }}>{c.header}</span>
                        )}
                        <span className="text-[13px] text-right min-w-0 truncate" style={{ color: 'var(--fg)' }}>{c.cell(row)}</span>
                      </div>
                    ))}
                  </div>
                  {actions && (
                    <div
                      className="data-card-actions flex flex-wrap items-center gap-1.5 px-3.5 py-2"
                      style={{ borderTop: '1px solid var(--border)' }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      {actions.cell(row)}
                    </div>
                  )}
                </div>
              )
            })}
      </div>

      {/* ---------- 分页 ---------- */}
      {onPageChange && total > 0 && (
        <div className="flex items-center justify-between gap-3 pt-3 shrink-0 flex-wrap">
          <span className="text-[12px]" style={{ color: 'var(--fg-subtle)' }}>
            共 {total} 条{selectedKeys.length > 0 ? `，已选 ${selectedKeys.length} 条` : ''}
          </span>
          {/* 窄屏分页：页码按钮 + 每页条数在 320px 屏上放不下（实测顶出 385px），
              允许换行并把「每页条数」推到下一行，而不是横向溢出 */}
          <div className="flex flex-wrap items-center justify-end gap-1">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1, pageSize)}
              className="px-2.5 h-7 rounded-md text-[12px] disabled:opacity-40"
              style={{ border: '1px solid var(--border)', color: 'var(--fg-muted)', background: 'var(--bg-elev)' }}
            >
              上一页
            </button>
            {pageNumbers.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => onPageChange(p, pageSize)}
                aria-current={p === page ? 'page' : undefined}
                className="w-7 h-7 rounded-md text-[12px]"
                style={{
                  border: `1px solid ${p === page ? 'var(--accent)' : 'var(--border)'}`,
                  background: p === page ? 'var(--accent)' : 'var(--bg-elev)',
                  color: p === page ? 'var(--accent-fg)' : 'var(--fg-muted)',
                }}
              >
                {p}
              </button>
            ))}
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => onPageChange(page + 1, pageSize)}
              className="px-2.5 h-7 rounded-md text-[12px] disabled:opacity-40"
              style={{ border: '1px solid var(--border)', color: 'var(--fg-muted)', background: 'var(--bg-elev)' }}
            >
              下一页
            </button>
            <select
              value={pageSize}
              onChange={(e) => onPageChange(1, Number(e.target.value))}
              className="h-7 rounded-md text-[12px] px-1.5 ml-1"
              style={{ border: '1px solid var(--border)', color: 'var(--fg-muted)', background: 'var(--bg-elev)' }}
              aria-label="每页条数"
            >
              {PAGE_SIZE_OPTIONS.map((s) => <option key={s} value={s}>{s} 条/页</option>)}
            </select>
          </div>
        </div>
      )}
    </div>
  )
}