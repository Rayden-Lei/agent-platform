import { useState } from 'react'
import { Alert, Button, Form, Input, Space, Tag, Typography, message } from 'antd'
import { renderPromptTemplate, type PromptRenderResult, type PromptTemplateRow } from '../../api'
import { errorText } from '../../utils/errors'

// 渲染预览页签：按变量声明生成输入项，调后端渲染看结果；缺必填由后端 400 提示，不调模型。
interface Props { template: PromptTemplateRow }

export default function TemplateRenderTab({ template }: Props) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [result, setResult] = useState<PromptRenderResult | null>(null)
  const [rendering, setRendering] = useState(false)
  const render = async () => {
    setRendering(true)
    try { setResult(await renderPromptTemplate(template.id, values)) } catch (e) { message.error(errorText(e, '渲染失败')) } finally { setRendering(false) }
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <Form layout="vertical" size="small">
        {template.variables.map((v) => (
          <Form.Item key={v.name} label={`${v.name}${v.description ? `（${v.description}）` : ''}`} required={!!v.required && !v.default} style={{ marginBottom: 8 }}>
            <Input value={values[v.name] ?? ''} placeholder={v.default ? '默认：' + v.default : ''} onChange={(e) => setValues({ ...values, [v.name]: e.target.value })} />
          </Form.Item>
        ))}
        {!template.variables.length && <Alert type="info" showIcon message="该模板没有变量，直接渲染。" style={{ marginBottom: 8 }} />}
      </Form>
      <Space><Button type="primary" size="small" loading={rendering} onClick={render}>渲染</Button>{result && <Button size="small" onClick={() => { navigator.clipboard?.writeText(result.content); message.success('已复制') }}>复制结果</Button>}</Space>
      {result && (
        <div>
          <pre style={{ background: '#f8fafc', border: '1px solid #e5e7eb', borderRadius: 6, padding: 12, whiteSpace: 'pre-wrap', margin: 0, fontSize: 13 }}>{result.content}</pre>
          {result.unused.length > 0 && <Typography.Text type="secondary" style={{ fontSize: 12 }}>声明了但内容未使用：{result.unused.map((n) => <Tag key={n}>{n}</Tag>)}</Typography.Text>}
        </div>
      )}
    </div>
  )
}
