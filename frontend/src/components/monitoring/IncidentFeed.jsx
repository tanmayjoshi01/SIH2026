import { useEffect, useRef, useState } from 'react'
import { ServerCrash, Siren } from 'lucide-react'
import { getIncidents, INCIDENTS_WS_URL } from '../../api/client'
import AlertBadge from '../shared/AlertBadge'

const ACTIVE_STATUSES = new Set(['open', 'acknowledged'])
const RECONNECT_MS = 4000

const formatDuration = (openedAt) => {
  const opened = new Date(openedAt).getTime()
  if (Number.isNaN(opened)) return '—'
  const minutes = Math.max(0, (Date.now() - opened) / 60000)
  return minutes < 1 ? '<1m' : minutes < 60 ? `${Math.round(minutes)}m` : `${(minutes / 60).toFixed(1)}h`
}

const formatClock = (iso) => {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleTimeString()
}

/**
 * Active-incident overview for the monitoring page: node, severity,
 * status, opened time, live duration, peak_anomaly_score, and
 * root_cause_signal for every currently open/acknowledged incident.
 * Seeded from GET /api/incidents, then kept live over Developer 1's
 * /ws/incidents socket (confirmed shipped and stable in Step 0) --
 * OPEN/UPDATE events upsert, RESOLVE drops the row off this "active"
 * view. Falls back to polling if the socket cannot connect.
 */
export default function IncidentFeed() {
  const [incidents, setIncidents] = useState([])
  const [error, setError] = useState(null)
  const [wsConnected, setWsConnected] = useState(false)
  const cancelled = useRef(false)

  useEffect(() => {
    cancelled.current = false

    const loadInitial = () => {
      getIncidents()
        .then((rows) => {
          if (cancelled.current) return
          setIncidents(rows.filter((row) => ACTIVE_STATUSES.has(row.status)))
          setError(null)
        })
        .catch((err) => {
          if (!cancelled.current) setError(`${err.code} - ${err.message}`)
        })
    }

    loadInitial()

    let socket
    let reconnectTimer

    const connect = () => {
      socket = new WebSocket(INCIDENTS_WS_URL)

      socket.onopen = () => {
        if (cancelled.current) return
        setWsConnected(true)
        loadInitial() // catch anything that opened/resolved between the initial fetch and the socket opening
      }

      socket.onmessage = (event) => {
        if (cancelled.current) return
        try {
          const payload = JSON.parse(event.data)
          const incident = payload.incident
          if (!incident) return
          setIncidents((prev) => {
            const withoutThis = prev.filter((row) => row.id !== incident.id)
            return ACTIVE_STATUSES.has(incident.status) ? [incident, ...withoutThis] : withoutThis
          })
        } catch {
          // Ignore a malformed push; the next OPEN/UPDATE/RESOLVE event or poll will resync.
        }
      }

      socket.onclose = () => {
        if (cancelled.current) return
        setWsConnected(false)
        reconnectTimer = setTimeout(connect, RECONNECT_MS)
      }

      socket.onerror = () => {
        socket.close()
      }
    }

    connect()

    return () => {
      cancelled.current = true
      clearTimeout(reconnectTimer)
      socket?.close()
    }
  }, [])

  const sorted = [...incidents].sort((a, b) => new Date(b.opened_at) - new Date(a.opened_at))

  return (
    <section className="flex flex-col rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          <Siren size={16} className={sorted.length > 0 ? 'text-red-400' : 'text-slate-500'} aria-hidden="true" />
          Active Incidents
        </h2>
        <span className="text-[11px] text-slate-500">{wsConnected ? 'live' : 'reconnecting...'}</span>
      </div>

      <div className="mt-3 space-y-2">
        {error ? (
          <div className="flex items-center gap-2 rounded-md bg-red-500/10 px-3 py-2 text-xs text-red-300 ring-1 ring-red-500/40">
            <ServerCrash size={14} aria-hidden="true" /> {error}
          </div>
        ) : sorted.length === 0 ? (
          <p className="text-xs text-slate-500">No active incidents. Network is nominal.</p>
        ) : (
          sorted.map((incident) => (
            <div key={incident.id} className="rounded-md border border-slate-700 bg-slate-950/60 p-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-xs font-semibold text-sky-300">{incident.node_id}</span>
                <div className="flex items-center gap-1.5">
                  <AlertBadge level={incident.severity} />
                  <AlertBadge level={incident.status === 'acknowledged' ? 'medium' : 'critical'} label={incident.status} />
                </div>
              </div>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-slate-400">
                <span>opened {formatClock(incident.opened_at)}</span>
                <span>duration {formatDuration(incident.opened_at)}</span>
                <span className="tabular-nums">peak {Math.round(incident.peak_anomaly_score * 100)}%</span>
              </div>
              {incident.root_cause_signal && (
                <p className="mt-1 truncate text-[11px] text-slate-500">cause: {incident.root_cause_signal}</p>
              )}
            </div>
          ))
        )}
      </div>
    </section>
  )
}
