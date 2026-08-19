import { Activity, ServerCrash, TriangleAlert } from 'lucide-react'
import AlertBadge from '../shared/AlertBadge'

function Stat({ label, value, tone = 'text-slate-100' }) {
  return (
    <div className="rounded-md bg-slate-900/60 px-3 py-2 ring-1 ring-slate-800">
      <p className="text-[11px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`mt-0.5 text-xl font-bold tabular-nums ${tone}`}>{value}</p>
    </div>
  )
}

/** Overall fleet health from GET /api/health-score plus a per-node roll-up. */
export default function SystemHealthCard({ score, nodes, error }) {
  if (error) {
    return (
      <section className="rounded-lg border border-red-500/40 bg-red-500/10 p-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-red-300">
          <ServerCrash size={16} aria-hidden="true" /> System Health unavailable
        </h2>
        <p className="mt-1 text-xs text-red-200/80">{error}</p>
      </section>
    )
  }

  const pct = score?.overall_pct ?? null
  const alerts = score?.active_alerts ?? 0
  const tone = pct === null ? 'text-slate-100' : pct >= 90 ? 'text-emerald-300' : pct >= 70 ? 'text-amber-300' : 'text-red-300'
  const degraded = (nodes ?? []).filter((node) => node.status !== 'healthy')

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
        <Activity size={16} className="text-sky-400" aria-hidden="true" /> System Health
      </h2>

      <div className="mt-3 grid grid-cols-3 gap-2">
        <Stat label="Overall" value={pct === null ? '--' : `${pct}%`} tone={tone} />
        <Stat label="Active alerts" value={alerts} tone={alerts > 0 ? 'text-red-300' : 'text-emerald-300'} />
        <Stat label="Nodes" value={nodes?.length ?? '--'} />
      </div>

      <div className="mt-3">
        {degraded.length === 0 ? (
          <p className="text-xs text-slate-500">All nodes reporting healthy.</p>
        ) : (
          <ul className="space-y-1.5">
            {degraded.map((node) => (
              <li key={node.id} className="flex items-center justify-between gap-2 text-xs">
                <span className="flex items-center gap-1.5 text-slate-300">
                  <TriangleAlert size={13} className="text-amber-400" aria-hidden="true" />
                  <strong className="font-mono">{node.id}</strong>
                  <span className="text-slate-500">{node.name}</span>
                </span>
                <span className="flex items-center gap-2">
                  <span className="font-mono tabular-nums text-slate-400">
                    cpu {node.cpu.toFixed(1)}% &middot; loss {node.packet_loss.toFixed(2)}%
                  </span>
                  <AlertBadge level={node.status} />
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
