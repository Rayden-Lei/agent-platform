import { Collapse, Form, InputNumber, Slider, Typography } from 'antd'

// 智能体模型参数：temperature / top_p / max_tokens 落在 agents.params 里（透传给模型调用）。
// 折叠在"高级参数"里，默认不填即用模型默认值。
export default function AgentParamsFields() {
  return (
    <Collapse
      size="small"
      ghost
      items={[{
        key: 'params',
        label: '高级参数（留空用模型默认值）',
        children: (
          <>
            <Form.Item name={['params', 'temperature']} label="temperature" extra="越高越发散；0 最稳定">
              <Slider min={0} max={2} step={0.1} marks={{ 0: '0', 1: '1', 2: '2' }} />
            </Form.Item>
            <Form.Item name={['params', 'top_p']} label="top_p">
              <Slider min={0} max={1} step={0.05} marks={{ 0: '0', 0.5: '0.5', 1: '1' }} />
            </Form.Item>
            <Form.Item name={['params', 'max_tokens']} label="max_tokens" extra="单次回答的最大 token 数">
              <InputNumber min={1} max={128000} style={{ width: 200 }} />
            </Form.Item>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>参数随对话请求透传给模型；不同厂商支持的取值范围不同。</Typography.Text>
          </>
        ),
      }]}
    />
  )
}
