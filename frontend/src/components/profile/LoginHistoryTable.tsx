import { Table, Tag, Typography } from 'antd'
import type { LoginRecord } from '../../api'
import ErrorState from '../common/ErrorState'
import TimeCell from '../common/TimeCell'

// 个人中心"登录记录"（docs/15 OP-03）：近 90 天最近 20 次，含用你的用户名输错密码的尝试——看到不认识的来源 IP 就该改密并退出其他设备。
// 数据由页面传入。
interface Props { rows: LoginRecord[] | null; error?: string | null; onRetry: () => void }

export default function LoginHistoryTable({ rows, error, onRetry }: Props) {
  if (error) return <ErrorState compact message={error} onRetry={onRetry} />
  return (
    <>
      <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>近 90 天最近 20 次登录，包括用你的用户名输错密码的尝试。看到不认识的来源，请修改密码并退出其他设备。</Typography.Paragraph>
      <Table size="small" rowKey={(r) => `${r.created_at}-${r.success}`} loading={!rows} dataSource={rows ?? []} pagination={false} style={{ maxWidth: 560 }}
        columns={[
          { title: '时间', dataIndex: 'created_at', render: (v: string) => <TimeCell value={v} /> },
          { title: '来源 IP', dataIndex: 'ip', render: (v: string | null) => v || '-' },
          { title: '结果', dataIndex: 'success', render: (v: boolean) => (v ? <Tag color="green">成功</Tag> : <Tag color="red">密码错误</Tag>) },
        ]} />
    </>
  )
}
