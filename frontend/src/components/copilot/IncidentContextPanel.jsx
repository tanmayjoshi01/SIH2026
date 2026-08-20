import { useEffect, useState } from 'react'
import { CheckCircle2, ShieldAlert, TrendingDown, TrendingUp } from 'lucide-react'
import { acknowledgeIncident, getAnomalies, getIncidents } from '../../api/client'
import AlertBadge from '../shared/AlertBadge'

const ACTIVE_STATUSES = new Set(['open', 'acknowledged'])
const POLL_MS = 4000

const formatDuration = (openedAt) => {
  const opened = new Date(openedAt).getTime()
  if (Number.isNaN(opened)) return 'unknown'
  const minutes = Math.max(0, (Date.now() - opened) / 60000)
  return minutes < 1 ? 'under a minute' : minutes < 60 ? `${Math.round(minutes)} min` : `${(minutes / 60).toFixed(1)} hr`
}

/**
 * Active-incident context block for the copilot page: the node currently
 * under discussion's open/acknowledged incident (if any), read straight
 * from GET /api/incidents, plus the node's current anomaly_score (from
 * GET /api/anomalies) next to the incident's peak so an operator can see
 * at a glance whether it's improving. The Acknowledge button calls
 * POST /api/incidents/{id}/acknowledge directly -- this component holds
 * no incident state-transition logic of its own.
 */
export default function IncidentContextPanel({ nodeId }) {
  const [incident, setIncident] = useState(null)
  const [currentScore, setCurrentScore] = useState(null)
  const [error, setError] = useState(null)
  const [acking, setAcking] = useState(false)
  const [ackMessage, setAckMessage] = useState(null)

  useEffect(() => {
    if (!nodeId) {
      setIncident(null)
      return
    }
    let cancelled = false

    const load = () => {
      Promise.all([getIncidents({ node_id: nodeId }), getAnomalies()])
        .then(([incidentRows, anomalyRows]) => {
          if (cancelled) return
          const active = incidentRows.find((row) => ACTIVE_STATUSES.has(row.status)) ?? null
          setIncident(active)
          const anomalyRow = anomalyRows.find((row) => row.node_id === nodeId)
          setCurrentScore(anomalyRow ? anomalyRow.anomaly_score : null)
          setError(null)
        })
        .catch((err) => {
          if (!cancelled) setError(`${err.code} - ${err.message}`)
        })
    }

    load()
    const timer = setInterval(load, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [nodeId])

  const acknowledge = async () => {
    if (!incident) return
    setAcking(true)
    setAckMessage(null)
    try {
      const updated = await acknowledgeIncident(incident.id)
      setIncident(updated)
      setAckMessage('Acknowledged.')
    } catch (err) {
      setAckMessage(`${err.code} - ${err.message}`)
    } finally {
      setAcking(false)
    }
  }

  if (!nodeId) return null

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>
    )
  }

  if (!incident) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-500">
        <CheckCircle2 size={14} className="text-emerald-400" aria-hidden="true" />
        No active incident on <span className="font-mono text-slate-300">{nodeId}</span>.
      </div>
    )
  }

  const improving = currentScore != null && currentScore < incident.peak_anomaly_score

  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-200">
          <ShieldAlert size={15} className="text-red-400" aria-hidden="true" /> Active Incident #{incident.id}
        </h3>
        <div className="flex items-center gap-1.5">
          <AlertBadge level={incident.severity} />
          <AlertBadge level={incident.status === 'acknowledged' ? 'medium' : 'critical'} label={incident.status} />
        </div>
      </div>

      <dl className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
        <div>
          <dt className="text-[11px] uppercase tracking-wider text-slate-500">Node</dt>
          <dd className="font-mono text-sky-300">{incident.node_id}</dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wider text-slate-500">Open for</dt>
          <dd className="text-slate-200">{formatDuration(incident.opened_at)}</dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wider text-slate-500">Peak score</dt>
          <dd className="tabular-nums text-slate-200">{Math.round(incident.peak_anomaly_score * 100)}%</dd>
        </div>
        <div>
          <dt className="text-[11px] uppercase tracking-wider text-slate-500">Current score</dt>
          <dd className="flex items-center gap-1 tabular-nums text-slate-200">
            {currentScore != null ? `${Math.round(currentScore * 100)}%` : 'n/a'}
            {currentScore != null &&
              (improving ? (
                <TrendingDown size={12} className="text-emerald-400" aria-hidden="true" />
              ) : (
                <TrendingUp size={12} className="text-amber-400" aria-hidden="true" />
              ))}
          </dd>
        </div>
        <div className="col-span-2">
          <dt className="text-[11px] uppercase tracking-wider text-slate-500">Root cause signal</dt>
          <dd className="truncate text-slate-200">{incident.root_cause_signal ?? 'unknown'}</dd>
        </div>
      </dl>

      {incident.status === 'open' && (
        <button
          type="button"
          onClick={acknowledge}
          disabled={acking}
          className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-amber-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <ShieldAlert size={13} aria-hidden="true" /> {acking ? 'Acknowledging...' : 'Acknowledge Incident'}
        </button>
      )}
      {ackMessage && <p className="mt-2 text-[11px] text-emerald-300">{ackMessage}</p>}
    </div>
  )
}
