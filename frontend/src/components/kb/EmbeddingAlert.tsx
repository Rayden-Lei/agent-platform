import { Alert } from 'antd'
import { useSystemStatus } from '../../hooks/useSystemStatus'

// 向量后端降级提示：检索质量会明显下降，必须在建库 / 上传 / 评测的页面直接告诉使用者（docs/07 第 3 节）。
export default function EmbeddingAlert() {
  const { status, error } = useSystemStatus()
  if (error && !status) return <Alert type="warning" showIcon message={error} />
  const embedding = status?.embedding
  if (!embedding || embedding.mode !== 'hash') return null
  return (
    <Alert
      type="warning"
      showIcon
      message="检索当前使用本地 hash 兜底向量，语义召回能力有限"
      description={(
        <div style={{ fontSize: 13 }}>
          <div>{embedding.reason}</div>
          {embedding.last_error && <div style={{ marginTop: 4 }}>最近一次失败：{embedding.last_error.at}　{embedding.last_error.error}</div>}
          <div style={{ marginTop: 4 }}>恢复方式：配置 EMBEDDING_API_BASE 与 EMBEDDING_API_KEY 后重启后端，再对已有文档执行"重新解析"重建向量。</div>
        </div>
      )}
    />
  )
}
