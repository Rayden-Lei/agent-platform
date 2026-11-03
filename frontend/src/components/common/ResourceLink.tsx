import { Link } from 'react-router-dom'
import { RESOURCES, type ResourceType } from '../../constants/resources'

// 关联跳转的统一写法：按资源类型生成到详情页（/agents/3）或列表抽屉（/models?open=3）的链接；无 name 时显示 #id。
interface Props {
  type: ResourceType
  id?: number | null
  name?: string | null
  showIcon?: boolean
}

export default function ResourceLink({ type, id, name, showIcon = false }: Props) {
  if (id === null || id === undefined) return <span style={{ color: 'var(--fg-subtle)' }}>-</span>
  const meta = RESOURCES[type]
  return (
    <Link
      to={meta.link(id)}
      onClick={(e) => e.stopPropagation()}
      className="whitespace-nowrap hover:underline"
      style={{ color: 'var(--accent)' }}
    >
      {showIcon && <span style={{ marginRight: 4 }}>{meta.icon}</span>}
      {name || `#${id}`}
    </Link>
  )
}
