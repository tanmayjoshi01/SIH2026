import { useEffect, useState } from 'react'
import { Cpu, Database, Library, WifiOff, TriangleAlert } from 'lucide-react'
import { getHealth } from '../../api/client'

const CHIPS = [
  { key: 'network', label: 'NETWORK', Icon: WifiOff },
  { key: 'llm', label: 'LLM', Icon: Cpu },
  { key: 'rag', label: 'RAG', Icon: Library },
  { key: 'db', label: 'DB', Icon: Database },
]

const HEALTH_POLL_MS = 5000

/**
 * Air-gap status strip. The values come from GET /api/health, never from
 * hardcoded frontend constants, so the strip goes red the moment the
 * backend cannot confirm the system's posture.
 */
export default function TopHeaderBar() {
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        const data = await getHealth()
        if (cancelled) return
        setHealth(data)
        setError(null)
      } catch (err) {
        if (cancelled) return
        setHealth(null)
        setError(err.message)
      }
    }

    load()
    const timer = setInterval(load, HEALTH_POLL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  return (
    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 bg-slate-900 px-5 py-3">
      <div>
        <h1 className="text-base font-bold tracking-tight text-slate-100">
          Predictive Network Operations Centre
        </h1>
        <p className="text-[11px] text-slate-500">
          All inference, retrieval and storage stay inside the isolated enclave.
        </p>
      </div>

      {error ? (
        <div className="flex items-center gap-2 rounded-md bg-red-500/15 px-3 py-1.5 text-xs font-semibold text-red-300 ring-1 ring-red-500/40">
          <TriangleAlert size={14} aria-hidden="true" />
          AIR-GAP STATUS UNAVAILABLE &mdash; {error}
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <span className="rounded-md bg-emerald-500/15 px-2.5 py-1 text-[11px] font-bold tracking-wider text-emerald-300 ring-1 ring-emerald-500/40">
            AIR-GAPPED
          </span>
          {CHIPS.map(({ key, label, Icon }) => {
            const value = health?.air_gap?.[key] ?? '...'
            return (
              <span
                key={key}
                className="inline-flex items-center gap-1.5 rounded-md bg-slate-800 px-2.5 py-1 font-mono text-[11px] text-slate-300 ring-1 ring-slate-700"
              >
                <Icon size={12} className="text-emerald-400" aria-hidden="true" />
                {label}: <strong className="text-emerald-300">{value}</strong>
              </span>
            )
          })}
        </div>
      )}
    </header>
  )
}
