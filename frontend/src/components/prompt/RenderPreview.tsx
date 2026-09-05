import { useEffect, useState } from 'react'
import { Alert, Button, Form, Input, Modal, Tag, message } from 'antd'
import { renderPromptTemplate, type PromptRenderResult, type PromptTemplateRow } from '../../api'

// 渲染预览：按模板的变量声明生成输入项，调后端渲染看结果；缺必填由后端 400 提示，不调模型。

interface Props {
  template: PromptTemplateRow | null
  open: boolean
  onClose: () => void
}

export default function RenderPreview({ template, open, onClose }: Props) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [result, setResult] = useState<PromptRenderResult | null>(null)
  const [rendering, setRendering] = useState(false)

  useEffect(() => { if (open) { setValues({}); setResult(null) } }, [open, template?.id])

  const doRender = async () => {
    if (!template) return
    setRendering(true)
    try {
      setResult(await renderPromptTemplate(template.id, values))
    } catch (e: any) { message.error(e.response?.data?.detail || '渲染失败') } finally { setRendering(false) }
  }

  return (
    <Modal title={'渲染预览：' + (template?.name || '')} open={open} onCancel={onClose} onOk={doRender} okText="渲染" confirmLoading={rendering} destroyOnClose>
      <Form layout="vertical">
        {(template?.variables || []).map((v) => (
          <Form.Item key={v.name} label={`${v.name}${v.description ? `（${v.description}）` : ''}`} required={!!v.required && !v.default}>
            <Input value={values[v.name] ?? ''} placeholder={v.default ? '默认：' + v.default : ''} onChange={(e) => setValues({ ...values, [v.name]: e.target.value })} />
          </Form.Item>
        ))}
        {!template?.variables?.length && <Alert type="info" showIcon message="该模板没有变量，直接渲染。" />}
      </Form>
      {result && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>渲染结果：</div>
          <pre style={{ background: '#f8fafc', border: '1px solid #e5e7eb', borderRadius: 6, padding: 12, whiteSpace: 'pre-wrap', margin: 0, fontSize: 13 }}>{result.content}</pre>
          {result.unused.length > 0 && <div style={{ marginTop: 6 }}>声明了但内容未使用：{result.unused.map((n) => <Tag key={n}>{n}</Tag>)}</div>}
          <Button size="small" style={{ marginTop: 8 }} onClick={() => navigator.clipboard?.writeText(result.content)}>复制结果</Button>
        </div>
      )}
    </Modal>
  )
}
