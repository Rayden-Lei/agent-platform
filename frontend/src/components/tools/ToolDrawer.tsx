import { Button, Descriptions, Drawer, Space, Table, Tag, Typography } from 'antd'
import { ExperimentOutlined } from '@ant-design/icons'
import { getTool, type ToolProperty, type ToolRow } from '../../api'
import { useAsyncData } from '../../hooks/useAsyncData'
import ErrorState from '../common/ErrorState'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { TYPE_OPTIONS } from './ToolParamsEditor'

// 工具详情抽屉：请求配置、鉴权（只显示方式与是否已配置，凭据不回显）、参数声明表、绑定它的智能体；测试 / 编辑在头部。
// 请求头里已不允许放凭据（保存时 422），所以直接显示值
interface Props { tool: ToolRow | null; canManage: boolean; onClose: () => void; onTest: (tool: ToolRow) => void; onEdit: (tool: ToolRow) => void }

const AUTH_LABEL: Record<string, string> = { bearer: 'Bearer Token', api_key: 'API Key', basic: 'Basic' }
function authText(tool: ToolRow) {
  const auth = tool.auth
  if (!auth || auth.type === 'none') return <Typography.Text type="secondary">不需要</Typography.Text>
  const where = auth.type === 'api_key' ? `（${auth.location === 'query' ? '查询参数' : '请求头'} ${auth.name}）` : ''
  return <Space size={6}>{AUTH_LABEL[auth.type] ?? auth.type}{where}{auth.has_secret ? <Tag color="success">凭据已配置</Tag> : <Tag color="error">缺少凭据</Tag>}</Space>
}

export default function ToolDrawer({ tool, canManage, onClose, onTest, onEdit }: Props) {
  const id = tool?.id ?? 0
  const detail = useAsyncData(() => getTool(id), [id], { auto: !!tool, errorText: '加载工具详情失败' })
  const params = tool?.config?.parameters
  const rows = Object.entries(params?.properties || {}).map(([name, p]: [string, ToolProperty]) => ({ name, ...p, required: (params?.required || []).includes(name) }))
  const headerNames = Object.keys(tool?.config?.headers || {})
  return (
    <Drawer title={tool ? `工具：${tool.name}` : ''} open={!!tool} onClose={onClose} width={720} destroyOnHidden
      extra={tool && <Space><Button icon={<ExperimentOutlined />} onClick={() => onTest(tool)}>测试</Button><Button type="primary" disabled={!canManage} onClick={() => onEdit(tool)}>编辑</Button></Space>}>
      {tool && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Descriptions size="small" bordered column={2} items={[
            { key: 'type', label: '类型', children: <StatusTag domain="toolType" value={tool.type} /> },
            { key: 'enabled', label: '状态', children: <StatusTag domain="enabled" value={tool.is_enabled} /> },
            { key: 'desc', label: '描述', span: 2, children: tool.description },
            ...(tool.type === 'http' ? [
              { key: 'req', label: '请求', span: 2, children: <Space size={4}><Tag>{(tool.config?.method || 'POST').toUpperCase()}</Tag><Typography.Text copyable>{tool.config?.url || '-'}</Typography.Text></Space> },
              { key: 'headers', label: '请求头', span: 2, children: headerNames.length ? <Space size={4} wrap>{headerNames.map((h) => <Tag key={h}>{h}: {tool.config?.headers?.[h]}</Tag>)}</Space> : <Typography.Text type="secondary">无</Typography.Text> },
              { key: 'auth', label: '鉴权', span: 2, children: authText(tool) },
            ] : []),
            { key: 'timeout', label: '超时', children: `${tool.timeout} 秒` },
            { key: 'agents', label: '绑定智能体', children: tool.agents_count },
            { key: 'creator', label: '创建人', children: tool.created_by_username || '-' },
            { key: 'updated', label: '更新时间', children: <TimeCell value={tool.updated_at} /> },
          ]} />
          {tool.type === 'http' && (
            <div>
              <Typography.Text strong>参数声明（{rows.length}）</Typography.Text>
              {rows.length ? (
                <Table size="small" rowKey="name" pagination={false} style={{ marginTop: 8 }} dataSource={rows} columns={[
                  { title: '参数', dataIndex: 'name', width: 160, render: (v: string, r) => <span>{v}{r.required && <span style={{ color: '#dc2626' }}> *</span>}</span> },
                  { title: '类型', dataIndex: 'type', width: 90, render: (v: string) => TYPE_OPTIONS.find((o) => o.value === v)?.label ?? v },
                  { title: '说明', dataIndex: 'description', render: (v?: string) => v || '-' },
                  { title: '枚举', dataIndex: 'enum', width: 200, render: (v?: string[]) => (v?.length ? <Space size={4} wrap>{v.map((x) => <Tag key={x}>{x}</Tag>)}</Space> : '-') },
                ]} />
              ) : <div style={{ marginTop: 8 }}><Tag color="warning">未声明参数：模型只能以空参数调用，建议补充声明</Tag></div>}
            </div>
          )}
          <div>
            <Typography.Text strong>绑定它的智能体（{tool.agents_count}）</Typography.Text>
            <div style={{ marginTop: 8 }}>
              {detail.error ? <ErrorState compact message={detail.error} onRetry={() => detail.reload()} /> : detail.data?.agents.length ? (
                <Space direction="vertical" size={4}>
                  {detail.data.agents.map((a) => <span key={a.id}><ResourceLink type="agent" id={a.id} name={a.name} showIcon /> <StatusTag domain="agent" value={a.status} /></span>)}
                </Space>
              ) : <Typography.Text type="secondary">{detail.loading ? '加载中…' : '没有智能体绑定该工具'}</Typography.Text>}
            </div>
          </div>
          {!tool.is_enabled && <Tag color="warning">已停用：智能体对话不会带上该工具，工作流工具节点会直接失败</Tag>}
        </div>
      )}
    </Drawer>
  )
}
