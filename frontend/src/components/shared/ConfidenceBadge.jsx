import { Gauge } from 'lucide-react'

/** Renders a 0..1 model confidence as a percentage pill. */
export default function ConfidenceBadge({ value, label = 'confidence' }) {
  const numeric = Number.isFinite(value) ? value : 0
  const pct = Math.round(numeric * 100)
  const cls =
    pct >= 80
      ? 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/40'
      : pct >= 60
        ? 'bg-amber-500/15 text-amber-300 ring-amber-500/40'
        : 'bg-red-500/15 text-red-300 ring-red-500/40'

  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ${cls}`}>
      <Gauge size={13} aria-hidden="true" />
      {pct}% {label}
    </span>
  )
}
