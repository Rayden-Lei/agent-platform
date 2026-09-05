import { useState } from 'react'
import { Button, Form, Input, Select, Switch, Typography, message } from 'antd'
import type { FormInstance } from 'antd'
import { renderPromptTemplate, type PromptTemplateRow } from '../../api'

// 智能体表单的提示词区块（FR-028）："从模板生成"开关：开启后选模板、按声明填变量、只读展示渲染结果，
// system_prompt 不再手填（提交时传空串由后端渲染）；关闭后恢复手填。

interface Props {
  form: FormInstance
  templates: PromptTemplateRow[]
}

export default function AgentTemplateFields({ form, templates }: Props) {
  const useTemplate = Form.useWatch('use_template', form)
  const templateId = Form.useWatch('prompt_template_id', form)
  const [preview, setPreview] = useState('')
  const selected = templates.find((t) => t.id === templateId)

  const doPreview = async () => {
    if (!templateId) return
    try {
      const r = await renderPromptTemplate(templateId, form.getFieldValue('prompt_variables') || {})
      setPreview(r.content)
    } catch (e: any) { message.error(e.response?.data?.detail || '渲染失败') }
  }

  return (
    <>
      <Form.Item name="use_template" label="提示词来源" valuePropName="checked">
        <Switch checkedChildren="从模板生成" unCheckedChildren="手填" />
      </Form.Item>
      {useTemplate ? (
        <>
          <Form.Item name="prompt_template_id" label="模板" rules={[{ required: true, message: '请选择模板' }]}>
            <Select showSearch optionFilterProp="label" placeholder="选择提示词模板" options={templates.map((t) => ({ value: t.id, label: `${t.name}（v${t.version}）` }))}
              onChange={() => { form.setFieldValue('prompt_variables', {}); setPreview('') }} />
          </Form.Item>
          {(selected?.variables || []).map((v) => (
            <Form.Item key={v.name} name={['prompt_variables', v.name]} label={`${v.name}${v.description ? `（${v.description}）` : ''}`}
              rules={v.required && !v.default ? [{ required: true, message: '必填变量' }] : undefined}>
              <Input placeholder={v.default ? '默认：' + v.default : ''} />
            </Form.Item>
          ))}
          <Button size="small" onClick={doPreview} disabled={!templateId}>预览渲染结果</Button>
          {preview && <Input.TextArea value={preview} readOnly rows={4} style={{ marginTop: 8 }} />}
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8 }}>保存时按模板当前版本渲染进系统提示词；模板改版后不会自动更新，需重新保存。</Typography.Paragraph>
        </>
      ) : (
        <Form.Item name="system_prompt" label="系统提示词" rules={[{ required: true }]}><Input.TextArea rows={4} /></Form.Item>
      )}
    </>
  )
}
