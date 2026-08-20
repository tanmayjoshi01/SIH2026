import { useCallback, useEffect, useRef, useState } from 'react'
import { getHealthScore, getNodes, getTelemetry } from '../api/client'
import SystemHealthCard from '../components/monitoring/SystemHealthCard'
import TelemetryChart from '../components/monitoring/TelemetryChart'
import AnomalyFeed from '../components/monitoring/AnomalyFeed'
import AIStatusSummary from '../components/monitoring/AIStatusSummary'
import HITLControlPanel from '../components/monitoring/HITLControlPanel'
import IncidentFeed from '../components/monitoring/IncidentFeed'

const POLL_MS = 2500
const FEED_LIMIT = 150
const CHART_LIMIT = 300
const CHART_POINTS = 40
const METRICS = ['cpu', 'memory', 'packet_loss', 'latency_ms', 'interface_errors', 'bgp_flap_count']

const formatClock = (iso) => {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleTimeString()
}

export default function LiveMonitoring() {
  const [nodes, setNodes] = useState([])
  const [score, setScore] = useState(null)
  const [feed, setFeed] = useState([])
  const [series, setSeries] = useState([])
  const [error, setError] = useState(null)
  const [lastUpdated, setLastUpdated] = useState(null)

  const [chartNode, setChartNode] = useState('router-7')
  const [chartMetric, setChartMetric] = useState('cpu')

  const cancelled = useRef(false)

  const load = useCallback(async () => {
    try {
      const [feedRows, nodeRows, scoreRow, chartRows] = await Promise.all([
        getTelemetry({ limit: FEED_LIMIT }),
        getNodes(),
        getHealthScore(),
        getTelemetry({ node_id: chartNode, limit: CHART_LIMIT }),
      ])
      if (cancelled.current) return

      setFeed(feedRows)
      setNodes(nodeRows)
      setScore(scoreRow)
      setSeries(
        chartRows
          .filter((row) => row.metric_name === chartMetric)
          .slice(0, CHART_POINTS)
          .reverse()
          .map((row) => ({ time: formatClock(row.timestamp), value: row.value })),
      )
      setError(null)
      setLastUpdated(new Date().toISOString())
    } catch (err) {
      if (!cancelled.current) setError(`${err.code} - ${err.message}`)
    }
  }, [chartNode, chartMetric])

  useEffect(() => {
    cancelled.current = false
    load()
    const timer = setInterval(load, POLL_MS)
    return () => {
      cancelled.current = true
      clearInterval(timer)
    }
  }, [load])

  const degradedNodeIds = nodes.filter((node) => node.status !== 'healthy').map((node) => node.id)
  const selectCls =
    'rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 focus:border-sky-500 focus:outline-none'

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-slate-100">Live Monitoring</h2>
          <p className="text-xs text-slate-500">
            Polling the backend every {POLL_MS / 1000}s &middot; data served from the local Postgres instance.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <select className={selectCls} value={chartNode} onChange={(e) => setChartNode(e.target.value)} aria-label="Chart node">
            {(nodes.length ? nodes.map((n) => n.id) : [chartNode]).map((id) => (
              <option key={id} value={id}>{id}</option>
            ))}
          </select>
          <select className={selectCls} value={chartMetric} onChange={(e) => setChartMetric(e.target.value)} aria-label="Chart metric">
            {METRICS.map((metric) => (
              <option key={metric} value={metric}>{metric}</option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-xs text-red-300">
          <strong className="font-semibold">Backend unreachable.</strong> {error}
          <span className="ml-1 text-red-200/70">Retrying every {POLL_MS / 1000}s.</span>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          <SystemHealthCard score={score} nodes={nodes} error={error} />
          <TelemetryChart data={series} nodeId={chartNode} metricName={chartMetric} error={error} />
          <HITLControlPanel nodes={nodes} onAction={load} />
        </div>
        <div className="space-y-4">
          <IncidentFeed />
          <AnomalyFeed rows={feed} error={error} degradedNodeIds={degradedNodeIds} lastUpdated={lastUpdated} />
          <AIStatusSummary />
        </div>
      </div>
    </div>
  )
}
