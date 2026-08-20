import { Bot, ServerCrash, ShieldQuestion, User } from 'lucide-react'
import AlertBadge from '../shared/AlertBadge'
import ConfidenceBadge from '../shared/ConfidenceBadge'
import CitationBadge from '../shared/CitationBadge'

function Field({ label, children }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wider text-slate-500">{label}</p>
      <div className="mt-0.5 text-sm text-slate-200">{children}</div>
    </div>
  )
}

/** One turn in the copilot chat: a right-aligned user question, or a left-aligned answer/error card from the assistant. */
export default function MessageBubble({ message }) {
  if (message.role === 'user') {
    return (
      <div className="flex items-start justify-end gap-2 self-end">
        <div className="max-w-[85%] rounded-lg bg-sky-500/15 px-3 py-2 text-sm text-sky-100 ring-1 ring-sky-500/30">
          {message.text}
        </div>
        <User size={16} className="mt-1.5 shrink-0 text-slate-500" aria-hidden="true" />
      </div>
    )
  }

  if (message.error) {
    return (
      <div className="flex items-start gap-2 self-start">
        <ServerCrash size={16} className="mt-1.5 shrink-0 text-red-400" aria-hidden="true" />
        <div className="max-w-[85%] rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          {message.error}
        </div>
      </div>
    )
  }

  const answer = message.answer
  const isFallback = answer.mode === 'fallback'

  return (
    <div className="flex items-start gap-2 self-start">
      <Bot size={16} className="mt-1.5 shrink-0 text-violet-400" aria-hidden="true" />
      <div className="max-w-[92%] space-y-2.5 rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <ConfidenceBadge value={answer.confidence} />
          <AlertBadge
            level={answer.risk >= 0.7 ? 'critical' : answer.risk >= 0.4 ? 'warning' : 'low'}
            label={`risk ${Math.round(answer.risk * 100)}%`}
          />
          {answer.requires_human_approval && (
            <span className="inline-flex items-center gap-1 rounded-full bg-violet-500/15 px-2 py-0.5 text-[11px] font-semibold text-violet-300 ring-1 ring-violet-500/40">
              <ShieldQuestion size={12} aria-hidden="true" /> approval required
            </span>
          )}
          {isFallback && (
            <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-semibold text-amber-300 ring-1 ring-amber-500/40">
              offline fallback &middot; LLM unavailable
            </span>
          )}
        </div>

        <Field label="Summary">{answer.summary}</Field>
        <Field label="Root cause">{answer.root_cause}</Field>
        <Field label="Affected component">
          <span className="font-mono text-sky-300">{answer.affected_component}</span>
        </Field>
        <Field label="Recommended action">
          <code className="rounded bg-slate-950 px-2 py-1 font-mono text-xs text-amber-300 ring-1 ring-slate-700">
            {answer.recommended_action}
          </code>
        </Field>

        {answer.evidence.length > 0 && (
          <div className="flex flex-wrap gap-1.5 border-t border-slate-800 pt-2">
            {answer.evidence.map((item, index) => (
              <CitationBadge key={index} source={item.source} snippet={item.snippet} score={item.score} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
