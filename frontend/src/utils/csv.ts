// 导出当前数据为 CSV（带 BOM，Excel 直接打开不乱码）。只导出页面已拿到的数据，不另发全量请求。
export interface CsvColumn<T> { title: string; value: (row: T) => string | number | null | undefined }

function escapeCell(value: string | number | null | undefined): string {
  const text = value === null || value === undefined ? '' : String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

export function exportCsv<T>(filename: string, columns: CsvColumn<T>[], rows: T[]): void {
  const lines = [columns.map((c) => escapeCell(c.title)).join(',')]
  for (const row of rows) lines.push(columns.map((c) => escapeCell(c.value(row))).join(','))
  const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.csv') ? filename : `${filename}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
