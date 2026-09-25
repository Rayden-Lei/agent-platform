import { Collapse, Typography } from 'antd'
import type { ModelParams } from '../../api'
import ModelParamsFields from '../models/ModelParamsFields'

// 智能体模型参数：temperature / top_p / max_tokens 存 agents.params，运行时覆盖所选模型的默认参数（FR-042）。
// 折叠在"高级参数"里；留空继承模型默认，占位文字显示继承值（inherited 由表单按所选模型传入）。
export default function AgentParamsFields({ inherited }: { inherited?: ModelParams }) {
  return (
    <Collapse
      size="small"
      ghost
      items={[{
        key: 'params',
        label: '高级参数（留空继承模型默认）',
        children: (
          <>
            <ModelParamsFields name="params" inherited={inherited ?? {}} />
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>模型的默认参数在模型页设置；不同厂商支持的取值范围不同。</Typography.Text>
          </>
        ),
      }]}
    />
  )
}
