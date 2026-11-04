import type { ModelParams } from '../../api'
import ModelParamsFields from '../models/ModelParamsFields'

// 智能体模型参数：temperature / top_p / max_tokens 存 agents.params，运行时覆盖所选模型的默认参数（FR-042）。
// 留空继承模型默认，占位文字显示继承值（inherited 由表单按所选模型传入）。
// 原先折叠在"高级参数"里；装配页已经是分区卡片，再套一层折叠只会多点一次，这里直接平铺。
export default function AgentParamsFields({ inherited }: { inherited?: ModelParams }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="text-[13.5px] font-medium text-foreground">高级参数（留空继承模型默认）</span>
      <ModelParamsFields inherited={inherited ?? {}} />
      <p className="m-0 text-[12.5px] text-muted-foreground">模型的默认参数在模型页设置；不同厂商支持的取值范围不同。</p>
    </div>
  )
}
