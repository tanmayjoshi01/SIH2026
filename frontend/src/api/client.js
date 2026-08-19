/**
 * api/client.js
 *
 * Single place that knows how to talk to the FastAPI backend. Every
 * helper throws an ApiError carrying the backend's {error, code}
 * envelope, so callers can render a visible error state instead of a
 * silently empty panel.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  constructor(message, code, status) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch {
    // Network-level failure: backend down, wrong port, blocked by CORS.
    throw new ApiError(`Cannot reach the API at ${BASE_URL}`, 'NETWORK_ERROR', 0)
  }

  let body = null
  try {
    body = await response.json()
  } catch {
    body = null
  }

  if (!response.ok) {
    const message = body?.error ?? `Request failed with HTTP ${response.status}`
    const code = body?.code ?? `HTTP_${response.status}`
    throw new ApiError(message, code, response.status)
  }

  return body
}

function query(params) {
  const search = new URLSearchParams()
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, value)
  })
  const string = search.toString()
  return string ? `?${string}` : ''
}

const post = (path, payload) => request(path, { method: 'POST', body: JSON.stringify(payload ?? {}) })

/* Live, database-backed endpoints */
export const getHealth = () => request('/api/health')
export const getNodes = () => request('/api/nodes')
export const getLinks = () => request('/api/links')
export const getTopology = () => request('/api/topology')
export const getHealthScore = () => request('/api/health-score')
export const getTelemetry = (params) => request(`/api/telemetry${query(params)}`)

/* Simulation (thin wrapper over the backend fault injector) */
export const injectFault = (nodeId, faultType) =>
  post('/api/simulation/fault', { node_id: nodeId, fault_type: faultType })
export const resetSimulation = () => post('/api/simulation/reset')

/* Day 1 stubs - real implementations land on Day 2/3 */
export const getAnomalies = () => request('/api/anomalies')
export const getPredictions = () => request('/api/predictions')
export const askCopilot = (question) => post('/api/chat', { question })
export const approveRecommendation = (payload) => post('/api/hitl/approve', payload)
export const rejectRecommendation = (payload) => post('/api/hitl/reject', payload)
export const getAuditLogs = () => request('/api/audit-logs')

export { BASE_URL }
