import { Modal, Table, Typography } from 'antd'
import type { BatchResult } from '../../api'

// 批量结果：成功 N 条、失败 M 条，失败逐条列原因（docs/07 第 3 节"批量失败要说明失败了哪几条"）。
interface Props {
  result: BatchResult | null
  onClose: () => void
  nameOf?: (id: number) => string | undefined
}

export default function BatchResultModal({ result, onClose, nameOf }: Props) {
  return (
    <Modal open={!!result} onCancel={onClose} onOk={onClose} cancelButtonProps={{ style: { display: 'none' } }} title="批量操作结果" destroyOnHidden>
      {result && (
        <>
          <Typography.Paragraph>成功 <b>{result.succeeded.length}</b> 项，失败 <b style={{ color: '#dc2626' }}>{result.failed.length}</b> 项。</Typography.Paragraph>
          <Table
            size="small"
            rowKey="id"
            pagination={false}
            dataSource={result.failed}
            columns={[
              { title: 'ID', dataIndex: 'id', width: 80 },
              { title: '名称', width: 160, render: (_: unknown, r) => nameOf?.(r.id) ?? '-' },
              { title: '原因', dataIndex: 'detail' },
            ]}
          />
        </>
      )}
    </Modal>
  )
}
