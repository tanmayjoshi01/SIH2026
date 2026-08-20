import { useEffect, useState } from 'react'
import { Radio, ServerCrash } from 'lucide-react'
import { getAnomalies } from '../../api/client'
import AlertBadge from '../shared/AlertBadge'

const POLL_MS = 3000

const formatTime = (iso) => {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleTimeString()
}

/**
 * Live log feed. The parent page polls GET /api/telemetry every few
 * seconds and hands the newest-first rows down; this component renders
 * them, plus its own poll of GET /api/anomalies for a compact strip of
 * currently-elevated nodes above the raw log lines.
 */
export default function AnomalyFeed({ rows, error, degradedNodeIds = [], lastUpdated }) {
  const degraded = new Set(degradedNodeIds)
  const [anomalies, setAnomalies] = useState([])

  useEffect(() => {
    let cancelled = false
    const load = () => {
      getAnomalies()
        .then((data) => {
          if (!cancelled) setAnomalies(data)
        })
        .catch(() => {
          // Non-fatal: the telemetry feed below already surfaces a connectivity error.
        })
    }
    load()
    const timer = setInterval(load, POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  return (
    <section className="flex flex-col rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          <Radio size={16} className={error ? 'text-red-400' : 'animate-pulse text-emerald-400'} aria-hidden="true" />
          Live Telemetry Feed
        </h2>
        <span className="text-[11px] text-slate-500">
          {error ? 'polling failed' : lastUpdated ? `updated ${formatTime(lastUpdated)}` : 'connecting...'}
        </span>
      </div>

      {anomalies.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {anomalies.map((item) => (
            <AlertBadge
              key={item.id}
              level={item.severity}
              label={`${item.node_id} · ${Math.round(item.anomaly_score * 100)}%`}
            />
          ))}
        </div>
      )}

      <div className="mt-3 h-72 overflow-y-auto rounded-md bg-slate-950/60 ring-1 ring-slate-800">
        {error ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-4 text-center text-red-300">
            <ServerCrash size={22} aria-hidden="true" />
            <p className="text-xs">{error}</p>
          </div>
        ) : !rows || rows.length === 0 ? (
          <p className="p-4 text-xs text-slate-500">
            No telemetry rows yet. Seed the database and make sure the backend generator loop is running.
          </p>
        ) : (
          <ul className="divide-y divide-slate-800/70">
            {rows.map((row, index) => (
              <li
                key={`${row.timestamp}-${row.node_id}-${row.metric_name}-${index}`}
                className={`flex items-center gap-3 px-3 py-1.5 font-mono text-[11px] ${
                  degraded.has(row.node_id) ? 'bg-amber-500/5 text-amber-200' : 'text-slate-400'
                }`}
              >
                <span className="w-20 shrink-0 text-slate-600">{formatTime(row.timestamp)}</span>
                <span className="w-24 shrink-0 text-sky-300">{row.node_id}</span>
                <span className="flex-1 truncate">{row.metric_name}</span>
                <span className="shrink-0 tabular-nums text-slate-200">{row.value}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
