# -*- coding: utf-8 -*-
from docx import Document
from docx.shared import Pt
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT

doc = Document()
n = doc.styles['Normal']
n.font.name = 'Calibri'; n.font.size = Pt(10.5)
n._element.rPr.rFonts.set(qn('w:eastAsia'), '宋体')

def cn(r, f='宋体', s=10.5, b=False):
    r.font.name = f; r._element.rPr.rFonts.set(qn('w:eastAsia'), f)
    r.font.size = Pt(s); r.font.bold = b

def title(t):
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cn(p.add_run(t), '黑体', 22, True)
def sub(t):
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cn(p.add_run(t), '宋体', 11)
def h1(t):
    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(14); p.paragraph_format.space_after = Pt(6)
    cn(p.add_run(t), '黑体', 16, True)
def h2(t):
    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(10)
    cn(p.add_run(t), '黑体', 13.5, True)
def h3(t):
    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(6)
    cn(p.add_run(t), '黑体', 11.5, True)
def body(t):
    p = doc.add_paragraph(); cn(p.add_run(t), '宋体', 10.5)
def table(headers, rows, fs=9.5):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = 'Table Grid'; t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        cn(t.rows[0].cells[i].paragraphs[0].add_run(h), '黑体', fs, True)
    for row in rows:
        c = t.add_row().cells
        for i, v in enumerate(row):
            cn(c[i].paragraphs[0].add_run(str(v)), '宋体', fs)
    return t

# ================= 封面 =================
title('智能体中台 开发设计文档')
sub('完整版 V2.0')
sub('第一部分 软件需求规格说明书 (SRS)')
sub('第二部分 架构设计说明书 (ADD)')
sub('第三部分 数据库设计说明书 (DBD)')
sub('第四部分 接口设计说明书 (API)')
doc.add_paragraph()

# ================= 第一部分 =================
h1('第一部分 软件需求规格说明书 (SRS)')

h2('一、引言')
body('1.1 目的：详细定义智能体中台的功能与非功能需求，明确字段级定义、业务规则、交互流程与异常处理，作为设计、开发、测试、验收的依据。')
body('1.2 背景：公司内部大模型智能体分散开发、重复建设、缺乏统一管理，需建设私有化中台统一管理模型、智能体、工具、知识库、工作流。')
body('1.3 术语：')
table(['术语','说明'], [['智能体 Agent','基于大模型、可调用工具/知识库/工作流完成任务的程序单元'],['RAG','检索增强生成'],['工作流','节点与连线组成的 DAG 编排'],['SSE','服务端单向推送的流式协议'],['Token','模型计费与上下文计量单位'],['Embedding','文本向量化，用于语义检索']])

h2('二、总体描述')
body('2.1 定位：私有化智能体中台，覆盖智能体配置、运行、编排、监控全生命周期，服务内部技术/算法团队。')
body('2.2 用户：技术/算法团队为主。')
body('2.3 环境：单机 Docker Compose，PostgreSQL+pgvector、Redis、MinIO；浏览器 Chrome/Edge。')
body('2.4 假设：PG/Redis/MinIO 现成；并发几十级；模型为外部 API。')

h2('三、用户角色与权限矩阵')
table(['功能','管理员','开发者','调用者'], [['登录/登出','是','是','是'],['用户管理','是','否','否'],['模型管理','是','只读','否'],['智能体管理','是','是','否'],['对话调用','是','是','是'],['知识库管理','是','是','否'],['工具管理','是','是','否'],['工作流编排/运行','是','是','否'],['运行监控','是','是','否']])

h2('四、功能性需求（字段级详细定义）')

# ---- 4.1 ----
h3('4.1 认证与权限管理')
body('功能点：登录、登出、Token 刷新、用户管理（管理员）、角色权限控制、账号启用停用。')
table(['字段','类型','必填','默认值','校验/说明'], [['username','varchar(64)','是','-','唯一，3-32 字符'],['password','varchar(255)','是','-','bcrypt 哈希，长度≥8'],['role','varchar(16)','是','caller','admin/developer/caller'],['is_active','boolean','是','true','停用后禁止登录']])
body('流程：输入账号密码 -> 后端校验 -> 签发 JWT(24h) -> 前端跳转首页 -> 后续请求携带 Bearer Token。')
body('异常：密码错误提示并计数，连续 5 次锁定 10 分钟；Token 过期返回 401；账号停用返回 403。')

h3('4.2 模型管理')
body('功能点：模型增删改查、连通性测试、启用停用。')
table(['字段','类型','必填','默认值','校验/说明'], [['name','varchar(128)','是','-','展示名'],['provider','varchar(32)','是','-','openai/anthropic/deepseek/qwen'],['api_base','varchar(255)','是','-','模型服务端点'],['api_key','text','是','-','AES 加密存储，返回脱敏'],['model_name','varchar(128)','是','-','实际调用标识'],['default_params','jsonb','否','{}','temperature/top_p/max_tokens'],['is_enabled','boolean','是','true','停用后不可被选']])
body('流程：新增填写配置 -> 保存 -> 测试连接（发起最小请求）-> 通过后启用 -> 智能体可选。')
body('异常：密钥/地址错误测试返回明确错误；删除被引用模型提示先解除引用。')

h3('4.3 智能体管理')
body('功能点：创建、编辑、版本发布、回滚、停用、调试对话。')
table(['字段','类型','必填','默认值','校验/说明'], [['name','varchar(128)','是','-','名称'],['description','text','否','-','用途说明'],['system_prompt','text','是','-','角色设定'],['model_id','int','是','-','外键 models'],['params','jsonb','否','{}','覆盖模型默认参数'],['kb_ids','jsonb','否','[]','关联知识库 ID 数组'],['tool_ids','jsonb','否','[]','关联工具 ID 数组'],['workflow_id','int','否','null','绑定工作流'],['status','varchar(16)','是','draft','draft/published/disabled'],['version','int','是','1','发布时递增']])
body('流程：新建 -> 填配置 -> 保存草稿 -> 调试对话 -> 发布(生成版本 v1) -> 可回滚历史版本。')
body('异常：发布校验必填项；模型未启用禁发布；停用后禁对话。')

h3('4.4 对话运行时')
body('功能点：SSE 流式输出、多轮记忆、工具调用循环、RAG 增强、引用来源、用量统计。')
body('关键参数：top_k 检索默认 4；工具调用最大循环 8 次；模型超时 120 秒重试 1 次；上下文 token 预算截断。')
body('流程：发送消息 -> 鉴权 -> 加载配置 -> 加载历史 -> 检索知识(top_k) -> 组装提示词 -> 流式调用 -> 工具循环 -> 流式返回 -> 落库。')
body('异常：模型超时重试 1 次；工具异常回填错误结果让模型重答；上下文超长按预算截断。')

h3('4.5 工具管理')
body('功能点：内置工具、HTTP 工具、测试调用、启用停用。')
table(['字段','类型','必填','默认值','校验/说明'], [['name','varchar(128)','是','-','工具名'],['description','text','是','-','供模型理解'],['type','varchar(16)','是','-','builtin/http'],['config','jsonb','是','-','method/url/headers/参数 Schema'],['timeout','int','否','30','秒'],['is_enabled','boolean','是','true','-']])
body('异常：接口超时提示；Schema 非法校验失败；被引用工具删除提示先解除引用。')

h3('4.6 知识库 RAG')
body('功能点：知识库创建、文档上传(PDF/Word/MD/TXT)、异步解析切片向量化、混合检索、引用回填。')
table(['字段','类型','必填','默认值','校验/说明'], [['name','varchar(128)','是','-','知识库名'],['embedding_model','varchar(128)','是','-','向量模型'],['chunk_size','int','是','500','切片字符数'],['chunk_overlap','int','是','50','重叠字符数']])
body('文档字段：name、file_path(MinIO)、file_type、status(上传中/解析中/切片中/就绪/失败)、chunk_count、error。')
body('流程：上传 -> MinIO -> 后台解析 -> 切片 -> 向量化 -> 写 pgvector -> 就绪；检索 = 向量+关键词混合 -> top_k。')
body('异常：解析失败置失败并记录原因；检索无结果按普通对话处理；重名文档提示覆盖/跳过。')

h3('4.7 工作流编排')
body('功能点：拖拽画布、6 类节点、节点配置、运行、节点级日志、运行历史。')
table(['节点类型','说明'], [['开始','定义输入参数'],['结束','定义输出'],['智能体','调用指定智能体'],['工具','调用指定工具'],['条件','表达式判断 true/false 分支'],['循环','遍历数组/条件循环，设最大迭代上限(默认 20)']])
body('流程：拖节点 -> 连线 -> 配置 -> 保存 DAG -> 运行 -> 拓扑排序逐节点执行 -> 节点状态落库 -> 汇总输出。')
body('异常：图有环保存拒绝；表达式非法运行报错；循环超上限强制终止。')

h3('4.8 运行监控')
body('功能点：运行记录、token 用量统计、成本估算、失败记录。')
body('指标：运行类型、状态、token(输入/输出)、首字延迟、总耗时、错误信息；按模型/智能体/时间聚合。')

h2('五、非功能性需求')
table(['编号','类别','详细要求'], [['NFR-001','性能','50 并发；TTFT 平均<3s(不含模型延迟)；普通查询<500ms'],['NFR-002','安全','bcrypt 哈希；密钥 AES 加密；JWT；角色控制；日志脱敏'],['NFR-003','部署','Docker Compose 一键私有化，无外网依赖，数据卷持久化'],['NFR-004','可用性','单机可运行；重启数据不丢；任务状态可恢复'],['NFR-005','可维护性','FastAPI 分层；结构化日志；统一异常'],['NFR-006','可扩展性','模型/工具/节点插件式扩展；库为唯一配置源'],['NFR-007','兼容性','Chrome/Edge；兼容 OpenAI 协议及主流国产模型']])

h2('六、验收标准')
for ac in ['AC-001 登录正常，三角色权限隔离正确。','AC-002 至少配置并测试通过一家国产与一家国外模型。','AC-003 可创建并发布智能体，流式对话、多轮记忆、工具调用正常。','AC-004 可拖拽编排并执行含条件分支与循环的工作流。','AC-005 上传 PDF/Word 后可检索并返回引用来源。','AC-006 Docker Compose 干净环境一键拉起，重启数据不丢。']:
    body(ac)

doc.add_page_break()

# ================= 第二部分 =================
h1('第二部分 架构设计说明书 (ADD)')
h2('一、设计目标与原则')
for x in ['单体优先、内部模块化','插件化扩展(模型/工具/节点)','数据库为唯一配置源','异步解耦(文档解析/向量化/工作流)','安全内建(加密/哈希/JWT)','可观测(运行记录/结构化日志/token 计量)']:
    body('· ' + x)
h2('二、总体架构（分层）')
table(['层次','组成','职责'], [['接入层','React 控制台、REST API、SSE','交互与接口入口'],['应用层','认证/模型/智能体/对话/工具/知识库/工作流/监控 8 模块','业务逻辑'],['能力层','模型网关、RAG 管道、工具执行器、工作流引擎、会话管理器','可复用能力'],['数据层','PostgreSQL(+pgvector)、Redis、MinIO','数据存储'],['基础设施','Docker Compose、Nginx','部署运行']])
h2('三、技术选型')
table(['技术点','选型','备选','理由'], [['后端框架','FastAPI','Flask/Django','异步、OpenAPI、类型校验'],['ORM','SQLAlchemy 2.0+Alembic','SQLModel','成熟、迁移完善'],['数据库','PostgreSQL 16','MySQL','pgvector、JSON 强'],['向量库','pgvector','Chroma/Milvus','复用 PG 少组件'],['缓存','Redis','-','会话缓存+未来队列'],['对象存储','MinIO','本地磁盘','S3 兼容私有化'],['前端','React+TS','Vue','生态大'],['画布','React Flow','自研','成熟 DAG 拖拽'],['任务队列','BackgroundTasks','Celery','MVP 够用'],['流式','SSE','WebSocket','单向流式简单可靠'],['认证','JWT','Session','无状态']])
h2('四、模块详细设计')
body('模型网关：Provider 接口(chat/chat_stream)，逐厂商适配器，工厂按 provider 创建；能力=请求适配、流式转发、超时(120s)、重试(1)、密钥解密、用量回传。')
body('工作流引擎：DAG 解析 -> 拓扑排序 -> 逐节点执行；Node 接口(execute)，6 类节点实现；节点状态机 pending->running->success/failed；循环带最大迭代上限。')
body('RAG 管道：解析器插件化(PDF/Word/MD/TXT)；切片(chunk_size+overlap)；向量化；检索(向量+BM25 混合重排 top_k)；引用回填。')
body('工具执行器：JSON Schema 校验参数；超时控制；结果规整。')
body('会话管理器：会话/消息持久化；上下文组装；token 预算截断。')
h2('五、核心时序流程')
body('5.1 对话：发送消息 -> 鉴权 -> 加载配置 -> 加载历史 -> 检索知识 -> 组装提示词 -> 流式调用 -> 工具循环 -> 流式返回 -> 落库。')
body('5.2 RAG 入库：上传 -> MinIO -> 后台解析 -> 切片 -> 向量化 -> 写 pgvector -> 就绪。')
body('5.3 工作流：触发 -> 建 run -> 解析 DAG -> 拓扑排序 -> 逐节点执行 -> 条件/循环 -> 汇总 -> 标记成功/失败。')
h2('六、接口设计规范')
for x in ['REST+JSON，流式用 SSE','统一响应 {"code":0,"message":"ok","data":{}}','分页 page/page_size 返回 total+items','鉴权 Authorization: Bearer <token>','错误码 401/403/404/422/500/504','前缀 /api/v1']:
    body('· ' + x)
h2('七、安全设计')
for x in ['密码 bcrypt','密钥 AES 加密、主密钥来自环境变量、返回脱敏','JWT 24h+刷新','路由级角色鉴权','日志脱敏(密钥/密码/token)','内网部署 Nginx 可选 HTTPS']:
    body('· ' + x)
h2('八、部署架构')
table(['容器','内容','端口','持久化'], [['api','FastAPI+Uvicorn','8000','无'],['web','React+Nginx','80/443','无'],['postgres','PostgreSQL+pgvector','5432','数据卷'],['redis','Redis','6379','数据卷'],['minio','MinIO','9000','数据卷']])
h2('九、风险与应对')
table(['风险','等级','应对'], [['工作流引擎复杂','高','MVP 6 类节点，循环设上限'],['文档格式多','中','解析器插件化，先支持 4 类'],['模型接口差异','中','网关统一抽象'],['流式并发','中','asyncio'],['token 成本','中','计量/配额/缓存/降级'],['密钥泄露','高','AES+脱敏+权限']])

doc.add_page_break()

# ================= 第三部分 =================
h1('第三部分 数据库设计说明书 (DBD)')
h2('一、设计约定')
for x in ['主键统一 BIGSERIAL；时间统一 timestamptz 默认 now()','外键显式声明，删除策略：配置类 RESTRICT，运行类 CASCADE','JSON 用 jsonb；向量用 vector(维度)','命名：表名复数小写下划线，字段小写下划线','统一 updated_at 自动更新']:
    body('· ' + x)

def dbtable(name, desc, fields, indexes=None):
    h3(name)
    body('说明：' + desc)
    table(['字段','类型','约束/默认','说明'], fields)
    if indexes:
        body('索引：' + '；'.join(indexes))

dbtable('users 用户表','存储系统用户与角色。',
 [('id','BIGSERIAL','PK','主键'),('username','varchar(64)','UNIQUE NOT NULL','用户名'),('password_hash','varchar(255)','NOT NULL','bcrypt 哈希'),('role','varchar(16)','NOT NULL DEFAULT caller','admin/developer/caller'),('is_active','boolean','NOT NULL DEFAULT true','是否启用'),('created_at','timestamptz','NOT NULL DEFAULT now()','创建时间'),('updated_at','timestamptz','NOT NULL DEFAULT now()','更新时间')],
 ['UNIQUE(username)'])

dbtable('models 模型配置表','统一管理可接入的大模型。',
 [('id','BIGSERIAL','PK','主键'),('name','varchar(128)','NOT NULL','展示名'),('provider','varchar(32)','NOT NULL','openai/anthropic/deepseek/qwen'),('api_base','varchar(255)','NOT NULL','API 地址'),('api_key_enc','text','NOT NULL','AES 加密密钥'),('model_name','varchar(128)','NOT NULL','实际模型名'),('default_params','jsonb','DEFAULT {}','默认参数'),('is_enabled','boolean','DEFAULT true','启用'),('created_by','int','FK users','创建人'),('created_at','timestamptz','DEFAULT now()','创建时间'),('updated_at','timestamptz','DEFAULT now()','更新时间')],
 ['idx(models.provider)'])

dbtable('agents 智能体表','平台核心资源，配置全部落库。',
 [('id','BIGSERIAL','PK','主键'),('name','varchar(128)','NOT NULL','名称'),('description','text','NULL','说明'),('system_prompt','text','NOT NULL','系统提示词'),('model_id','int','FK models','关联模型'),('params','jsonb','DEFAULT {}','参数覆盖'),('kb_ids','jsonb','DEFAULT []','知识库 ID 数组'),('tool_ids','jsonb','DEFAULT []','工具 ID 数组'),('workflow_id','int','FK workflows NULL','绑定工作流'),('status','varchar(16)','DEFAULT draft','draft/published/disabled'),('version','int','DEFAULT 1','版本号'),('created_by','int','FK users','创建人'),('created_at','timestamptz','DEFAULT now()','创建时间'),('updated_at','timestamptz','DEFAULT now()','更新时间')],
 ['idx(status)','GIN(kb_ids)','GIN(tool_ids)'])

dbtable('tools 工具表','内置与 HTTP 工具定义。',
 [('id','BIGSERIAL','PK','主键'),('name','varchar(128)','NOT NULL','名称'),('description','text','NOT NULL','说明'),('type','varchar(16)','NOT NULL','builtin/http'),('config','jsonb','NOT NULL','method/url/headers/schema'),('timeout','int','DEFAULT 30','超时秒'),('is_enabled','boolean','DEFAULT true','启用'),('created_at','timestamptz','DEFAULT now()','创建时间')])

dbtable('knowledge_bases 知识库表','知识库基础配置。',
 [('id','BIGSERIAL','PK','主键'),('name','varchar(128)','NOT NULL','名称'),('description','text','NULL','说明'),('embedding_model','varchar(128)','NOT NULL','向量模型'),('chunk_size','int','DEFAULT 500','切片字符数'),('chunk_overlap','int','DEFAULT 50','重叠字符数'),('created_by','int','FK users','创建人'),('created_at','timestamptz','DEFAULT now()','创建时间')])

dbtable('documents 文档表','知识库内的文档。',
 [('id','BIGSERIAL','PK','主键'),('kb_id','int','FK knowledge_bases','所属知识库'),('name','varchar(255)','NOT NULL','文档名'),('file_path','varchar(512)','NOT NULL','MinIO 对象键'),('file_type','varchar(16)','NOT NULL','pdf/docx/md/txt'),('status','varchar(16)','DEFAULT uploading','uploading/parsing/chunking/ready/failed'),('chunk_count','int','DEFAULT 0','切片数'),('error','text','NULL','失败原因'),('created_at','timestamptz','DEFAULT now()','创建时间')],
 ['idx(kb_id,status)'])

dbtable('document_chunks 切片表','文档切片与向量。',
 [('id','BIGSERIAL','PK','主键'),('doc_id','int','FK documents','所属文档'),('kb_id','int','FK knowledge_bases','冗余便于过滤'),('content','text','NOT NULL','切片文本'),('embedding','vector(1536)','NOT NULL','向量'),('meta','jsonb','DEFAULT {}','页码/标题等'),('token_count','int','DEFAULT 0','token 数'),('created_at','timestamptz','DEFAULT now()','创建时间')],
 ['HNSW 向量索引(embedding)','idx(kb_id)','idx(doc_id)'])

dbtable('workflows 工作流表','工作流 DAG 定义。',
 [('id','BIGSERIAL','PK','主键'),('name','varchar(128)','NOT NULL','名称'),('description','text','NULL','说明'),('graph','jsonb','NOT NULL','节点+边完整定义'),('version','int','DEFAULT 1','版本'),('status','varchar(16)','DEFAULT draft','draft/published'),('created_by','int','FK users','创建人'),('created_at','timestamptz','DEFAULT now()','创建时间'),('updated_at','timestamptz','DEFAULT now()','更新时间')])

dbtable('workflow_nodes 节点表','工作流节点明细（便于查询）。',
 [('id','BIGSERIAL','PK','主键'),('workflow_id','int','FK workflows','所属工作流'),('node_id','varchar(64)','NOT NULL','节点标识'),('node_type','varchar(16)','NOT NULL','start/end/agent/tool/condition/loop'),('config','jsonb','DEFAULT {}','节点配置'),('pos_x','float','DEFAULT 0','画布坐标 x'),('pos_y','float','DEFAULT 0','画布坐标 y')],
 ['idx(workflow_id)'])

dbtable('conversations 会话表','一次连续对话容器。',
 [('id','BIGSERIAL','PK','主键'),('agent_id','int','FK agents NULL','智能体'),('workflow_id','int','FK workflows NULL','工作流'),('user_id','int','FK users','用户'),('title','varchar(255)','NULL','标题'),('created_at','timestamptz','DEFAULT now()','创建时间'),('updated_at','timestamptz','DEFAULT now()','更新时间')],
 ['idx(user_id)'])

dbtable('messages 消息表','对话消息明细。',
 [('id','BIGSERIAL','PK','主键'),('conversation_id','int','FK conversations','所属会话'),('role','varchar(16)','NOT NULL','user/assistant/tool'),('content','text','NOT NULL','内容'),('tool_calls','jsonb','DEFAULT []','工具调用'),('citations','jsonb','DEFAULT []','引用来源'),('token_usage','jsonb','DEFAULT {}','token 用量'),('created_at','timestamptz','DEFAULT now()','创建时间')],
 ['idx(conversation_id,created_at)'])

dbtable('runs 运行记录表','对话/工作流运行记录。',
 [('id','BIGSERIAL','PK','主键'),('run_type','varchar(16)','NOT NULL','chat/workflow'),('agent_id','int','FK agents NULL','智能体'),('workflow_id','int','FK workflows NULL','工作流'),('user_id','int','FK users','用户'),('status','varchar(16)','DEFAULT running','running/success/failed'),('input','jsonb','DEFAULT {}','输入'),('output','jsonb','DEFAULT {}','输出'),('error','text','NULL','错误'),('token_usage','jsonb','DEFAULT {}','用量'),('latency_ms','int','DEFAULT 0','耗时'),('started_at','timestamptz','NULL','开始'),('finished_at','timestamptz','NULL','结束')],
 ['idx(user_id,created_at)','idx(run_type,status)'])

dbtable('run_nodes 节点运行表','工作流节点级运行日志。',
 [('id','BIGSERIAL','PK','主键'),('run_id','int','FK runs','所属运行'),('node_id','varchar(64)','NOT NULL','节点'),('node_type','varchar(16)','NOT NULL','类型'),('status','varchar(16)','DEFAULT pending','pending/running/success/failed'),('input','jsonb','DEFAULT {}','输入'),('output','jsonb','DEFAULT {}','输出'),('error','text','NULL','错误'),('started_at','timestamptz','NULL','开始'),('finished_at','timestamptz','NULL','结束')],
 ['idx(run_id)'])

h2('二、实体关系（ER）说明')
body('users 1-N agents/tools/knowledge_bases/workflows/conversations/runs；models 1-N agents；knowledge_bases 1-N documents 1-N document_chunks；workflows 1-N workflow_nodes；conversations 1-N messages；runs 1-N run_nodes；agents 与 tools/knowledge_bases 通过 jsonb 数组弱关联（多对多，用 GIN 索引）。')

doc.add_page_break()

# ================= 第四部分 =================
h1('第四部分 接口设计说明书 (API)')
h2('一、通用约定')
for x in ['Base URL: /api/v1','统一响应 {"code":0,"message":"ok","data":{}}','鉴权 Bearer JWT（登录/刷新除外）','分页 page(默认1)/page_size(默认20)','流式接口 Content-Type: text/event-stream']:
    body('· ' + x)

def api(method, path, perm, desc, req, resp):
    h3(method + ' ' + path)
    body('权限：' + perm + '｜说明：' + desc)
    body('请求：' + req)
    body('响应：' + resp)

h2('二、认证模块')
api('POST','/auth/login','公开','登录','{username, password}','{code,message,data:{token,user}}')
api('POST','/auth/refresh','登录','刷新 Token','{token}','{token}')
api('POST','/auth/logout','登录','登出','-','{code,message}')
api('GET','/auth/me','登录','当前用户','-','{user}')

h2('三、用户管理（管理员）')
api('GET','/users','管理员','用户列表','?page&page_size','{total,items:[user]}')
api('POST','/users','管理员','新增用户','{username,password,role}','{user}')
api('PUT','/users/{id}','管理员','修改用户','{role,is_active}','{user}')
api('DELETE','/users/{id}','管理员','删除用户','-','{code,message}')

h2('四、模型管理')
api('GET','/models','管理员/开发者','模型列表','?page&page_size','{total,items:[model]}')
api('POST','/models','管理员','新增模型','{name,provider,api_base,api_key,model_name,default_params}','{model}')
api('GET','/models/{id}','管理员/开发者','模型详情','-','{model}')
api('PUT','/models/{id}','管理员','修改模型','同新增','{model}')
api('DELETE','/models/{id}','管理员','删除模型','-','{code,message}')
api('POST','/models/{id}/test','管理员','连通测试','{message?}','{ok,latency_ms,error?}')

h2('五、智能体管理')
api('GET','/agents','管理员/开发者','智能体列表','?page&page_size&status','{total,items:[agent]}')
api('POST','/agents','管理员/开发者','创建','{name,description,system_prompt,model_id,params,kb_ids,tool_ids,workflow_id}','{agent}')
api('GET','/agents/{id}','管理员/开发者','详情','-','{agent}')
api('PUT','/agents/{id}','管理员/开发者','修改','同创建','{agent}')
api('DELETE','/agents/{id}','管理员/开发者','删除','-','{code,message}')
api('POST','/agents/{id}/publish','管理员/开发者','发布','-','{agent(version+1,status=published)}')

h2('六、对话运行时')
api('POST','/agents/{id}/chat','登录','对话(SSE 流式)','{conversation_id?,message}','SSE: 增量文本/工具调用/引用/完成事件')
api('GET','/conversations','登录','会话列表','?page&page_size','{total,items}')
api('GET','/conversations/{id}','登录','会话详情','-','{conversation}')
api('GET','/conversations/{id}/messages','登录','历史消息','?page&page_size','{total,items:[message]}')
api('DELETE','/conversations/{id}','登录','删除会话','-','{code,message}')

h2('七、工具管理')
api('GET','/tools','管理员/开发者','工具列表','?page&page_size','{total,items}')
api('POST','/tools','管理员/开发者','新增','{name,description,type,config,timeout}','{tool}')
api('PUT','/tools/{id}','管理员/开发者','修改','同新增','{tool}')
api('DELETE','/tools/{id}','管理员/开发者','删除','-','{code,message}')
api('POST','/tools/{id}/test','管理员/开发者','测试','{args}','{ok,result,error?}')

h2('八、知识库')
api('GET','/knowledge-bases','管理员/开发者','知识库列表','?page&page_size','{total,items}')
api('POST','/knowledge-bases','管理员/开发者','创建','{name,description,embedding_model,chunk_size,chunk_overlap}','{kb}')
api('GET','/knowledge-bases/{id}','管理员/开发者','详情','-','{kb}')
api('DELETE','/knowledge-bases/{id}','管理员/开发者','删除','-','{code,message}')
api('POST','/knowledge-bases/{id}/documents','管理员/开发者','上传文档(multipart)','file','{document}')
api('GET','/knowledge-bases/{id}/documents','管理员/开发者','文档列表','?page&page_size','{total,items}')
api('DELETE','/knowledge-bases/{id}/documents/{doc_id}','管理员/开发者','删除文档','-','{code,message}')
api('POST','/knowledge-bases/{id}/search','管理员/开发者','检索测试','{query,top_k}','{items:[{content,score,doc_name,meta}]}')

h2('九、工作流')
api('GET','/workflows','管理员/开发者','列表','?page&page_size','{total,items}')
api('POST','/workflows','管理员/开发者','创建','{name,description,graph}','{workflow}')
api('GET','/workflows/{id}','管理员/开发者','详情','-','{workflow}')
api('PUT','/workflows/{id}','管理员/开发者','修改','同创建','{workflow}')
api('DELETE','/workflows/{id}','管理员/开发者','删除','-','{code,message}')
api('POST','/workflows/{id}/run','管理员/开发者','执行','{input}','{run}')
api('GET','/workflows/{id}/runs','管理员/开发者','运行历史','?page&page_size','{total,items:[run]}')

h2('十、运行记录')
api('GET','/runs','管理员/开发者','运行记录','?run_type&status&page&page_size','{total,items:[run]}')
api('GET','/runs/{id}','管理员/开发者','运行详情(含节点日志)','-','{run,nodes:[run_node]}')

doc.save('docs/agent-platform-design.docx')
print('SAVED OK')
