import { useState } from 'react'
import { Bot, Send, ServerCrash, ShieldQuestion, ThumbsDown, ThumbsUp } from 'lucide-react'
import { approveRecommendation, askCopilot, rejectRecommendation } from '../api/client'
import ConfidenceBadge from '../components/shared/ConfidenceBadge'
import CitationBadge from '../components/shared/CitationBadge'
import AlertBadge from '../components/shared/AlertBadge'

const SUGGESTIONS = [
  'Why is router-7 degraded?',
  'What is causing packet loss on the edge?',
  'Summarise the current network risk.',
]

function Field({ label, children }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wider text-slate-500">{label}</p>
      <div className="mt-1 text-sm text-slate-200">{children}</div>
    </div>
  )
}

export default function AICopilot() {
  const [question, setQuestion] = useState(SUGGESTIONS[0])
  const [answer, setAnswer] = useState(null)
  const [decision, setDecision] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const ask = async (text) => {
    setBusy(true)
    setError(null)
    setDecision(null)
    try {
      setAnswer(await askCopilot(text))
    } catch (err) {
      setAnswer(null)
      setError(`${err.code} - ${err.message}`)
    } finally {
      setBusy(false)
    }
  }

  const decide = async (kind) => {
    const call = kind === 'approve' ? approveRecommendation : rejectRecommendation
    try {
      const response = await call({ recommendation_id: 1, operator: 'demo_operator' })
      setDecision(`Recorded as "${response.status}" (audit log #${response.audit_log_id}).`)
    } catch (err) {
      setError(`${err.code} - ${err.message}`)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-bold text-slate-100">
          <Bot size={20} className="text-violet-400" aria-hidden="true" /> AI Copilot
          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-normal text-slate-400">
            stubbed response &middot; local RAG lands Day 2
          </span>
        </h2>
        <p className="text-xs text-slate-500">
          Every answer is produced inside the enclave and must be approved by a human before any action is taken.
        </p>
      </div>

      <section className="rounded-lg border border-slate-800 bg-slate-900 p-4">
        <form
          onSubmit={(event) => {
            event.preventDefault()
            ask(question)
          }}
          className="flex flex-col gap-2 sm:flex-row"
        >
          <input
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask about the current network state..."
            className="flex-1 rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none"
          />
          <button
            type="submit"
            disabled={busy || !question.trim()}
            className="inline-flex items-center justify-center gap-1.5 rounded-md bg-sky-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Send size={14} aria-hidden="true" /> {busy ? 'Thinking...' : 'Ask'}
          </button>
        </form>

        <div className="mt-2 flex flex-wrap gap-2">
          {SUGGESTIONS.map((text) => (
            <button
              key={text}
              type="button"
              onClick={() => {
                setQuestion(text)
                ask(text)
              }}
              className="rounded-full border border-slate-700 px-2.5 py-1 text-[11px] text-slate-400 hover:border-sky-600 hover:text-sky-300"
            >
              {text}
            </button>
          ))}
        </div>
      </section>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-3 text-xs text-red-300">
          <ServerCrash size={15} aria-hidden="true" /> {error}
        </div>
      )}

      {answer && (
        <section className="grid gap-4 lg:grid-cols-3">
          <div className="space-y-4 rounded-lg border border-slate-800 bg-slate-900 p-4 lg:col-span-2">
            <div className="flex flex-wrap items-center gap-2">
              <ConfidenceBadge value={answer.confidence} />
              <AlertBadge
                level={answer.risk >= 0.7 ? 'critical' : answer.risk >= 0.4 ? 'warning' : 'low'}
                label={`risk ${Math.round(answer.risk * 100)}%`}
              />
              {answer.requires_human_approval && (
                <span className="inline-flex items-center gap-1 rounded-full bg-violet-500/15 px-2.5 py-1 text-xs font-semibold text-violet-300 ring-1 ring-violet-500/40">
                  <ShieldQuestion size={13} aria-hidden="true" /> human approval required
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

            <div className="flex flex-wrap items-center gap-2 border-t border-slate-800 pt-3">
              <button
                type="button"
                onClick={() => decide('approve')}
                className="inline-flex items-center gap-1.5 rounded-md bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-emerald-400"
              >
                <ThumbsUp size={13} aria-hidden="true" /> Approve
              </button>
              <button
                type="button"
                onClick={() => decide('reject')}
                className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-800"
              >
                <ThumbsDown size={13} aria-hidden="true" /> Reject
              </button>
              {decision && <span className="text-xs text-emerald-300">{decision}</span>}
            </div>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
            <h3 className="text-sm font-semibold text-slate-200">Evidence</h3>
            <p className="mt-0.5 text-[11px] text-slate-500">Retrieved from the local knowledge base.</p>
            <div className="mt-3 space-y-2">
              {answer.evidence.length === 0 ? (
                <p className="text-xs text-slate-500">No citations returned.</p>
              ) : (
                answer.evidence.map((item, index) => (
                  <CitationBadge key={index} source={item.source} snippet={item.snippet} score={item.score} />
                ))
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  )
}
