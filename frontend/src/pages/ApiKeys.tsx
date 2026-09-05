import { useState } from 'react'
import { Table, Button, Modal, Form, Input, InputNumber, message, Popconfirm, Space, Tag, Tooltip } from 'antd'
import { PlusOutlined, KeyOutlined } from '@ant-design/icons'
import { listApiKeys, createApiKey, updateApiKey, toggleApiKey, deleteApiKey } from '../api'
import type { ApiKeyRow } from '../api'
import { usePagedList } from '../hooks/usePagedList'

// API Key 管理页：生成调用方密钥（明文仅创建时返回一次）、编辑配额 / 来源白名单 / 限速、启用/禁用、删除。
// 列表展示配额与已用量，key 本身只显示前缀，防止泄露完整密钥。
// developer 只看到本人创建的 Key（服务端按归属过滤），admin 看全部。

// 表单里的白名单用多行文本承载（一行一条），提交前拆成数组；空行忽略
const splitIps = (text?: string): string[] => (text ?? '').split(/\r?\n/).map((s) => s.trim()).filter(Boolean)

// 表单值 → 接口入参；表单只负责收集，字段合法性（CIDR、范围）由服务端 422 兜底
const toPayload = (values: any) => ({
  name: values.name,
  quota: values.quota ?? 1000,
  allowed_ips: splitIps(values.allowed_ips_text),
  rate_limit_per_minute: values.rate_limit_per_minute ?? 0,
})

// 422 是逐字段数组，取第一条的 msg 给用户看；其余错误按 detail 字符串展示
const errorText = (e: any, fallback: string): string => {
  const detail = e.response?.data?.detail
  if (Array.isArray(detail)) return detail[0]?.msg?.replace(/^Value error, /, '') || fallback
  return detail || fallback
}

export default function ApiKeys() {
  const { tableProps, reload } = usePagedList<ApiKeyRow>(listApiKeys)
  const [open, setOpen] = useState(false)
  // editing 非空表示当前弹窗处于编辑模式（提交时走 update），否则为新增（走 create）
  const [editing, setEditing] = useState<ApiKeyRow | null>(null)
  // 创建成功后服务端返回的明文 Key，展示后用户复制保存，刷新即不可再见
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const [form] = Form.useForm()

  const openCreate = () => { setEditing(null); form.resetFields(); setOpen(true) }
  const openEdit = (row: ApiKeyRow) => {
    setEditing(row)
    form.setFieldsValue({ name: row.name, quota: row.quota, allowed_ips_text: row.allowed_ips.join('\n'), rate_limit_per_minute: row.rate_limit_per_minute })
    setOpen(true)
  }

  // 新增/编辑共用提交：editing 非空走更新接口，否则走创建接口；成功后关弹窗并刷新列表
  const onSubmit = async (values: any) => {
    try {
      if (editing) {
        await updateApiKey(editing.id, toPayload(values))
        message.success('已保存')
      } else {
        // 创建接口返回一次明文 key，存入 createdKey 供"仅显示一次"弹窗展示
        const res = await createApiKey(toPayload(values))
        setCreatedKey(res.key)
      }
      setOpen(false)
      form.resetFields()
      reload()
    } catch (e: any) { message.error(errorText(e, editing ? '保存失败' : '创建失败')) }
  }

  // 通用操作包装：执行一次写操作（启用/禁用/删除）→ 成功后刷新列表，失败统一取后端 detail 提示
  const act = async (fn: () => Promise<unknown>, fallback: string) => {
    try { await fn(); reload() } catch (e: any) { message.error(errorText(e, fallback)) }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '名称', dataIndex: 'name' },
    { title: 'Key', dataIndex: 'key_prefix', render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v}</span> },
    { title: '配额', dataIndex: 'quota', width: 90 },
    { title: '已用', dataIndex: 'used', width: 90 },
    { title: '允许的 IP', dataIndex: 'allowed_ips', width: 110, render: (v: string[]) => v.length === 0
      ? <span style={{ color: '#94a3b8' }}>不限制</span>
      : <Tooltip title={<div style={{ fontFamily: 'monospace', whiteSpace: 'pre-line' }}>{v.join('\n')}</div>}><Tag>{v.length} 条</Tag></Tooltip> },
    { title: '限速/分钟', dataIndex: 'rate_limit_per_minute', width: 100, render: (v: number) => v === 0 ? <span style={{ color: '#94a3b8' }}>默认</span> : v },
    { title: '状态', dataIndex: 'is_enabled', width: 90, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '禁用'}</Tag> },
    { title: '最后使用', dataIndex: 'last_used_at', width: 170, render: (v: string | null) => v ? new Date(v).toLocaleString() : '-' },
    { title: '操作', render: (_: any, r: ApiKeyRow) => (
      <Space>
        <Button size="small" onClick={() => openEdit(r)}>编辑</Button>
        <Button size="small" onClick={() => act(() => toggleApiKey(r.id), '操作失败')}>{r.is_enabled ? '禁用' : '启用'}</Button>
        <Popconfirm title="确定删除？" onConfirm={() => act(() => deleteApiKey(r.id), '删除失败')}><Button size="small" danger>删除</Button></Popconfirm>
      </Space>
    ) },
  ]

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
        <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}><KeyOutlined /> API Key 管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>生成 Key</Button>
      </div>
      <div className="fixed-table-wrapper">
        <Table rowKey="id" {...tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      </div>

      <Modal title={editing ? `编辑 API Key：${editing.name}` : '生成 API Key'} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnHidden>
        <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ quota: 1000, rate_limit_per_minute: 0 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }, { max: 64 }]}><Input placeholder="如：生产环境调用" /></Form.Item>
          <Form.Item name="quota" label="配额(调用次数)" rules={[{ required: true }]}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="allowed_ips_text" label="允许的来源 IP（一行一条，IP 或 CIDR；留空不限制）" extra="不在名单内的来源会被拒绝（403）且不扣配额。最多 50 条。">
            <Input.TextArea rows={3} placeholder={'10.20.0.0/16\n203.0.113.8'} style={{ fontFamily: 'monospace' }} />
          </Form.Item>
          <Form.Item name="rate_limit_per_minute" label="每分钟限速" extra="0 表示使用服务端全局默认；超限返回 429 且不扣配额。">
            <InputNumber min={0} max={10000} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="API Key 已生成（仅显示一次，请复制保存）" open={!!createdKey} onCancel={() => setCreatedKey(null)} footer={<Button type="primary" onClick={() => setCreatedKey(null)}>我已保存</Button>}>
        <div style={{ background: '#f8fafc', border: '1px solid #e5e7eb', borderRadius: 6, padding: 12, fontFamily: 'monospace', wordBreak: 'break-all' }}>{createdKey}</div>
        <div style={{ marginTop: 10, fontSize: 12, color: '#64748b', lineHeight: 1.7 }}>
          调用方式：请求头 <code>Authorization: Bearer {'<key>'}</code>。可调用对话、会话、工作流运行接口，管理类接口不接受 API Key；每次请求消耗 1 次配额，被白名单拒绝或被限速的请求不消耗。
        </div>
      </Modal>
    </div>
  )
}
