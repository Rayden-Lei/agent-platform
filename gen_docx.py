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
    p = doc.add_paragraph(); p.paragraph_format.space_before = Pt(8)
    cn(p.add_run(t), '黑体', 13, True)
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

title('智枢·智能体平台 开发设计文档')
sub('完整版 V2.0')
sub('需求规格 / 架构设计 / 数据库设计 / 接口设计')
doc.add_paragraph()

h1('第一部分 软件需求规格说明书 (SRS) V2.0')
table(['编号','功能','优先级','说明'], [
['FR-001','登录认证','P0','JWT 签发；连续 5 次失败锁定 10 分钟(Redis)'],
['FR-002','角色权限','P0','三级角色(admin/developer/caller)路由级鉴权'],
['FR-003','模型管理','P0','CRUD + 连通测试 + 输入/输出单价配置'],
['FR-004','模型统一接入','P0','LangChain ChatOpenAI 兼容多厂商，流式 + token 用量'],
['FR-005','智能体创建','P0','数据库方式配置(提示词/模型/参数/知识库/工具)'],
['FR-006','版本与发布','P0','发布存快照，版本历史 + 一键回滚'],
['FR-007','对话运行时','P0','SSE 流式 + 多轮 + 工具循环 + RAG；停止/重新生成/实时token'],
['FR-008','工具调用','P0','内置(时间/计算器) + HTTP 工具'],
['FR-009','知识库管理','P0','创建知识库，配置切片参数'],
['FR-010','文档处理','P0','PDF/Word/MD/TXT 解析切片；智谱 embedding-3 向量化(2048维)'],
['FR-011','检索增强','P0','pgvector 余弦检索 + 引用回填'],
['FR-012','工作流编排','P0','React Flow 拖拽，5 类节点'],
['FR-013','工作流运行','P0','LangGraph 执行 + 节点级日志'],
['FR-014','工具管理','P0','CRUD + 测试调用'],
['FR-015','运行监控','P0','运行记录 + token 用量 + 成本计算'],
['FR-016','审计日志','P0','记录登录/资源操作，管理员可查'],
['FR-017','API Key 管理','P1','生成(明文一次)/列表/禁用/删除 + 配额'],
['FR-018','定时调度','P1','APScheduler Cron 触发工作流'],
['FR-019','自动化测试','P1','pytest 12 用例覆盖核心接口'],
['FR-020','CI/CD','P1','GitHub Actions 后端测试 + 前端构建'],
])

doc.add_page_break()
h1('第二部分 架构设计 (ADD) V2.0')
h2('总体架构（分层）')
table(['层次','组成'], [
['接入层','React 控制台、REST API、SSE 流式'],
['应用层','认证/模型/智能体/对话/工具/知识库/工作流/监控/审计/API Key/定时调度'],
['能力层','模型网关(LangChain)、RAG 管道、工具执行器、工作流引擎(LangGraph)、会话管理器、调度器(APScheduler)'],
['数据层','PostgreSQL(pgvector)、Redis、MinIO'],
['基础设施','Docker Compose、GitHub Actions CI'],
])
h2('技术选型')
body('后端：FastAPI + SQLAlchemy 2.0 + LangChain/LangGraph + pgvector + Redis + MinIO + APScheduler + pytest')
body('前端：React 18 + TypeScript + Vite + Ant Design 5 + React Flow + Zustand + axios')
h2('核心模块')
body('模型网关：ChatOpenAI(stream_usage 提取 token)；对话：create_agent 工具循环；工作流：LangGraph StateGraph；')
body('RAG：pypdf/python-docx 解析 + 智谱 embedding-3 + pgvector；安全：bcrypt+AES+JWT+限流+审计；调度：APScheduler。')

doc.add_page_break()
h1('第三部分 数据库设计 (DBD) V2.0')
h2('表清单（17 张业务表）')
table(['表','说明'], [
['users','用户与角色'],['models','模型配置(含价格)'],['agents','智能体'],['agent_versions','智能体版本快照'],
['tools','工具定义'],['knowledge_bases','知识库'],['documents','文档(状态跟踪)'],['document_chunks','文档切片(向量)'],
['workflows','工作流 DAG'],['workflow_nodes','工作流节点'],['conversations','会话'],['messages','消息'],
['runs','运行记录'],['run_nodes','节点运行日志'],['audit_logs','审计日志'],['api_keys','API Key'],['scheduled_jobs','定时任务'],
])

doc.add_page_break()
h1('第四部分 接口设计 (API) V2.0')
h2('接口清单（按模块）')
table(['模块','接口'], [
['认证','POST /auth/login, GET /auth/me'],
['用户','GET/POST /users, PUT/DELETE /users/{id}'],
['模型','GET/POST /models, GET/PUT/DELETE /models/{id}, POST /models/{id}/test'],
['智能体','GET/POST /agents, GET/PUT/DELETE /agents/{id}, POST /publish, GET /versions, POST /rollback/{vid}'],
['对话','POST /agents/{id}/chat (SSE 流式)'],
['会话','GET /conversations, GET /conversations/{id}/messages, DELETE /conversations/{id}'],
['工具','GET/POST /tools, PUT/DELETE /tools/{id}, POST /tools/{id}/test'],
['知识库','GET/POST /knowledge-bases, DELETE /{id}, POST /{id}/documents, GET /{id}/documents, DELETE /{id}/documents/{doc_id}, POST /{id}/search'],
['工作流','GET/POST /workflows, GET/PUT/DELETE /workflows/{id}, POST /{id}/run, GET /{id}/runs'],
['运行','GET /runs, GET /runs/{id}'],
['审计','GET /audit-logs'],
['API Key','GET/POST /api-keys, POST /api-keys/{id}/toggle, DELETE /api-keys/{id}'],
['定时','GET/POST /schedules, POST /schedules/{id}/toggle, DELETE /schedules/{id}'],
])

doc.save('docs/agent-platform-design.docx')
print('SAVED OK')