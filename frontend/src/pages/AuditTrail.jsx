import { useEffect, useState } from 'react'
import { ScrollText, ServerCrash, ShieldCheck } from 'lucide-react'
import { getAuditLogs } from '../api/client'

const formatTime = (iso) => {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}

export default function AuditTrail() {
  const [logs, setLogs] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    getAuditLogs()
      .then((rows) => {
        if (cancelled) return
        setLogs(rows)
        setError(null)
      })
      .catch((err) => {
        if (!cancelled) setError(`${err.code} - ${err.message}`)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div className="space-y-4">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-bold text-slate-100">
          <ScrollText size={20} className="text-emerald-400" aria-hidden="true" /> Audit Trail
          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-normal text-slate-400">
            stubbed &middot; hash chaining lands Day 3
          </span>
        </h2>
        <p className="text-xs text-slate-500">
          Tamper-evident record of every AI recommendation and operator decision.
        </p>
      </div>

      {error ? (
        <div className="flex items-center gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-xs text-red-300">
          <ServerCrash size={15} aria-hidden="true" /> {error}
        </div>
      ) : logs.length === 0 ? (
        <p className="rounded-lg border border-slate-800 bg-slate-900 px-4 py-3 text-xs text-slate-500">
          Loading audit entries&hellip;
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead className="border-b border-slate-800 text-[11px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-4 py-2.5 font-medium">ID</th>
                <th className="px-4 py-2.5 font-medium">Timestamp</th>
                <th className="px-4 py-2.5 font-medium">Event</th>
                <th className="px-4 py-2.5 font-medium">Payload</th>
                <th className="px-4 py-2.5 font-medium">Hash</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/70">
              {logs.map((log) => (
                <tr key={log.id} className="align-top hover:bg-slate-800/40">
                  <td className="px-4 py-2.5 font-mono text-slate-500">#{log.id}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-slate-400">{formatTime(log.timestamp)}</td>
                  <td className="px-4 py-2.5">
                    <span className="rounded bg-slate-800 px-2 py-0.5 font-mono text-[11px] text-sky-300">
                      {log.event_type}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-[11px] text-slate-400">
                    {Object.entries(log.payload ?? {}).map(([key, value]) => (
                      <div key={key}>
                        <span className="text-slate-600">{key}:</span> {String(value)}
                      </div>
                    ))}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-emerald-400">
                      <ShieldCheck size={12} aria-hidden="true" />
                      {log.hash ? `${log.hash.slice(0, 16)}...` : 'unchained'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
