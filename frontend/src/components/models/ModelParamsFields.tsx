import { Form, InputNumber } from 'antd'
import type { ModelParams } from '../../api'

// 模型调用参数的三个输入框：模型表单填"默认参数"（name='default_params'），智能体表单填"覆盖参数"（name='params'）。
// 用可清空的数字框而不是滑块：滑块拖过就清不掉，而"留空 = 继承上一层"是这组参数的核心语义。
// inherited 传所选模型的默认参数时，占位文字显示将继承的值。
interface Props {
  name: 'default_params' | 'params'
  inherited?: ModelParams
}

export default function ModelParamsFields({ name, inherited }: Props) {
  const hint = (key: 'temperature' | 'top_p' | 'max_tokens') => {
    const value = inherited?.[key]
    if (value !== undefined && value !== null) return `继承模型默认 ${value}`
    return inherited ? '继承模型默认（未设置）' : '厂商默认'
  }
  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
      <Form.Item name={[name, 'temperature']} label="temperature" tooltip="0～2，越高越发散，0 最稳定" style={{ flex: 1, minWidth: 140 }}>
        <InputNumber min={0} max={2} step={0.1} style={{ width: '100%' }} placeholder={hint('temperature')} />
      </Form.Item>
      <Form.Item name={[name, 'top_p']} label="top_p" tooltip="0～1，核采样阈值；一般只调 temperature 与 top_p 之一" style={{ flex: 1, minWidth: 140 }}>
        <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} placeholder={hint('top_p')} />
      </Form.Item>
      <Form.Item name={[name, 'max_tokens']} label="max_tokens" tooltip="单次回答的最大 token 数，1～128000" style={{ flex: 1, minWidth: 140 }}>
        <InputNumber min={1} max={128000} precision={0} style={{ width: '100%' }} placeholder={hint('max_tokens')} />
      </Form.Item>
    </div>
  )
}
