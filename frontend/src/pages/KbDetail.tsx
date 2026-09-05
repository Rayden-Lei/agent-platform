import { useState } from 'react'
import { Button, Popconfirm, Space, Tag, Typography, message } from 'antd'
import { DeleteOutlined, EditOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { deleteKB, getKB } from '../api'
import { useAsyncData } from '../hooks/useAsyncData'
import DetailPage from '../components/layout/DetailPage'
import StatusTag from '../components/common/StatusTag'
import ResourceLink from '../components/common/ResourceLink'
import EmptyState from '../components/common/EmptyState'
import EmbeddingAlert from '../components/kb/EmbeddingAlert'
import KbForm from '../components/kb/KbForm'
import DocTable from '../components/kb/DocTable'
import SearchEval from '../components/kb/SearchEval'
import KbStats from '../components/kb/KbStats'
import { statusLabel } from '../constants/status'
import { errorText } from '../utils/errors'
import { formatNumber } from '../utils/format'

// 知识库详情页：文档（上传 / 筛选 / 重新解析 / 切片）/ 检索评测 / 统计 / 引用它的智能体；头部编辑与删除。
export default function KbDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const kbId = Number(id)
  const { data: kb, loading, error, reload } = useAsyncData(() => getKB(kbId), [kbId], { errorText: '加载知识库失败' })
  const [editing, setEditing] = useState(false)
  const remove = async () => { try { await deleteKB(kbId); message.success('已删除'); navigate('/knowledge-bases') } catch (e) { message.error(errorText(e, '删除失败')) } }

  return (
    <>
      <DetailPage
        crumbs={[{ label: '知识库', to: '/knowledge-bases' }, { label: kb?.name ?? `#${kbId}` }]}
        title={kb?.name ?? ''}
        tags={kb && <Space size={4}><StatusTag domain="visibility" value={kb.is_public} />{!kb.is_public && (kb.visible_roles || []).map((r) => <Tag key={r}>{statusLabel('role', r)}</Tag>)}<Tag>{kb.embedding_model}</Tag></Space>}
        meta={kb ? [
          { label: '文档', value: <span>{kb.document_count}{kb.failed_count > 0 && <Tag color="error" style={{ marginLeft: 6 }}>失败 {kb.failed_count}</Tag>}{kb.processing_count > 0 && <Tag color="processing" style={{ marginLeft: 6 }}>处理中 {kb.processing_count}</Tag>}</span> },
          { label: '切片 / Token', value: `${formatNumber(kb.chunk_count)} / ${formatNumber(kb.token_count)}` },
          { label: '切片参数', value: `${kb.chunk_size} / 重叠 ${kb.chunk_overlap}` },
          { label: '创建人', value: kb.created_by_username || '-' },
        ] : []}
        loading={loading && !kb}
        error={error}
        onRetry={() => reload()}
        backTo="/knowledge-bases"
        extra={kb && (
          <Space>
            <Button icon={<EditOutlined />} onClick={() => setEditing(true)}>编辑</Button>
            <Popconfirm title="确定删除？文档与切片会一并删除" onConfirm={remove}><Button danger icon={<DeleteOutlined />}>删除</Button></Popconfirm>
          </Space>
        )}
        tabs={kb ? [
          { key: 'documents', label: `文档（${kb.document_count}）`, children: <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}><EmbeddingAlert /><DocTable kbId={kb.id} onChanged={() => reload(true)} /></div> },
          { key: 'search', label: '检索评测', children: <SearchEval kbId={kb.id} /> },
          { key: 'stats', label: '统计', children: <KbStats kb={kb} /> },
          {
            key: 'agents', label: `引用（${kb.agents.length}）`, children: kb.agents.length ? (
              <Space direction="vertical">
                <Typography.Text type="secondary">绑定了该知识库的智能体；改权限或重新解析会影响它们的检索结果。</Typography.Text>
                {kb.agents.map((a) => <span key={a.id}><ResourceLink type="agent" id={a.id} name={a.name} showIcon /> <StatusTag domain="agent" value={a.status} /></span>)}
              </Space>
            ) : <EmptyState description="还没有智能体绑定该知识库；在智能体表单里选择即可" />,
          },
        ] : []}
      />
      <KbForm open={editing} editing={kb} onClose={() => setEditing(false)} onSaved={() => reload(true)} />
    </>
  )
}
