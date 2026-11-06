// 图表主题与通用配置：与应用主题令牌、StatusTag 语义色一致（docs/07 第 6 节）。
// 2026-11-06 精致化：过去图表是 G2 的默认样式 —— 粗线、实色大块柱、灰色网格密布，
// 在白底卡片里显得又土又满。现在统一走「轻量」风格：细线、圆角柱、浅网格、无边框轴线，
// 通过 AXIS / SCALE_STYLE 两个导出在 TrendLine / StackedBar 里应用，一处改全局生效。

export const PALETTE = ['#2563eb', '#0d9488', '#d97706', '#16a34a', '#0f766e', '#64748b', '#9a3412', '#475569']

// 状态序列的固定颜色（趋势图按状态堆叠时用），与 StatusTag 同语义
export const STATUS_COLORS: Record<string, string> = {
  success: '#16a34a',
  failed: '#dc2626',
  cancelled: '#9ca3af',
  awaiting_review: '#d97706',
  running: '#2563eb',
}
export const STATUS_SERIES_LABEL: Record<string, string> = { success: '成功', failed: '失败', cancelled: '已取消', awaiting_review: '待审核', running: '运行中' }
// 序列名既可能是状态码也可能是中文标签（图例要显示中文），两种都能查到颜色
export const statusSeriesColor = (series: string, fallback: string) =>
  STATUS_COLORS[series] ?? STATUS_COLORS[Object.keys(STATUS_SERIES_LABEL).find((k) => STATUS_SERIES_LABEL[k] === series) ?? ''] ?? fallback

export const CHART_HEIGHT = 260

// ---- 统一样式 ----

/** 坐标轴：浅灰细网格（只保留横向）、去掉轴线与刻度线、淡色标签 —— 图表不再被网格框住 */
export const AXIS_STYLE = {
  x: {
    labelAutoHide: true,
    title: false,
    line: false,
    tick: false,
    labelFontSize: 11,
    labelFill: '#94a3b8',
    grid: null as unknown as null,
  },
  y: {
    title: false,
    line: false,
    tick: false,
    labelFontSize: 11,
    labelFill: '#94a3b8',
    grid: true as unknown as boolean,
    gridStroke: '#e2e8f0',
    gridStrokeOpacity: 0.7,
    gridLineWidth: 1,
  },
}

/** 柱样式：细间距 + 圆角顶；条形图（横向 transpose）自动圆在右端 */
export const BAR_STYLE = { radiusTop: 3, radiusBottom: 0, maxWidth: 28 } as const

/** 折线样式：2px 线 + 小面积淡填充 */
export const LINE_STYLE = { lineWidth: 2 } as const
export const AREA_FILL_OPACITY = 0.08