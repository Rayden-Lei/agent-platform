import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/shadcn/dialog'
import Button from '../ui/Button'
import type { BatchResult } from '../../api'

// 批量结果：成功 N 条、失败 M 条，失败逐条列原因（docs/07 第 3 节"批量失败要说明失败了哪几条"）。
interface Props {
  result: BatchResult | null
  onClose: () => void
  nameOf?: (id: number) => string | undefined
}

export default function BatchResultModal({ result, onClose, nameOf }: Props) {
  return (
    <Dialog open={!!result} onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>批量操作结果</DialogTitle>
        </DialogHeader>
        {result && (
          <div className="flex flex-col gap-3 text-[13px]">
            <p className="m-0">
              成功 <b>{result.succeeded.length}</b> 项，失败 <b className="text-destructive">{result.failed.length}</b> 项。
            </p>
            {result.failed.length > 0 && (
              <div className="max-h-72 overflow-auto rounded-lg border border-border">
                <table className="w-full border-collapse text-[12.5px]">
                  <thead className="bg-secondary">
                    <tr>
                      <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">ID</th>
                      <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">名称</th>
                      <th className="px-2 py-1.5 text-left font-medium text-muted-foreground">原因</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.failed.map((r) => (
                      <tr key={r.id} className="border-t border-border">
                        <td className="px-2 py-1.5">{r.id}</td>
                        <td className="px-2 py-1.5">{nameOf?.(r.id) ?? '-'}</td>
                        <td className="px-2 py-1.5">{r.detail}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="primary" size="md" onClick={onClose}>关闭</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
