import { lazy } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from './store/auth'
import AppLayout from './components/AppLayout'
import Login from './pages/Login'

// 页面按路由懒加载：首屏只带布局与登录；AppLayout 的 <Outlet> 外套了 Suspense 骨架
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Models = lazy(() => import('./pages/Models'))
const Agents = lazy(() => import('./pages/Agents'))
const Chat = lazy(() => import('./pages/Chat'))
const KnowledgeBases = lazy(() => import('./pages/KnowledgeBases'))
const Workflows = lazy(() => import('./pages/Workflows'))
const WorkflowEditor = lazy(() => import('./pages/WorkflowEditor'))
const Tools = lazy(() => import('./pages/Tools'))
const Runs = lazy(() => import('./pages/Runs'))
const Users = lazy(() => import('./pages/Users'))
const AuditLogs = lazy(() => import('./pages/AuditLogs'))
const ApiKeys = lazy(() => import('./pages/ApiKeys'))
const Schedules = lazy(() => import('./pages/Schedules'))
const PromptTemplates = lazy(() => import('./pages/PromptTemplates'))

// 路由守卫：未登录（无 token）时重定向到 /login，已登录则渲染受保护的子路由
function RequireAuth({ children }: { children: JSX.Element }) {
  const { token } = useAuth()
  if (!token) return <Navigate to="/login" replace />
  return children
}

// 应用路由表：/login 为公开页，其余业务页面挂在带鉴权的 AppLayout 壳布局下；未匹配路径兜底重定向到首页
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<RequireAuth><AppLayout /></RequireAuth>}>
        <Route index element={<Dashboard />} />
        <Route path="agents" element={<Agents />} />
        <Route path="prompt-templates" element={<PromptTemplates />} />
        <Route path="chat" element={<Chat />} />
        <Route path="models" element={<Models />} />
        <Route path="tools" element={<Tools />} />
        <Route path="knowledge-bases" element={<KnowledgeBases />} />
        <Route path="workflows" element={<Workflows />} />
        {/* 新建与编辑共用同一个工作流编辑器页面，通过是否有 :id 区分 */}
        <Route path="workflows/new" element={<WorkflowEditor />} />
        <Route path="workflows/:id/edit" element={<WorkflowEditor />} />
        <Route path="runs" element={<Runs />} />
        <Route path="users" element={<Users />} />
        <Route path="audit-logs" element={<AuditLogs />} />
        <Route path="api-keys" element={<ApiKeys />} />
        <Route path="schedules" element={<Schedules />} />
      </Route>
      {/* 兜底：未匹配的路径统一回到首页 */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
