// 图表色板与主题：与 antd 主题、StatusTag 语义色一致；企业风纯色，无紫色渐变（docs/07 第 6 节）。
export const PALETTE = ['#1e40af', '#0e7490', '#b45309', '#15803d', '#0f766e', '#6b7280', '#9a3412', '#334155']

// 状态序列的固定颜色（趋势图按状态堆叠时用），与 StatusTag 同语义
export const STATUS_COLORS: Record<string, string> = {
  success: '#16a34a',
  failed: '#dc2626',
  cancelled: '#9ca3af',
  awaiting_review: '#d97706',
  running: '#2563eb',
}
export const STATUS_SERIES_LABEL: Record<string, string> = { success: '成功', failed: '失败', cancelled: '已取消', awaiting_review: '待审核', running: '运行中' }

export const CHART_HEIGHT = 260
