import { useState } from 'react'
import { Table, Button, Drawer, Form, Input, message, Popconfirm, Space, Tag } from 'antd'
import { PlusOutlined, HistoryOutlined, EyeOutlined } from '@ant-design/icons'
import { listPromptTemplates, createPromptTemplate, updatePromptTemplate, deletePromptTemplate, getPromptTemplate, type PromptTemplateRow } from '../api'
import { usePagedList } from '../hooks/usePagedList'
import VariablesEditor, { rowsFromVariables, variablesFromRows, type VarRow } from '../components/prompt/VariablesEditor'
import VersionsDrawer from '../components/prompt/VersionsDrawer'
import RenderPreview from '../components/prompt/RenderPreview'

// 提示词模板页（FR-028）：列表 + 编辑抽屉（内容 + 变量表格）+ 版本历史（回滚）+ 渲染预览。
// 内容里用 {{变量名}} 引用变量；引用未声明的变量后端 400，声明了但没用到的在保存后提示。
export default function PromptTemplates() {
  const { tableProps, reload } = usePagedList(listPromptTemplates)
  const [open, setOpen] = useState(false)
  // editing 非空表示编辑模式（走 update），否则新增（走 create）
  const [editing, setEditing] = useState<PromptTemplateRow | null>(null)
  const [versionTarget, setVersionTarget] = useState<PromptTemplateRow | null>(null)
  const [previewTarget, setPreviewTarget] = useState<PromptTemplateRow | null>(null)
  const [form] = Form.useForm()

  const onSubmit = async (values: any) => {
    const payload = { name: values.name, description: values.description || '', content: values.content, variables: variablesFromRows((values.variables as VarRow[]) || []) }
    try {
      const saved = editing ? await updatePromptTemplate(editing.id, payload) : await createPromptTemplate(payload)
      if (saved.unused_variables?.length) message.warning('已保存，但这些变量声明了却没在内容里使用：' + saved.unused_variables.join(', '))
      else message.success(editing ? '保存成功' : '创建成功')
      setOpen(false)
      form.resetFields()
      reload()
    } catch (e: any) {
      // 422 是 FastAPI 的逐字段数组（变量名不合法 / 重复 / 超过 30 个），取首条 msg；400 / 409 是字符串 detail
      const detail = e.response?.data?.detail
      message.error(Array.isArray(detail) ? detail[0]?.msg : detail || '保存失败')
    }
  }

  const openCreate = () => { setEditing(null); form.resetFields(); setOpen(true) }
  // 列表不下发 content，编辑前先取详情
  const openEdit = async (r: PromptTemplateRow) => {
    try {
      const detail = await getPromptTemplate(r.id)
      setEditing(detail)
      form.setFieldsValue({ name: detail.name, description: detail.description || '', content: detail.content, variables: rowsFromVariables(detail.variables) })
      setOpen(true)
    } catch (e: any) { message.error(e.response?.data?.detail || '加载模板失败') }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '名称', dataIndex: 'name' },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    {
      title: '变量', dataIndex: 'variables', render: (vars: PromptTemplateRow['variables']) => (
        vars.length ? <Space size={4} wrap>{vars.map((v) => <Tag key={v.name}>{v.name}{v.required ? ' *' : ''}</Tag>)}</Space> : <span style={{ color: '#9ca3af' }}>无</span>
      ),
    },
    { title: '版本', dataIndex: 'version', width: 70, render: (v: number) => 'v' + v },
    { title: '更新时间', dataIndex: 'updated_at', width: 170, render: (v: string) => new Date(v).toLocaleString() },
    {
      title: '操作', width: 260, render: (_: unknown, r: PromptTemplateRow) => (
        <Space>
          <Button size="small" icon={<EyeOutlined />} onClick={() => setPreviewTarget(r)}>预览</Button>
          <Button size="small" icon={<HistoryOutlined />} onClick={() => setVersionTarget(r)}>版本</Button>
          <Button size="small" onClick={() => openEdit(r)}>编辑</Button>
          {/* 仍被智能体绑定时后端 409，提示里带绑定数 */}
          <Popconfirm title="确定删除？" onConfirm={async () => { try { await deletePromptTemplate(r.id); reload() } catch (e: any) { message.error(e.response?.data?.detail || '删除失败') } }}>
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
        <h2>提示词模板</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增模板</Button>
      </div>
      <div className="fixed-table-wrapper">
        <Table rowKey="id" {...tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      </div>

      <Drawer title={editing ? `编辑模板（当前 v${editing.version}）` : '新增模板'} open={open} onClose={() => setOpen(false)} width={760} destroyOnClose
        extra={<Button type="primary" onClick={() => form.submit()}>保存</Button>}>
        <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ variables: [] }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }, { max: 128 }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input /></Form.Item>
          <Form.Item name="content" label="内容" rules={[{ required: true }]} extra="用 {{变量名}} 引用下方声明的变量；内容或变量变化会自动升版本">
            <Input.TextArea rows={10} placeholder={'你是{{role}}，请用{{tone}}的语气回答。'} />
          </Form.Item>
          <Form.Item name="variables" label="变量声明（最多 30 个）"><VariablesEditor /></Form.Item>
        </Form>
      </Drawer>

      <VersionsDrawer template={versionTarget} open={!!versionTarget} onClose={() => setVersionTarget(null)} onRolledBack={reload} />
      <RenderPreview template={previewTarget} open={!!previewTarget} onClose={() => setPreviewTarget(null)} />
    </div>
  )
}
