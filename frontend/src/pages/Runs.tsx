import { useEffect, useState } from 'react'
import { Table, Tag, message, Card, Col, Row, Statistic, Modal, Descriptions, Button, Space, Typography } from 'antd'
import { EyeOutlined, CheckOutlined, CloseOutlined } from '@ant-design/icons'
import { listRuns, getRun, resumeWorkflow } from '../api'

const runTypeLabel: Record<string, string> = { chat: '对话', workflow: '工作流' }

const statusColor = (v: string) => v === 'success' ? 'green' : v === 'running' ? 'blue' : v === 'awaiting_review' ? 'orange' : v === 'failed' ? 'red' : 'default'

export default function Runs() {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<any>(null)
  const [resuming, setResuming] = useState(false)

  const load = async () => {
    setLoading(true)
    try { setData(await listRuns() as any) } catch (e: any) { message.error(e.response?.data?.detail || '加载失败') } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const doResume = async (decision: any) => {
    if (!detail?.workflow_id) return
    setResuming(true)
    try {
      await resumeWorkflow(detail.workflow_id, detail.id, decision)
      message.success('已提交审核结果')
      setDetail(null)
      load()
    } catch (e: any) { message.error(e.response?.data?.detail || '操作失败') } finally { setResuming(false) }
  }

  const total = data.length
  const success = data.filter((r) => r.status === 'success').length
  const failed = data.filter((r) => r.status === 'failed').length
  const running = data.filter((r) => r.status === 'running').length
  const totalTokens = data.reduce((s, r) => s + (r.token_usage?.total_tokens || 0), 0)
  const totalCost = data.reduce((s, r) => s + (r.cost || 0), 0)

  const viewDetail = async (id: number) => {
    try {
      const res: any = await getRun(id)
      setDetail(res)
    } catch (e: any) { message.error('加载详情失败') }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    { title: '类型', dataIndex: 'run_type', width: 90, render: (v: string) => runTypeLabel[v] || v },
    { title: '状态', dataIndex: 'status', width: 110, render: (v: string) => <Tag color={statusColor(v)}>{v}</Tag> },
    { title: 'Token', dataIndex: ['token_usage', 'total_tokens'], width: 90, render: (v: number) => v || '-' },
    { title: '成本(元)', dataIndex: 'cost', width: 100, render: (v: number) => v != null ? v.toFixed(4) : '-' },
    { title: '耗时(ms)', dataIndex: 'latency_ms', width: 100 },
    { title: '错误', dataIndex: 'error', ellipsis: true },
    { title: '操作', width: 80, render: (_: any, r: any) => <Button size="small" icon={<EyeOutlined />} onClick={() => viewDetail(r.id)}>详情</Button> },
  ]

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ flexShrink: 0 }}>
        <h2 style={{ marginBottom: 16 }}>运行记录</h2>
        <Row gutter={[16, 16]}>
          <Col xs={12} md={6}><Card className="tech-card"><Statistic title="总运行" value={total} /></Card></Col>
          <Col xs={12} md={6}><Card className="tech-card"><Statistic title="成功" value={success} valueStyle={{ color: '#16a34a' }} /></Card></Col>
          <Col xs={12} md={6}><Card className="tech-card"><Statistic title="失败" value={failed} valueStyle={{ color: '#dc2626' }} /></Card></Col>
          <Col xs={12} md={6}><Card className="tech-card"><Statistic title="Token 消耗" value={totalTokens} /></Card></Col>
          <Col xs={12} md={6}><Card className="tech-card"><Statistic title="总成本(元)" value={totalCost} precision={4} /></Card></Col>
        </Row>
      </div>

      <div className="fixed-table-wrapper">
        <Table rowKey="id" loading={loading} dataSource={data} columns={columns} scroll={{ x: 'max-content' }} pagination={{ position: ['bottomRight'], showSizeChanger: true, showTotal: (t) => '共 ' + t + ' 条' }} />
      </div>

      <Modal title={'运行详情 #' + (detail?.id || '')} open={!!detail} onCancel={() => setDetail(null)} footer={null} width={720}>
        {detail && (
          <div>
            <Descriptions column={2} size="small" bordered style={{ marginBottom: 16 }}>
              <Descriptions.Item label="类型">{runTypeLabel[detail.run_type] || detail.run_type}</Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color={statusColor(detail.status)}>{detail.status}</Tag></Descriptions.Item>
              <Descriptions.Item label="耗时">{detail.latency_ms} ms</Descriptions.Item>
              <Descriptions.Item label="Token">{JSON.stringify(detail.token_usage || {})}</Descriptions.Item>
            </Descriptions>
            <Typography.Text strong>输入：</Typography.Text>
            <pre style={{ background: '#f8fafc', padding: 12, borderRadius: 6, maxHeight: 150, overflow: 'auto', fontSize: 12 }}>{JSON.stringify(detail.input, null, 2)}</pre>
            <Typography.Text strong>输出：</Typography.Text>
            <pre style={{ background: '#f8fafc', padding: 12, borderRadius: 6, maxHeight: 150, overflow: 'auto', fontSize: 12 }}>{JSON.stringify(detail.output, null, 2)}</pre>
            {detail.status === 'awaiting_review' && (
              <>
                <Typography.Text strong type="warning">等待人工审核：</Typography.Text>
                <pre style={{ background: '#fffbeb', padding: 12, borderRadius: 6, maxHeight: 150, overflow: 'auto', fontSize: 12, color: '#92400e' }}>{JSON.stringify(detail.output?.interrupt, null, 2)}</pre>
                <Space style={{ marginTop: 8 }}>
                  <Button type="primary" size="small" icon={<CheckOutlined />} loading={resuming} onClick={() => doResume({ decision: 'approved' })}>通过</Button>
                  <Button danger size="small" icon={<CloseOutlined />} loading={resuming} onClick={() => doResume({ decision: 'rejected' })}>拒绝</Button>
                </Space>
              </>
            )}
            {detail.error && (
              <>
                <Typography.Text strong type="danger">错误：</Typography.Text>
                <pre style={{ background: '#fef2f2', padding: 12, borderRadius: 6, maxHeight: 150, overflow: 'auto', fontSize: 12, color: '#dc2626' }}>{detail.error}</pre>
              </>
            )}
            {detail.nodes && detail.nodes.length > 0 && (
              <>
                <Typography.Text strong>节点日志：</Typography.Text>
                <Table
                  size="small"
                  style={{ marginTop: 8 }}
                  rowKey={(r: any) => r.node_id + r.status}
                  dataSource={detail.nodes}
                  pagination={false}
                  columns={[
                    { title: '节点', dataIndex: 'node_id' },
                    { title: '类型', dataIndex: 'node_type' },
                    { title: '状态', dataIndex: 'status', render: (v: string) => <Tag color={v === 'success' ? 'green' : 'red'}>{v}</Tag> },
                    { title: '错误', dataIndex: 'error', ellipsis: true },
                  ]}
                />
              </>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}