// API 封装（B-T2）：token 存 localStorage，统一 fetch 带 Authorization
const TOKEN_KEY = 'rehab_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

async function request(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`/api${path}`, { ...options, headers })
  if (res.status === 401) {
    clearToken()
    window.location.hash = '#/login'
    throw new Error('未认证')
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `请求失败（${res.status}）`)
  }
  if (res.status === 204) return null
  return res.json()
}

export const api = {
  login: (username, password) =>
    request('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) }),
  me: () => request('/auth/me'),
  listPatients: () => request('/patients'),
  getPatient: (id) => request(`/patients/${id}`),
  createPatient: (data) => request('/patients', { method: 'POST', body: JSON.stringify(data) }),
  updatePatient: (id, data) => request(`/patients/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deletePatient: (id) => request(`/patients/${id}`, { method: 'DELETE' }),
  getPatternKeywords: () => request('/meta/pattern-keywords'),
  listAssessments: (patientId) => request(`/assessments/${patientId}`),
  createAssessment: (data) => request('/assessments', { method: 'POST', body: JSON.stringify(data) }),
  listPrescriptions: (patientId) => request(`/prescriptions/${patientId}`),
  latestAssessment: (patientId) => request(`/patients/${patientId}/latest-assessment`),
  generateRx: (data) => request('/prescriptions/generate', { method: 'POST', body: JSON.stringify(data) }),
  updateRx: (rxId, data) => request(`/prescriptions/${rxId}`, { method: 'PUT', body: JSON.stringify(data) }),
  signRx: (rxId, data) => request(`/prescriptions/${rxId}/sign`, { method: 'POST', body: JSON.stringify(data) }),
  listFollowups: (patientId) => request(`/followups/${patientId}`),
  generateFollowups: (data) => request('/followups/generate', { method: 'POST', body: JSON.stringify(data) }),
  completeFollowup: (fuId, data) => request(`/followups/${fuId}/complete`, { method: 'POST', body: JSON.stringify(data) }),
  listAlerts: (status) => request(`/alerts?status=${status}`),
  handleAlert: (alertId, data) => request(`/alerts/${alertId}/handle`, { method: 'POST', body: JSON.stringify(data) }),
  listRules: () => request('/rules'),
  updateRule: (table, rowId, data) => request(`/rules/${table}/${rowId}`, { method: 'PUT', body: JSON.stringify(data) }),
}
