import { useState } from 'react'
import { toast } from 'sonner'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import InlineConfirm from '../ui/InlineConfirm'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'
import { getAgentVersions, restoreAgentVersion, rollbackAgent, type AgentDetail, type AgentVersionRow } from '../../api'
import { usePagedList } from '../../hooks/usePagedList'
import EmptyState from '../common/EmptyState'
import JsonView from '../common/JsonView'
import TimeCell from '../common/TimeCell'
import DataTable, { type DataColumn } from '../table/DataTable'
import SnapshotDiff, { type RefNames } from './SnapshotDiff'
import { errorText } from '../../utils/errors'

// 版本历史（发布语义，docs/15 3.2）：每个发布版本是不可变快照。两种操作语义不同 ——
// 恢复到草稿：草稿 = 该版本，线上不变（日常改版用）；回滚上线：用该版本生成新版本并立即上线，草稿不动（线上出事一键止血）。
// "与草稿对比"用后端给的同形快照（草稿 draft_snapshot、版本 snapshot 已补齐字段），前端不维护字段清单。
interface Props { agent: AgentDetail; onChanged: () => void }

export default function AgentVersionsTab({ agent, onChanged }: Props) {
  const list = usePagedList<AgentVersionRow>((params) => getAgentVersions(agent.id, params), { pageSize: 10 })
  const [compare, setCompare] = useState<AgentVersionRow | null>(null)
  const [snapshotOf, setSnapshotOf] = useState<AgentVersionRow | null>(null)
  // 名称只认得草稿引用的对象与该版本的模型；其余（已删除、草稿已不再引用）显示 ID
  const names = (v: AgentVersionRow): RefNames => ({
    model: { ...(agent.model ? { [agent.model.id]: agent.model.name } : {}), ...(v.model_name ? { [v.snapshot.model_id as number]: v.model_name } : {}) },
    kb: Object.fromEntries(agent.knowledge_bases.map((k) => [k.id, k.name])),
    tool: Object.fromEntries(agent.tools.map((t) => [t.id, t.name])),
  })

  const done = () => { list.reload(); onChanged() }
  const restore = async (v: AgentVersionRow) => {
    try { await restoreAgentVersion(agent.id, v.id); toast.success(`草稿已恢复为 v${v.version}，发布后对外生效`); done() } catch (e) { toast.error(errorText(e, '恢复失败')) }
  }
  const rollback = async (v: AgentVersionRow) => {
    try {
      const r = await rollbackAgent(agent.id, v.id)
      toast.success(r.publish_result === 'unchanged' ? '线上已是这个版本的内容' : `已回滚上线，线上为 v${r.published_version}（内容同 v${v.version}）`)
      done()
    } catch (e) { toast.error(errorText(e, '回滚失败')) }
  }

  const columns: DataColumn<AgentVersionRow>[] = [
    {
      key: 'version', header: '版本', width: 110,
      cell: (v) => (
        <span className="inline-flex items-center gap-1.5">
          <span className="text-[13px]">v{v.version}</span>
          {v.is_live && <Badge tone="success">线上</Badge>}
        </span>
      ),
    },
    { key: 'created_at', header: '发布时间', width: 170, cell: (v) => <TimeCell value={v.created_at} /> },
    { key: 'created_by_username', header: '发布人', width: 100, cell: (v) => v.created_by_username || '-' },
    { key: 'note', header: '说明', width: 220, hideOnMobile: true, cell: (v) => <span className="block truncate" title={v.note ?? undefined}>{v.note || '-'}</span> },
    {
      key: 'model_name', header: '模型', width: 140, hideOnMobile: true,
      cell: (v) => <span className="block truncate">{v.model_name || `#${(v.snapshot as { model_id?: number }).model_id ?? '-'}（已删除）`}</span>,
    },
    {
      key: 'prompt_template_name', header: '模板', width: 120, hideOnMobile: true,
      cell: (v) => (v.prompt_template_name ? `${v.prompt_template_name} v${(v.snapshot as { prompt_template_version?: number }).prompt_template_version ?? ''}` : '手填'),
    },
    {
      key: 'snapshot', header: '快照', width: 76, hideOnMobile: true,
      // 原来用表格的展开行展示快照 JSON；DataTable 没有展开行，改成单元格里的按钮 + 弹窗
      cell: (v) => (
        <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); setSnapshotOf(v) }}>查看</Button>
      ),
    },
    {
      key: 'actions', header: '操作', width: 268, pinRight: true,
      cell: (v) => (
        <span className="inline-flex flex-wrap items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button size="sm" variant="secondary" onClick={() => setCompare(v)}>与草稿对比</Button>
          <InlineConfirm message={`草稿恢复为 v${v.version}？当前草稿会被覆盖，线上不变`} confirmLabel="恢复" onConfirm={() => restore(v)}>
            <Button size="sm" variant="secondary">恢复到草稿</Button>
          </InlineConfirm>
          {v.is_live ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <span><Button size="sm" variant="danger" disabled>回滚上线</Button></span>
              </TooltipTrigger>
              <TooltipContent>已是线上版本</TooltipContent>
            </Tooltip>
          ) : (
            <InlineConfirm message={`用 v${v.version} 生成新版本并立即上线？草稿不变`} confirmLabel="回滚" onConfirm={() => rollback(v)}>
              <Button size="sm" variant="danger">回滚上线</Button>
            </InlineConfirm>
          )}
        </span>
      ),
    },
  ]

  return (
    <>
      <DataTable
        columns={columns}
        rows={list.items}
        rowKey={(v) => v.id}
        loading={list.loading}
        error={list.error}
        empty={<EmptyState description="还没有发布版本；发布后会生成快照，可在此对比、恢复到草稿或回滚上线。" />}
        onRetry={list.reload}
        page={list.page}
        pageSize={list.pageSize}
        total={list.total}
        onPageChange={list.load}
      />
      <Modal
        open={!!compare}
        size="lg"
        title={compare ? `v${compare.version} 与当前草稿的差异` : ''}
        onClose={() => setCompare(null)}
        footer={<Button variant="secondary" size="md" onClick={() => setCompare(null)}>关闭</Button>}
      >
        {compare && <SnapshotDiff before={compare.snapshot} after={agent.draft_snapshot} names={names(compare)} />}
      </Modal>
      <Modal
        open={!!snapshotOf}
        size="lg"
        title={snapshotOf ? `v${snapshotOf.version} 的发布快照` : ''}
        onClose={() => setSnapshotOf(null)}
        footer={<Button variant="secondary" size="md" onClick={() => setSnapshotOf(null)}>关闭</Button>}
      >
        {snapshotOf && <JsonView title="快照" value={snapshotOf.snapshot} maxHeight={420} />}
      </Modal>
    </>
  )
}
