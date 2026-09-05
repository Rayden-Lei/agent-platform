import { ClockCircleOutlined, DatabaseOutlined, FileTextOutlined, KeyOutlined, PartitionOutlined, RobotOutlined, TeamOutlined, ThunderboltOutlined, ToolOutlined } from '@ant-design/icons'
import type { StatsOverview } from '../../api'
import StatCards from '../layout/StatCards'

// 资源概览：各类资源计数（含子状态），点击进对应列表。
interface Props { resources: StatsOverview['resources'] | null; loading: boolean; onGo: (path: string) => void }

export default function ResourceSummary({ resources, loading, onGo }: Props) {
  const r = resources
  const items = [
    { key: 'agents', title: '智能体', value: r?.agents ?? 0, suffix: r ? <span style={{ fontSize: 12, color: '#6b7280' }}>/ 已发布 {r.published_agents}</span> : undefined, icon: <RobotOutlined />, color: '#1e40af', onClick: () => onGo('/agents') },
    { key: 'models', title: '模型', value: r?.models ?? 0, suffix: r ? <span style={{ fontSize: 12, color: '#6b7280' }}>/ 启用 {r.enabled_models}</span> : undefined, icon: <ThunderboltOutlined />, color: '#0e7490', onClick: () => onGo('/models') },
    { key: 'workflows', title: '工作流', value: r?.workflows ?? 0, icon: <PartitionOutlined />, color: '#b45309', onClick: () => onGo('/workflows') },
    { key: 'kbs', title: '知识库', value: r?.knowledge_bases ?? 0, suffix: r ? <span style={{ fontSize: 12, color: '#6b7280' }}>/ 文档 {r.documents}</span> : undefined, icon: <DatabaseOutlined />, color: '#15803d', onClick: () => onGo('/knowledge-bases') },
    { key: 'tools', title: '工具', value: r?.tools ?? 0, icon: <ToolOutlined />, color: '#0f766e', onClick: () => onGo('/tools') },
    { key: 'templates', title: '提示词模板', value: r?.prompt_templates ?? 0, icon: <FileTextOutlined />, color: '#334155', onClick: () => onGo('/prompt-templates') },
    { key: 'keys', title: '启用的 API Key', value: r?.api_keys ?? 0, icon: <KeyOutlined />, color: '#9a3412', onClick: () => onGo('/api-keys') },
    { key: 'schedules', title: '启用的定时任务', value: r?.schedules ?? 0, icon: <ClockCircleOutlined />, color: '#6b7280', onClick: () => onGo('/schedules') },
  ]
  return <StatCards items={items} loading={loading} cols={4} />
}

export const usersIcon = <TeamOutlined />
