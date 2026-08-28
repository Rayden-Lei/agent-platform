import client from './client'

export const login = (data: { username: string; password: string }) => client.post('/auth/login', data)
export const me = () => client.get('/auth/me')

export const listModels = () => client.get('/models')
export const createModel = (data: any) => client.post('/models', data)
export const updateModel = (id: number, data: any) => client.put(`/models/${id}`, data)
export const deleteModel = (id: number) => client.delete(`/models/${id}`)

export const listAgents = () => client.get('/agents')
export const createAgent = (data: any) => client.post('/agents', data)
export const updateAgent = (id: number, data: any) => client.put(`/agents/${id}`, data)
export const deleteAgent = (id: number) => client.delete(`/agents/${id}`)
export const publishAgent = (id: number) => client.post(`/agents/${id}/publish`)
export const getAgentVersions = (id: number) => client.get(`/agents/${id}/versions`)
export const rollbackAgent = (id: number, versionId: number) => client.post(`/agents/${id}/rollback/${versionId}`)

export const listConversations = () => client.get('/conversations')
export const listMessages = (id: number) => client.get(`/conversations/${id}/messages`)
export const deleteConversation = (id: number) => client.delete(`/conversations/${id}`)

export const listTools = () => client.get('/tools')
export const createTool = (data: any) => client.post('/tools', data)
export const updateTool = (id: number, data: any) => client.put(`/tools/${id}`, data)
export const deleteTool = (id: number) => client.delete(`/tools/${id}`)
export const testTool = (id: number, data: any) => client.post(`/tools/${id}/test`, data)

export const listKBs = () => client.get('/knowledge-bases')
export const createKB = (data: any) => client.post('/knowledge-bases', data)
export const deleteKB = (id: number) => client.delete(`/knowledge-bases/${id}`)
export const listDocs = (kbId: number) => client.get(`/knowledge-bases/${kbId}/documents`)
export const uploadDoc = (kbId: number, file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return client.post(`/knowledge-bases/${kbId}/documents`, fd)
}
export const searchKB = (kbId: number, data: any) => client.post(`/knowledge-bases/${kbId}/search`, data)

export const listWorkflows = () => client.get('/workflows')
export const getWorkflow = (id: number) => client.get(`/workflows/${id}`)
export const createWorkflow = (data: any) => client.post('/workflows', data)
export const updateWorkflow = (id: number, data: any) => client.put(`/workflows/${id}`, data)
export const deleteWorkflow = (id: number) => client.delete(`/workflows/${id}`)
export const runWorkflow = (id: number, data: any) => client.post(`/workflows/${id}/run`, data)
export const listWorkflowRuns = (id: number) => client.get(`/workflows/${id}/runs`)

export const listRuns = () => client.get('/runs')
export const getRun = (id: number) => client.get(`/runs/${id}`)

export const listUsers = () => client.get('/users')
export const createUser = (data: any) => client.post('/users', data)
export const updateUser = (id: number, data: any) => client.put(`/users/${id}`, data)
export const deleteUser = (id: number) => client.delete(`/users/${id}`)
export const listAuditLogs = () => client.get('/audit-logs')
export const listApiKeys = () => client.get('/api-keys')
export const createApiKey = (data: any) => client.post('/api-keys', data)
export const toggleApiKey = (id: number) => client.post(`/api-keys/${id}/toggle`)
export const deleteApiKey = (id: number) => client.delete(`/api-keys/${id}`)
export const listSchedules = () => client.get('/schedules')
export const createSchedule = (data: any) => client.post('/schedules', data)
export const toggleSchedule = (id: number) => client.post(`/schedules/${id}/toggle`)
export const deleteSchedule = (id: number) => client.delete(`/schedules/${id}`)