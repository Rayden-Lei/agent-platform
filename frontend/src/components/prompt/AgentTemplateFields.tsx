import { useState } from 'react'
import { Alert, Button, Form, Input, Select, Switch, Typography, message } from 'antd'
import type { FormInstance } from 'antd'
import type { PromptRenderResult, PromptTemplateRow } from '../../api'
import { errorText } from '../../utils/errors'

// 智能体装配页的提示词区块（FR-028）："从模板生成"开关：开启后选模板、按声明填变量、只读展示渲染结果，
// system_prompt 不再手填（提交时传空串由后端渲染）；关闭后恢复手填。渲染预览的请求由页面注入（组件不发请求）。

interface Props {
  form: FormInstance
  templates: PromptTemplateRow[]
  onRender: (templateId: number, variables: Record<string, string>) => Promise<PromptRenderResult>
}

export default function AgentTemplateFields({ form, templates, onRender }: Props) {
  const useTemplate = Form.useWatch('use_template', form)
  const templateId = Form.useWatch('prompt_template_id', form)
  const [preview, setPreview] = useState<PromptRenderResult | null>(null)
  const selected = templates.find((t) => t.id === templateId)

  const doPreview = async () => {
    if (!templateId) return
    try { setPreview(await onRender(templateId, form.getFieldValue('prompt_variables') || {})) } catch (e) { message.error(errorText(e, '渲染失败')) }
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
              onChange={() => { form.setFieldValue('prompt_variables', {}); setPreview(null) }} />
          </Form.Item>
          {(selected?.variables || []).map((v) => (
            <Form.Item key={v.name} name={['prompt_variables', v.name]} label={`${v.name}${v.description ? `（${v.description}）` : ''}`}
              rules={v.required && !v.default ? [{ required: true, message: '必填变量' }] : undefined}>
              <Input placeholder={v.default ? '默认：' + v.default : ''} />
            </Form.Item>
          ))}
          <Button size="small" onClick={doPreview} disabled={!templateId}>预览渲染结果</Button>
          {preview && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 8 }}>
              {/* 缺必填变量时接口直接 400，不会走到这里；unused 是模板本身的问题，填了也不起作用 */}
              {preview.unused.length > 0 && <Alert type="warning" showIcon message={`模板声明了这些变量，但内容里没有引用，填了也不起作用：${preview.unused.join('、')}`} />}
              <Input.TextArea value={preview.content} readOnly autoSize={{ minRows: 4, maxRows: 16 }} />
            </div>
          )}
          <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8 }}>保存草稿时按模板当前版本渲染进系统提示词；模板改版后不会自动更新，需重新保存草稿并发布。</Typography.Paragraph>
        </>
      ) : (
        <Form.Item name="system_prompt" label="系统提示词" rules={[{ required: true }]}>
          <Input.TextArea autoSize={{ minRows: 8, maxRows: 24 }} maxLength={20000} showCount />
        </Form.Item>
      )}
    </>
  )
}
