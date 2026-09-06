import type { DocumentRow } from '../../api'

// 文档处理进度的派生量：百分比、速度（片 / 秒）、预计剩余秒数、总耗时；全部由服务端的计数与时间戳算出，不依赖前端轮询节奏。
export interface DocProgress {
  percent: number | null
  rate: number | null
  etaSeconds: number | null
  elapsedSeconds: number | null
  stalled: boolean // 处理中但超过 STALL_SECONDS 没有心跳：后端被杀或向量服务卡死，可"继续处理"
  stalledSeconds: number | null
}

export const PROCESSING_STATUSES = new Set(['uploading', 'parsing', 'chunking'])
// 与后端 INGEST_STALL_SECONDS 一致
export const STALL_SECONDS = 180

export function docProgress(doc: DocumentRow, now: number = Date.now()): DocProgress {
  const started = doc.processing_started_at ? Date.parse(doc.processing_started_at) : null
  const finished = doc.finished_at ? Date.parse(doc.finished_at) : null
  const end = finished ?? now
  const elapsedSeconds = started ? Math.max(0, (end - started) / 1000) : null
  const total = doc.chunk_total
  const percent = total ? Math.min(100, Math.round((doc.chunk_count / total) * 100)) : null
  // 速度按本次新增的片算（续处理时扣掉 resume_offset），且只在真正开始入库后才算，避免解析阶段显示 0 片 / 秒
  const done = doc.chunk_count - (doc.resume_offset || 0)
  const rate = started && elapsedSeconds && elapsedSeconds > 0 && done > 0 ? done / elapsedSeconds : null
  const etaSeconds = rate && total && doc.status === 'chunking' ? Math.max(0, (total - doc.chunk_count) / rate) : null
  const lastBeat = doc.heartbeat_at ?? doc.processing_started_at ?? doc.created_at
  const stalledSeconds = PROCESSING_STATUSES.has(doc.status) && lastBeat ? Math.max(0, (now - Date.parse(lastBeat)) / 1000) : null
  const stalled = stalledSeconds !== null && stalledSeconds > STALL_SECONDS
  return { percent, rate, etaSeconds, elapsedSeconds, stalled, stalledSeconds }
}

// 秒数的人话：58 秒 / 3 分 20 秒 / 1 小时 05 分
export function humanSeconds(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '-'
  const s = Math.round(seconds)
  if (s < 60) return `${s} 秒`
  if (s < 3600) return `${Math.floor(s / 60)} 分 ${String(s % 60).padStart(2, '0')} 秒`
  return `${Math.floor(s / 3600)} 小时 ${String(Math.floor((s % 3600) / 60)).padStart(2, '0')} 分`
}
