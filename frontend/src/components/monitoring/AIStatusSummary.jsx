import { useEffect, useState } from 'react'
import { Brain, ServerCrash } from 'lucide-react'
import { getAnomalies, getPredictions } from '../../api/client'
import AlertBadge from '../shared/AlertBadge'

/**
 * Detector / forecaster summary. Reads the real Day 2 endpoints
 * (/api/anomalies, /api/predictions), backed by Developer 1's anomaly
 * scoring service.
 */
const POLL_MS = 3000

export default function AIStatusSummary() {
  const [anomalies, setAnomalies] = useState([])
  const [predictions, setPredictions] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    const load = () => {
      Promise.all([getAnomalies(), getPredictions()])
        .then(([anomalyRows, predictionRows]) => {
          if (cancelled) return
          setAnomalies(anomalyRows)
          setPredictions(predictionRows)
          setError(null)
        })
        .catch((err) => {
          if (!cancelled) setError(err.message)
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
    <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
        <Brain size={16} className="text-violet-400" aria-hidden="true" /> AI Status
      </h2>

      {error ? (
        <p className="mt-3 flex items-center gap-2 rounded-md bg-red-500/10 px-3 py-2 text-xs text-red-300 ring-1 ring-red-500/40">
          <ServerCrash size={14} aria-hidden="true" /> {error}
        </p>
      ) : (
        <div className="mt-3 space-y-3">
          <div>
            <p className="text-[11px] uppercase tracking-wider text-slate-500">Detected anomalies</p>
            <ul className="mt-1.5 space-y-1.5">
              {anomalies.length === 0 && <li className="text-xs text-slate-500">No anomalies above threshold.</li>}
              {anomalies.map((item) => (
                <li key={item.id} className="flex items-center justify-between gap-2 text-xs">
                  <span className="font-mono text-sky-300">{item.node_id}</span>
                  <span className="flex items-center gap-2">
                    <span className="font-mono tabular-nums text-slate-400">{item.anomaly_score.toFixed(2)}</span>
                    <AlertBadge level={item.severity} />
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <div>
            <p className="text-[11px] uppercase tracking-wider text-slate-500">Failure forecast</p>
            <ul className="mt-1.5 space-y-1.5">
              {predictions.length === 0 && <li className="text-xs text-slate-500">No nodes trending toward failure.</li>}
              {predictions.map((item) => (
                <li key={item.id} className="flex items-center justify-between gap-2 text-xs">
                  <span className="font-mono text-sky-300">{item.node_id}</span>
                  <span className="tabular-nums text-slate-400">
                    {Math.round(item.failure_probability * 100)}%
                    {item.eta_minutes != null ? ` in ~${item.eta_minutes} min` : ' (not currently rising)'}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </section>
  )
}
