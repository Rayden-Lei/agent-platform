import { listDocs, type KnowledgeBaseDetail } from '../../api'
import { useAsyncData } from '../../hooks/useAsyncData'
import ChartCard from '../charts/ChartCard'
import Donut from '../charts/Donut'
import StackedBar from '../charts/StackedBar'
import StatCards from '../layout/StatCards'
import { formatNumber } from '../../utils/format'

// 知识库统计页签：文档状态分布、切片最多的文档 Top 10、总量卡。
// 两栏用 CSS grid 分（12 栅格），不引布局组件；图表卡与统计卡仍是共享件。
interface Props { kb: KnowledgeBaseDetail }

export default function KbStats({ kb }: Props) {
  const top = useAsyncData(() => listDocs(kb.id, { page: 1, page_size: 10, sort: 'chunk_count', order: 'desc' }), [kb.id])
  const slices = [
    { key: 'ready', type: '就绪', value: kb.ready_count },
    { key: 'failed', type: '失败', value: kb.failed_count },
    { key: 'running', type: '处理中', value: kb.processing_count },
  ].filter((s) => s.value > 0)
  const bars = (top.data?.items ?? []).filter((d) => d.chunk_count > 0).map((d) => ({ x: d.name.length > 18 ? d.name.slice(0, 18) + '…' : d.name, value: d.chunk_count }))
  return (
    <div className="flex flex-col gap-3">
      <StatCards cols={4} items={[
        { key: 'docs', title: '文档', value: kb.document_count },
        { key: 'chunks', title: '切片', value: formatNumber(kb.chunk_count) },
        { key: 'tokens', title: 'Token 总量', value: formatNumber(kb.token_count), hint: '按切片的 token 数合计' },
        { key: 'avg', title: '平均每文档切片', value: kb.ready_count ? Math.round(kb.chunk_count / kb.ready_count) : 0 },
      ]} />
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
        <div className="lg:col-span-5">
          <ChartCard title="文档状态分布" empty={!slices.length} emptyText="还没有文档">
            <Donut data={slices} height={236} statusColors />
          </ChartCard>
        </div>
        <div className="lg:col-span-7">
          <ChartCard title="切片最多的文档" loading={top.loading && !top.data} error={top.error} onRetry={() => top.reload()} empty={!bars.length} emptyText="还没有就绪的文档">
            <StackedBar data={bars} horizontal height={236} />
          </ChartCard>
        </div>
      </div>
    </div>
  )
}
