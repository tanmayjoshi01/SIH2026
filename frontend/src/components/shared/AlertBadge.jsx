import { AlertTriangle, CheckCircle2, CircleAlert, Info } from 'lucide-react'

const STYLES = {
  critical: { cls: 'bg-red-500/15 text-red-300 ring-red-500/40', Icon: CircleAlert },
  high: { cls: 'bg-red-500/15 text-red-300 ring-red-500/40', Icon: CircleAlert },
  degraded: { cls: 'bg-amber-500/15 text-amber-300 ring-amber-500/40', Icon: AlertTriangle },
  warning: { cls: 'bg-amber-500/15 text-amber-300 ring-amber-500/40', Icon: AlertTriangle },
  medium: { cls: 'bg-amber-500/15 text-amber-300 ring-amber-500/40', Icon: AlertTriangle },
  healthy: { cls: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/40', Icon: CheckCircle2 },
  low: { cls: 'bg-sky-500/15 text-sky-300 ring-sky-500/40', Icon: Info },
}

const FALLBACK = { cls: 'bg-slate-500/15 text-slate-300 ring-slate-500/40', Icon: Info }

/** Small status pill used for node status and anomaly severity. */
export default function AlertBadge({ level, label }) {
  const key = String(level ?? '').toLowerCase()
  const { cls, Icon } = STYLES[key] ?? FALLBACK
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${cls}`}>
      <Icon size={12} aria-hidden="true" />
      {label ?? level ?? 'unknown'}
    </span>
  )
}
