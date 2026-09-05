import { useEffect, useState } from 'react'
import { Form, Modal, message } from 'antd'
import { testTool, type ToolRow } from '../../api'
import JsonView from '../common/JsonView'
import ToolTestArgsForm, { collectTestArgs } from './ToolTestArgsForm'
import { errorText } from '../../utils/errors'

// 工具在线测试：HTTP 工具按参数声明生成输入项，内置工具用 JSON 文本；后端真实执行并返回结果。
interface Props { tool: ToolRow | null; onClose: () => void }

export default function ToolTestModal({ tool, onClose }: Props) {
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [jsonText, setJsonText] = useState('{}')
  const [result, setResult] = useState<unknown>(null)
  const [testing, setTesting] = useState(false)
  const [elapsed, setElapsed] = useState<number | null>(null)
  useEffect(() => { if (tool) { setValues({}); setJsonText('{}'); setResult(null); setElapsed(null) } }, [tool])

  const run = async () => {
    if (!tool) return
    let args: Record<string, unknown> = {}
    if (tool.type === 'http') args = collectTestArgs(values)
    else {
      try { args = JSON.parse(jsonText || '{}') } catch { message.error('参数 JSON 格式错误'); return }
    }
    setTesting(true)
    const started = performance.now()
    try {
      const res = await testTool(tool.id, { args })
      setResult(res.data?.result ?? res)
      setElapsed(Math.round(performance.now() - started))
    } catch (e) { message.error(errorText(e, '测试失败')) } finally { setTesting(false) }
  }

  return (
    <Modal title={tool ? `测试工具：${tool.name}` : ''} open={!!tool} onCancel={onClose} onOk={run} okText="测试" confirmLoading={testing} destroyOnHidden>
      {tool && (
        <Form layout="vertical">
          <ToolTestArgsForm tool={tool} values={values} onChange={setValues} jsonText={jsonText} onJsonChange={setJsonText} />
        </Form>
      )}
      {result !== null && <JsonView title={`返回结果${elapsed !== null ? `（耗时 ${elapsed} ms，含网络）` : ''}`} value={result} maxHeight={280} />}
    </Modal>
  )
}
