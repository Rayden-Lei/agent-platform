import { Copy } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/shadcn/alert'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/shadcn/tabs'
import type { WorkflowParameters } from '../../api'
import { copyText } from '../../utils/clipboard'
import Button from '../ui/Button'
import { CodeText, Disclosure, DocTable, Snippet } from '../publish/apiDocParts'
import { KEY_PLACEHOLDER } from '../publish/apiSnippets'
import { ERROR_ROWS, asyncSnippet, blockingSnippet, cancelSnippet, endpointRows, markdownDoc, resumeSnippet, variableRows, type WorkflowApiTarget } from './workflowApiSnippets'

// 工作流详情"API 访问"页签（docs/15 WF-06，FR-046）：与智能体发布渠道的 ApiAccessPanel（PB-02）同一套结构，
// 只是把资源换成工作流、示例换成 同步 / 异步 + 轮询 / 取消 / 续跑 四段。
// 数据由页面传入（工作流 + 线上版本的参数声明），本组件不发请求。
interface Props {
  workflow: WorkflowApiTarget
  baseUrl: string            // 对外地址（PUBLIC_BASE_URL，未配置时是当前访问地址）
  baseUrlConfigured: boolean
  parameters: WorkflowParameters | null
  parametersError?: string | null
  onRetryParameters?: () => void
}

export default function WorkflowApiAccessPanel({ workflow, baseUrl, baseUrlConfigured, parameters, parametersError, onRetryParameters }: Props) {
  const api = `${baseUrl}/api/v1`
  // 与"运行"按钮同一口径：没有线上版本就不能被调用（后端 403）
  const published = workflow.published_version !== null
  const variables = parameters?.variables ?? []
  const rows = variableRows(variables)

  return (
    <section className="flex flex-col rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3.5 py-2.5">
        <h3 className="m-0 text-[13px] font-semibold text-foreground">API 调用</h3>
        {published && (
          <Button icon={<Copy className="size-3.5" />} onClick={() => copyText(markdownDoc(api, workflow, variables), '对接说明（Markdown）')}>复制对接说明</Button>
        )}
      </div>

      <div className="flex flex-col gap-3 p-3.5">
        {!published ? (
          <Alert className="border-border-strong">
            <AlertTitle>发布后才能调用：工作流还没有线上版本，现在按示例调用会返回 403「工作流未发布」</AlertTitle>
            <AlertDescription>先在上方点"发布"，把当前草稿上线；接口示例与入参声明都按线上版本生成。</AlertDescription>
          </Alert>
        ) : (
          <>
            <Alert className="border-border-strong">
              <AlertDescription>API Key 只在服务端调用，不要放进浏览器、小程序或 App；Key 只能调用授权给它的工作流，且只能查询、取消、续跑本 Key 发起的运行</AlertDescription>
            </Alert>

            <dl className="m-0 grid grid-cols-1 gap-y-2 rounded-lg border border-border p-3">
              <div className="flex flex-wrap items-center gap-2">
                <dt className="w-[88px] shrink-0 text-[12.5px] text-muted-foreground">Base URL</dt>
                <dd className="m-0 flex min-w-0 flex-wrap items-center gap-2 text-[13px]">
                  <CodeText copy>{api}</CodeText>
                  {!baseUrlConfigured && <span className="text-[12px] text-muted-foreground">（未配置 PUBLIC_BASE_URL，这是你当前访问的地址）</span>}
                </dd>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <dt className="w-[88px] shrink-0 text-[12.5px] text-muted-foreground">工作流 ID</dt>
                <dd className="m-0 min-w-0 text-[13px]"><CodeText copy>{String(workflow.id)}</CodeText></dd>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <dt className="w-[88px] shrink-0 text-[12.5px] text-muted-foreground">鉴权</dt>
                <dd className="m-0 min-w-0 text-[13px]"><CodeText>{`Authorization: Bearer ${KEY_PLACEHOLDER}`}</CodeText></dd>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <dt className="w-[88px] shrink-0 text-[12.5px] text-muted-foreground">线上版本</dt>
                <dd className="m-0 min-w-0 text-[13px]">v{workflow.published_version}</dd>
              </div>
            </dl>

            <Tabs defaultValue="blocking">
              <TabsList>
                <TabsTrigger value="blocking">同步运行</TabsTrigger>
                <TabsTrigger value="async">异步 + 轮询</TabsTrigger>
                <TabsTrigger value="cancel">取消</TabsTrigger>
                <TabsTrigger value="resume">人工审核续跑</TabsTrigger>
              </TabsList>
              <TabsContent value="blocking"><Snippet code={blockingSnippet(api, workflow.id, variables)} label=" 同步运行示例" /></TabsContent>
              <TabsContent value="async"><Snippet code={asyncSnippet(api, workflow.id, variables)} label=" 异步运行 + 轮询示例" /></TabsContent>
              <TabsContent value="cancel"><Snippet code={cancelSnippet(api, workflow.id)} label=" 取消示例" /></TabsContent>
              <TabsContent value="resume"><Snippet code={resumeSnippet(api, workflow.id)} label=" 人工审核续跑示例" /></TabsContent>
            </Tabs>

            <div className="flex flex-col gap-2">
              <Disclosure title={`入参（按线上 v${workflow.published_version} 的输入声明生成）`}>
                {parametersError ? (
                  <p className="m-0 px-1 py-1 text-[13px] text-muted-foreground">
                    {parametersError}
                    {onRetryParameters && <Button size="sm" variant="ghost" onClick={onRetryParameters}>重试</Button>}
                  </p>
                ) : !parameters ? (
                  <p className="m-0 px-1 py-1 text-[13px] text-muted-foreground">加载中…</p>
                ) : rows.length === 0 ? (
                  <p className="m-0 px-1 py-1 text-[13px] text-muted-foreground">这个工作流没有声明输入变量，示例里的 inputs 传 {'{}'} 即可</p>
                ) : (
                  <DocTable rows={rows} first="变量" />
                )}
              </Disclosure>
              <Disclosure title="端点"><DocTable rows={endpointRows(workflow.id)} first="端点" /></Disclosure>
              <Disclosure title="错误码"><DocTable rows={ERROR_ROWS} first="状态码" /></Disclosure>
            </div>
          </>
        )}
      </div>
    </section>
  )
}
