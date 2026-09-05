import { useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, message, Popconfirm, Space, Tag, InputNumber } from 'antd'
import { PlusOutlined, ExperimentOutlined } from '@ant-design/icons'
import { listTools, createTool, updateTool, deleteTool, testTool, type ToolRow, type ToolConfig } from '../api'
import { usePagedList } from '../hooks/usePagedList'
import ToolParamsEditor, { rowsFromSchema, schemaFromRows, type ParamRow } from '../components/tools/ToolParamsEditor'
import ToolTestArgsForm, { collectTestArgs } from '../components/tools/ToolTestArgsForm'

// 工具管理页：内置工具与 HTTP 接口工具的增删改。HTTP 工具的请求细节
// （method/url/headers）以 JSON 形式写在 config 里，参数声明（config.parameters）用表格编辑；
// 测试弹窗按声明生成输入项，实测调用结果。
export default function Tools() {
  const { tableProps, reload } = usePagedList(listTools)
  const [open, setOpen] = useState(false)
  // editing 非空表示当前弹窗处于编辑模式（提交时走 update），否则为新增（走 create）
  const [editing, setEditing] = useState<ToolRow | null>(null)
  // 测试弹窗状态：目标工具 / 按声明生成的输入值（HTTP） / JSON 文本（内置） / 后端返回结果 / 请求中标记
  const [testTarget, setTestTarget] = useState<ToolRow | null>(null)
  const [testValues, setTestValues] = useState<Record<string, unknown>>({})
  const [testJson, setTestJson] = useState('{}')
  const [testResult, setTestResult] = useState<unknown>(null)
  const [testing, setTesting] = useState(false)
  const [form] = Form.useForm()

  // 新增/编辑共用提交：type 为 http 时把表单里的 configStr（JSON 文本）解析成 config，
  // 再把参数表格组装成 config.parameters（表格优先于 JSON 里手写的 parameters）；builtin 类型 config 恒为空对象。
  const onSubmit = async (values: any) => {
    try {
      let config: ToolConfig = {}
      if (values.type === 'http') {
        if (values.configStr) {
          try { config = JSON.parse(values.configStr) } catch { message.error('配置 JSON 格式错误'); return }
        }
        config = { ...config, parameters: schemaFromRows((values.params as ParamRow[]) || []) }
      }
      const payload = { name: values.name, description: values.description, type: values.type, config, timeout: values.timeout }
      if (editing) await updateTool(editing.id, payload)
      else await createTool(payload)
      message.success(editing ? '保存成功' : '创建成功')
      setOpen(false)
      form.resetFields()
      reload()
    } catch (e: any) {
      // 422 是 FastAPI 的逐字段数组，取首条 msg（参数声明不合法时会指出位置）；其余是字符串 detail
      const detail = e.response?.data?.detail
      message.error(Array.isArray(detail) ? detail[0]?.msg : detail || '保存失败')
    }
  }

  const openCreate = () => { setEditing(null); form.resetFields(); setOpen(true) }
  // 编辑：把已存 config 对象序列化回文本域（去掉 parameters，它由表格承载），方便用户直接改 JSON
  const openEdit = (r: ToolRow) => {
    const { parameters, ...rest } = r.config || {}
    setEditing(r)
    form.setFieldsValue({ name: r.name, description: r.description, type: r.type, timeout: r.timeout, configStr: JSON.stringify(rest, null, 2), params: rowsFromSchema(parameters) })
    setOpen(true)
  }

  const openTest = (r: ToolRow) => { setTestTarget(r); setTestValues({}); setTestJson('{}'); setTestResult(null) }

  // 实测工具：HTTP 工具用按声明收集的参数，内置工具用 JSON 文本；交给后端真实执行，结果展示在弹窗里
  const doTest = async () => {
    if (!testTarget) return
    let args: Record<string, unknown> = {}
    if (testTarget.type === 'http') args = collectTestArgs(testValues)
    else {
      try { args = JSON.parse(testJson || '{}') } catch { message.error('参数 JSON 格式错误'); return }
    }
    setTesting(true)
    try {
      const res: any = await testTool(testTarget.id, { args })
      setTestResult(res.data?.result ?? res)
    } catch (e: any) { message.error(e.response?.data?.detail || '测试失败') } finally { setTesting(false) }
  }

  const paramCount = (r: ToolRow) => Object.keys(r.config?.parameters?.properties || {}).length

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '名称', dataIndex: 'name' },
    {
      title: '类型', dataIndex: 'type', render: (v: string, r: ToolRow) => (
        <Space size={4}>
          <Tag color={v === 'builtin' ? 'blue' : 'green'}>{v === 'builtin' ? '内置' : 'HTTP'}</Tag>
          {/* 未声明参数的 HTTP 工具模型只能以空参数调用，提醒补声明 */}
          {v === 'http' && (paramCount(r) ? <Tag>{paramCount(r)} 个参数</Tag> : <Tag color="orange">未声明参数</Tag>)}
        </Space>
      ),
    },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    { title: '超时(s)', dataIndex: 'timeout', width: 90 },
    {
      title: '操作', render: (_: unknown, r: ToolRow) => (
        <Space>
          <Button size="small" icon={<ExperimentOutlined />} onClick={() => openTest(r)}>测试</Button>
          <Button size="small" onClick={() => openEdit(r)}>编辑</Button>
          <Popconfirm title="确定删除？" onConfirm={async () => { try { await deleteTool(r.id); reload() } catch (e: any) { message.error(e.response?.data?.detail || '删除失败') } }}><Button size="small" danger>删除</Button></Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
        <h2>工具管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增工具</Button>
      </div>
      <div className="fixed-table-wrapper">
        <Table rowKey="id" {...tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      </div>

      <Modal title={editing ? '编辑工具' : '新增工具'} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnHidden width={760}>
        <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ type: 'builtin', timeout: 30, params: [] }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述" rules={[{ required: true }]}><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="type" label="类型"><Select options={[{ value: 'builtin', label: '内置' }, { value: 'http', label: 'HTTP 接口' }]} /></Form.Item>
          {/* 仅 HTTP 类型显示配置项与参数声明；切换类型时联动显隐 */}
          <Form.Item noStyle shouldUpdate={(a, b) => a.type !== b.type}>
            {({ getFieldValue }) => getFieldValue('type') === 'http' && (
              <>
                <Form.Item name="configStr" label="HTTP 配置(JSON)">
                  <Input.TextArea rows={4} placeholder='{"method":"POST","url":"https://...","headers":{}}' />
                </Form.Item>
                <Form.Item name="params" label="参数声明（模型按此以结构化参数调用）">
                  <ToolParamsEditor />
                </Form.Item>
              </>
            )}
          </Form.Item>
          <Form.Item name="timeout" label="超时(秒)"><InputNumber min={1} max={300} /></Form.Item>
        </Form>
      </Modal>

      <Modal title={'测试工具：' + (testTarget?.name || '')} open={!!testTarget} onCancel={() => setTestTarget(null)} onOk={doTest} okText="测试" confirmLoading={testing} destroyOnHidden>
        {testTarget && (
          <Form layout="vertical">
            <ToolTestArgsForm tool={testTarget} values={testValues} onChange={setTestValues} jsonText={testJson} onJsonChange={setTestJson} />
          </Form>
        )}
        {testResult !== null && (
          <div style={{ background: '#f8fafc', border: '1px solid #e5e7eb', borderRadius: 6, padding: 12, marginTop: 8, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            <div style={{ fontWeight: 600, marginBottom: 4, fontSize: 13 }}>返回结果：</div>
            <div style={{ fontSize: 13, color: '#334155' }}>{JSON.stringify(testResult, null, 2)}</div>
          </div>
        )}
      </Modal>
    </div>
  )
}
