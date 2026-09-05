import { useEffect, useState } from 'react'
import { Divider, Form, Input, InputNumber, Modal, Select, Switch, Typography, message } from 'antd'
import { createKB, updateKB, type KnowledgeBaseInput, type KnowledgeBaseRow } from '../../api'
import { statusOptions } from '../../constants/status'
import { errorText } from '../../utils/errors'

// 知识库新建 / 编辑弹窗：名称、描述、向量模型（建库后不可改）、切片参数（只影响之后上传的文档）、访问权限。
interface Props {
  open: boolean
  editing: KnowledgeBaseRow | null
  onClose: () => void
  onSaved: (kb: KnowledgeBaseRow) => void
}

export default function KbForm({ open, editing, onClose, onSaved }: Props) {
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => {
    if (!open) return
    form.resetFields()
    if (editing) form.setFieldsValue({ ...editing, visible_roles: editing.visible_roles || [] })
  }, [open, editing, form])

  const onSubmit = async (values: KnowledgeBaseInput) => {
    setSubmitting(true)
    try {
      const saved = editing ? await updateKB(editing.id, values) : await createKB(values)
      message.success(editing ? '已保存' : '创建成功')
      onSaved(saved)
      onClose()
    } catch (e) { message.error(errorText(e, '保存失败')) } finally { setSubmitting(false) }
  }

  return (
    <Modal title={editing ? `编辑知识库：${editing.name}` : '新建知识库'} open={open} onCancel={onClose} onOk={() => form.submit()} confirmLoading={submitting} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ chunk_size: 500, chunk_overlap: 50, embedding_model: 'text-embedding-3-small', is_public: true, visible_roles: [] }}>
        <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="description" label="描述"><Input /></Form.Item>
        <Form.Item name="embedding_model" label="向量模型" extra={editing ? '建库后不可更改；实际使用的向量后端以系统状态为准' : '记录用，实际向量后端由服务端 EMBEDDING_* 配置决定'}>
          <Input disabled={!!editing} />
        </Form.Item>
        <div style={{ display: 'flex', gap: 12 }}>
          <Form.Item name="chunk_size" label="切片大小（字符）" style={{ flex: 1 }}><InputNumber min={50} max={5000} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="chunk_overlap" label="切片重叠" style={{ flex: 1 }}><InputNumber min={0} max={1000} style={{ width: '100%' }} /></Form.Item>
        </div>
        {editing && <Typography.Text type="secondary" style={{ fontSize: 12 }}>切片参数只影响之后上传的文档；已有文档可在详情页"重新解析"按新参数重建。</Typography.Text>}
        <Divider style={{ margin: '12px 0' }}>访问权限</Divider>
        <Form.Item name="is_public" label="公开（所有角色可见）" valuePropName="checked"><Switch /></Form.Item>
        <Form.Item noStyle shouldUpdate={(prev, cur) => prev.is_public !== cur.is_public}>
          {({ getFieldValue }) => !getFieldValue('is_public') && (
            <Form.Item name="visible_roles" label="可见角色（非公开时生效）" extra="检索与对话引用都按此过滤；改权限后已入库切片的标签不回写，需重新解析">
              <Select mode="multiple" placeholder="选择可访问的角色" options={statusOptions('role')} />
            </Form.Item>
          )}
        </Form.Item>
      </Form>
    </Modal>
  )
}
