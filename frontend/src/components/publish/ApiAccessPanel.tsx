import { Alert, Button, Card, Collapse, Descriptions, Space, Table, Tabs, Typography, message } from 'antd'
import { CopyOutlined } from '@ant-design/icons'
import { BODY_ROWS, ERROR_ROWS, EVENT_ROWS, KEY_PLACEHOLDER, curlSnippet, endpointRows, jsSnippet, markdownDoc, pythonSnippet, type DocRow } from './apiSnippets'

// 智能体"发布渠道 → API 调用"（docs/15 3.7.2，PB-02）：Base URL、智能体 ID、鉴权方式、端点与请求体、SSE 事件、错误码、
// curl / Python / JS 流式示例与"复制对接说明"（Markdown，Key 用占位符）。数据由页面传入，本组件不发请求。
interface Props {
  agent: { id: number; name: string; status: string }
  baseUrl: string            // 对外地址（PUBLIC_BASE_URL，未配置时是当前访问地址）
  baseUrlConfigured: boolean
}

async function copy(text: string, what: string) {
  try { await navigator.clipboard.writeText(text); message.success(`已复制${what}`) } catch {
    message.warning('浏览器不允许自动复制（http 下剪贴板不可用），请手动选中复制')
  }
}

const docColumns = (first: string) => [
  { title: first, dataIndex: 'name', width: 260, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
  { title: '说明', dataIndex: 'desc' },
]
const DocTable = ({ rows, first }: { rows: DocRow[]; first: string }) => (
  <Table size="small" rowKey="key" pagination={false} dataSource={rows} columns={docColumns(first)} />
)

function Snippet({ code, label }: { code: string; label: string }) {
  return (
    <div style={{ position: 'relative' }}>
      <Button size="small" icon={<CopyOutlined />} style={{ position: 'absolute', top: 8, right: 8 }} onClick={() => copy(code, label)}>复制</Button>
      <pre style={{ background: '#0f172a', color: '#e2e8f0', padding: '12px 14px', borderRadius: 8, fontSize: 12, lineHeight: 1.6, overflow: 'auto', maxHeight: 360, margin: 0 }}>{code}</pre>
    </div>
  )
}

export default function ApiAccessPanel({ agent, baseUrl, baseUrlConfigured }: Props) {
  const api = `${baseUrl}/api/v1`
  const published = agent.status === 'published'
  return (
    <Card size="small" title="API 调用" extra={<Button icon={<CopyOutlined />} onClick={() => copy(markdownDoc(api, agent), '对接说明（Markdown）')}>复制对接说明</Button>}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        {!published && <Alert type="warning" showIcon message={agent.status === 'offline' ? '已下线：按示例调用会返回 403「智能体已下线」，重新发布后恢复' : '发布后才能调用：现在按示例调用会返回 403「智能体未发布」'} />}
        <Alert type="info" showIcon message="API Key 只在服务端调用，不要放进浏览器、小程序或 App；Key 只能调用授权给它的智能体（下方密钥区）" />
        <Descriptions size="small" bordered column={1} items={[
          { key: 'base', label: 'Base URL', children: <Space><Typography.Text code copyable>{api}</Typography.Text>{!baseUrlConfigured && <Typography.Text type="secondary" style={{ fontSize: 12 }}>（未配置 PUBLIC_BASE_URL，这是你当前访问的地址）</Typography.Text>}</Space> },
          { key: 'id', label: '智能体 ID', children: <Typography.Text code copyable>{String(agent.id)}</Typography.Text> },
          { key: 'auth', label: '鉴权', children: <Typography.Text code>{`Authorization: Bearer ${KEY_PLACEHOLDER}`}</Typography.Text> },
        ]} />
        <Tabs size="small" items={[
          { key: 'curl', label: 'curl', children: <Snippet code={curlSnippet(api, agent.id)} label=" curl 示例" /> },
          { key: 'python', label: 'Python', children: <Snippet code={pythonSnippet(api, agent.id)} label=" Python 示例" /> },
          { key: 'js', label: 'JavaScript', children: <Snippet code={jsSnippet(api, agent.id)} label=" JavaScript 示例" /> },
        ]} />
        <Collapse size="small" items={[
          { key: 'endpoints', label: '端点', children: <DocTable rows={endpointRows(agent.id)} first="端点" /> },
          { key: 'body', label: '对话请求体（end_user、client_message_id 幂等）', children: <DocTable rows={BODY_ROWS} first="字段" /> },
          { key: 'events', label: '返回：SSE 事件', children: <DocTable rows={EVENT_ROWS} first="type" /> },
          { key: 'errors', label: '错误码', children: <DocTable rows={ERROR_ROWS} first="状态码" /> },
        ]} />
      </Space>
    </Card>
  )
}
