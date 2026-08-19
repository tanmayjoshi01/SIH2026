import { useEffect, useState } from 'react'
import { CheckCircle2, RotateCcw, ServerCrash, Zap } from 'lucide-react'
import { injectFault, resetSimulation } from '../../api/client'

// Fault ids accepted by the backend simulation package (core/taxonomy.py).
const FAULT_TYPES = [
  { id: 'bgp_flap', label: 'BGP Route Flap' },
  { id: 'high_cpu', label: 'High CPU Utilization' },
  { id: 'packet_loss', label: 'Packet Loss' },
]

const SELECT_CLS =
  'rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 focus:border-sky-500 focus:outline-none'

/**
 * Human-in-the-loop console. Today it drives the real simulation
 * endpoints; the approve/reject workflow lands on Day 3.
 */
export default function HITLControlPanel({ nodes, onAction }) {
  const [nodeId, setNodeId] = useState('')
  const [faultType, setFaultType] = useState(FAULT_TYPES[0].id)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!nodeId && nodes?.length) {
      const preferred = nodes.find((node) => node.id === 'router-7') ?? nodes[0]
      setNodeId(preferred.id)
    }
  }, [nodes, nodeId])

  const run = async (label, action) => {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const response = await action()
      setResult(`${label}: ${response.status}`)
      onAction?.()
    } catch (err) {
      setError(`${err.code} - ${err.message}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
        <Zap size={16} className="text-amber-400" aria-hidden="true" /> HITL Control Panel
      </h2>
      <p className="mt-1 text-[11px] text-slate-500">
        Operator-triggered actions. Fault injection calls the backend simulation engine directly.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <select
          className={SELECT_CLS}
          value={nodeId}
          onChange={(event) => setNodeId(event.target.value)}
          aria-label="Target node"
        >
          {(nodes ?? []).map((node) => (
            <option key={node.id} value={node.id}>
              {node.id} &mdash; {node.name}
            </option>
          ))}
        </select>

        <select
          className={SELECT_CLS}
          value={faultType}
          onChange={(event) => setFaultType(event.target.value)}
          aria-label="Fault type"
        >
          {FAULT_TYPES.map((fault) => (
            <option key={fault.id} value={fault.id}>
              {fault.label}
            </option>
          ))}
        </select>

        <button
          type="button"
          disabled={busy || !nodeId}
          onClick={() => run('Inject Fault', () => injectFault(nodeId, faultType))}
          className="inline-flex items-center gap-1.5 rounded-md bg-amber-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-amber-400 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Zap size={13} aria-hidden="true" /> Inject Fault
        </button>

        <button
          type="button"
          disabled={busy}
          onClick={() => run('Reset Simulation', resetSimulation)}
          className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RotateCcw size={13} aria-hidden="true" /> Reset
        </button>
      </div>

      {result && (
        <p className="mt-3 flex items-center gap-2 rounded-md bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300 ring-1 ring-emerald-500/40">
          <CheckCircle2 size={14} aria-hidden="true" /> {result}
        </p>
      )}
      {error && (
        <p className="mt-3 flex items-center gap-2 rounded-md bg-red-500/10 px-3 py-2 text-xs text-red-300 ring-1 ring-red-500/40">
          <ServerCrash size={14} aria-hidden="true" /> {error}
        </p>
      )}
    </section>
  )
}
