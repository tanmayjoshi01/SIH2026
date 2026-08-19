import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { LineChart as LineChartIcon, ServerCrash } from 'lucide-react'

/**
 * Time series for one node/metric pair. `data` is already sorted oldest
 * -> newest by the page, which owns the polling.
 */
export default function TelemetryChart({ data, nodeId, metricName, error }) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-200">
        <LineChartIcon size={16} className="text-sky-400" aria-hidden="true" />
        Telemetry &mdash; <span className="font-mono text-sky-300">{nodeId}</span>
        <span className="text-slate-500">/</span>
        <span className="font-mono text-sky-300">{metricName}</span>
      </h2>

      <div className="mt-3 h-64">
        {error ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 rounded-md bg-red-500/10 text-red-300 ring-1 ring-red-500/40">
            <ServerCrash size={22} aria-hidden="true" />
            <p className="text-xs">{error}</p>
          </div>
        ) : !data || data.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-slate-500">
            Waiting for telemetry from the generator loop&hellip;
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 5, right: 10, bottom: 0, left: -20 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="time" stroke="#64748b" tick={{ fontSize: 10 }} minTickGap={24} />
              <YAxis stroke="#64748b" tick={{ fontSize: 10 }} domain={['auto', 'auto']} />
              <Tooltip
                contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 6, fontSize: 12 }}
                labelStyle={{ color: '#94a3b8' }}
              />
              <Line
                type="monotone"
                dataKey="value"
                name={metricName}
                stroke="#38bdf8"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  )
}
