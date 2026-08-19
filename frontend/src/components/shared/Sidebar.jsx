import { NavLink } from 'react-router-dom'
import { Activity, Bot, ScrollText, ShieldCheck } from 'lucide-react'

const NAV = [
  { to: '/', label: 'Live Monitoring', Icon: Activity, end: true },
  { to: '/copilot', label: 'AI Copilot', Icon: Bot },
  { to: '/audit', label: 'Audit Trail', Icon: ScrollText },
]

export default function Sidebar() {
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-slate-800 bg-slate-950">
      <div className="flex items-center gap-2 border-b border-slate-800 px-4 py-4">
        <ShieldCheck className="text-emerald-400" size={22} aria-hidden="true" />
        <div className="leading-tight">
          <p className="text-sm font-bold text-slate-100">NOC Copilot</p>
          <p className="text-[11px] text-slate-500">Air-Gapped Predictive Ops</p>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-1 p-3">
        {NAV.map(({ to, label, Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors ${
                isActive
                  ? 'bg-sky-500/15 font-semibold text-sky-300 ring-1 ring-sky-500/30'
                  : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
              }`
            }
          >
            <Icon size={16} aria-hidden="true" />
            {label}
          </NavLink>
        ))}
      </nav>

      <p className="border-t border-slate-800 px-4 py-3 text-[11px] text-slate-600">
        SIH 2026 &middot; Day 1 prototype
      </p>
    </aside>
  )
}
