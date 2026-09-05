import { useState } from 'react'
import { Button, Popconfirm, Space, Tag, message } from 'antd'
import { CopyOutlined, DeleteOutlined, EditOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { deleteWorkflow, duplicateWorkflow, getWorkflow } from '../api'
import { useAsyncData } from '../hooks/useAsyncData'
import DetailPage from '../components/layout/DetailPage'
import StatusTag from '../components/common/StatusTag'
import TimeCell from '../components/common/TimeCell'
import AgentStatsTab from '../components/agents/AgentStatsTab'
import RunsTable from '../components/runs/RunsTable'
import WorkflowOverview from '../components/workflows/WorkflowOverview'
import RunWorkflowModal from '../components/workflows/RunWorkflowModal'
import { errorText } from '../utils/errors'

// 工作流详情页：概览（流程图 / 定时任务 / 引用）、运行统计、运行记录；头部运行 / 编辑 / 复制 / 删除。
export default function WorkflowDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const wfId = Number(id)
  const { data: wf, loading, error, reload } = useAsyncData(() => getWorkflow(wfId), [wfId], { errorText: '加载工作流失败' })
  const [running, setRunning] = useState(false)
  const remove = async () => { try { await deleteWorkflow(wfId); message.success('已删除'); navigate('/workflows') } catch (e) { message.error(errorText(e, '删除失败')) } }
  const duplicate = async () => {
    try { const copy = await duplicateWorkflow(wfId); message.success(`已复制为「${copy.name}」`); navigate(`/workflows/${copy.id}`) } catch (e) { message.error(errorText(e, '复制失败')) }
  }

  return (
    <>
      <DetailPage
        crumbs={[{ label: '工作流', to: '/workflows' }, { label: wf?.name ?? `#${wfId}` }]}
        title={wf?.name ?? ''}
        tags={wf && <Space size={4}><StatusTag domain="workflow" value={wf.status} /><Tag>v{wf.version}</Tag></Space>}
        meta={wf ? [
          { label: '节点', value: wf.node_count },
          { label: '定时任务', value: wf.schedules_count },
          { label: '近 7 天运行', value: wf.runs_7d ? <Link to={`/runs?workflow_id=${wf.id}`}>{wf.runs_7d}</Link> : 0 },
          { label: '最近运行', value: <TimeCell value={wf.last_run_at} mode="relative" /> },
          { label: '创建人', value: wf.created_by_username || '-' },
        ] : []}
        loading={loading && !wf}
        error={error}
        onRetry={() => reload()}
        backTo="/workflows"
        extra={wf && (
          <Space>
            <Button type="primary" icon={<PlayCircleOutlined />} disabled={!wf.node_count} onClick={() => setRunning(true)}>运行</Button>
            <Button icon={<EditOutlined />} onClick={() => navigate(`/workflows/${wf.id}/edit`)}>编辑</Button>
            <Button icon={<CopyOutlined />} onClick={duplicate}>复制</Button>
            <Popconfirm title="确定删除？关联的定时任务会一并删除" onConfirm={remove}><Button danger icon={<DeleteOutlined />}>删除</Button></Popconfirm>
          </Space>
        )}
        tabs={wf ? [
          { key: 'overview', label: '概览', children: <WorkflowOverview workflow={wf} /> },
          { key: 'stats', label: '运行统计', children: <AgentStatsTab workflowId={wf.id} /> },
          { key: 'runs', label: '运行记录', children: <RunsTable filters={{ workflow_id: wf.id }} hideOwner={false} /> },
        ] : []}
      />
      {wf && <RunWorkflowModal workflow={running ? wf : null} onClose={() => setRunning(false)} onDone={() => reload(true)} />}
    </>
  )
}
