import type { ReactNode } from 'react'
import { Col, Row, Skeleton, Statistic, Tooltip } from 'antd'
import { ArrowDownOutlined, ArrowUpOutlined } from '@ant-design/icons'
import { formatPercent } from '../../utils/format'

// 统计卡行：点击卡片可当筛选（active 高亮），可选环比与说明。加载中显示骨架，不显示 0。
export interface StatCardItem {
  key: string
  title: ReactNode
  value: ReactNode
  suffix?: ReactNode
  precision?: number
  color?: string
  icon?: ReactNode
  hint?: ReactNode
  delta?: number | null // 环比，null = 无法比较
  onClick?: () => void
  active?: boolean
}
interface Props {
  items: StatCardItem[]
  loading?: boolean
  cols?: 3 | 4 | 6 | 8
}

export default function StatCards({ items, loading, cols = 4 }: Props) {
  const span = 24 / cols
  return (
    <Row gutter={[12, 12]}>
      {items.map((item) => (
        <Col key={item.key} xs={12} md={span}>
          <Tooltip title={item.hint}>
            <div className={`tech-card stat-card${item.onClick ? ' stat-card-clickable' : ''}${item.active ? ' stat-card-active' : ''}`} onClick={item.onClick}>
              {loading ? <Skeleton active paragraph={{ rows: 1 }} title={false} /> : (
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  {item.icon && <div className="stat-icon" style={{ background: item.color ?? '#1e40af' }}>{item.icon}</div>}
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <Statistic title={item.title} value={item.value as number | string} precision={item.precision} suffix={item.suffix} valueStyle={{ color: item.color, fontSize: 22 }} />
                    {item.delta !== undefined && (
                      <div style={{ fontSize: 12, color: item.delta === null ? '#9ca3af' : item.delta >= 0 ? '#16a34a' : '#dc2626' }}>
                        {item.delta === null ? '较昨日 -' : <>{item.delta >= 0 ? <ArrowUpOutlined /> : <ArrowDownOutlined />} 较昨日 {formatPercent(Math.abs(item.delta))}</>}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </Tooltip>
        </Col>
      ))}
    </Row>
  )
}
