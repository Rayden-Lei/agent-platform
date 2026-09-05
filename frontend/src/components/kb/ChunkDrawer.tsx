import { Drawer, List, Space, Tag, Typography } from 'antd'
import { listDocChunks, type ChunkRow, type DocumentRow } from '../../api'
import { usePagedList } from '../../hooks/usePagedList'
import EmptyState from '../common/EmptyState'

// 切片抽屉（详情页上唯一一层抽屉）：分页看某文档的切片、token 数与入库时的向量后端。
interface Props { kbId: number; doc: DocumentRow | null; onClose: () => void }

export default function ChunkDrawer({ kbId, doc, onClose }: Props) {
  const list = usePagedList<ChunkRow>((params) => listDocChunks(kbId, doc?.id ?? 0, params), { pageSize: 20, auto: !!doc, emptyText: <EmptyState description="该文档没有切片" /> })
  const pagination = list.tableProps.pagination
  const offset = (pagination.current - 1) * pagination.pageSize
  return (
    <Drawer title={doc ? `切片：${doc.name}（共 ${list.total} 个）` : ''} open={!!doc} onClose={onClose} width={760} destroyOnHidden>
      <List
        loading={list.loading}
        dataSource={list.items}
        pagination={{ current: pagination.current, pageSize: pagination.pageSize, total: pagination.total, onChange: pagination.onChange, size: 'small', showSizeChanger: false }}
        locale={{ emptyText: list.loading ? ' ' : <EmptyState description="该文档没有切片" /> }}
        renderItem={(c, idx) => (
          <List.Item style={{ display: 'block', padding: '12px 0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, marginBottom: 6 }}>
              <Typography.Text strong>#{offset + idx + 1}</Typography.Text>
              <Space size={6} wrap>
                <Tag color="blue">{c.token_count ?? 0} tokens</Tag>
                {/* 入库时的向量后端：hash 表示这批切片是降级入库的，换回真实模型后需要重新解析 */}
                {c.meta?.embedding_mode === 'hash' && <Tag color="orange">hash 向量</Tag>}
                {c.meta?.embedding_mode === 'model' && <Tag color="green">{String(c.meta.embedding_model)}</Tag>}
              </Space>
            </div>
            <Typography.Paragraph style={{ marginBottom: 0, fontSize: 13, color: '#334155', whiteSpace: 'pre-wrap' }} ellipsis={{ rows: 4, expandable: true, symbol: '展开' }}>{c.content}</Typography.Paragraph>
          </List.Item>
        )}
      />
    </Drawer>
  )
}
