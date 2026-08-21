import { useState } from 'react'
import { Bot, Send } from 'lucide-react'
import { approveRecommendation, askCopilot, rejectRecommendation } from '../api/client'
import ChatWindow from '../components/copilot/ChatWindow'
import RetrievedSourcesPanel from '../components/copilot/RetrievedSourcesPanel'
import IncidentContextPanel from '../components/copilot/IncidentContextPanel'
import { useCopilotSession } from '../context/CopilotSessionContext'

const SUGGESTIONS = [
  'Why is router-7 at risk?',
  'What is causing packet loss on the edge?',
  'Summarise the current network risk.',
]

export default function AICopilot() {
  // Lifted into CopilotSessionContext (mounted above the router in
  // App.jsx) so the conversation and session_id survive navigating away
  // from and back to this page -- only local to this component is the
  // in-progress text of the input box, which resetting on navigation is
  // fine (and arguably expected).
  const { messages, setMessages, busy, setBusy, decision, setDecision, sessionId } = useCopilotSession()
  const [question, setQuestion] = useState('')

  const ask = async (text) => {
    const trimmed = text.trim()
    if (!trimmed || busy) return
    setBusy(true)
    setDecision(null)
    setMessages((prev) => [...prev, { role: 'user', text: trimmed, id: `u-${Date.now()}` }])
    try {
      const answer = await askCopilot(trimmed, sessionId)
      setMessages((prev) => [...prev, { role: 'assistant', answer, id: `a-${Date.now()}` }])
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'assistant', error: `${err.code} - ${err.message}`, id: `e-${Date.now()}` }])
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
      setDecision(`${err.code} - ${err.message}`)
    }
  }

  const latestAnswer = [...messages].reverse().find((m) => m.role === 'assistant' && m.answer)?.answer

  return (
    <div className="space-y-4">
      <div>
        <h2 className="flex items-center gap-2 text-lg font-bold text-slate-100">
          <Bot size={20} className="text-violet-400" aria-hidden="true" /> AI Copilot
        </h2>
        <p className="text-xs text-slate-500">
          Every answer is produced inside the enclave by a local model (gemma3:4b via Ollama), grounded in retrieved
          runbooks, and must be approved by a human before any action is taken.
        </p>
      </div>

      <section className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          {latestAnswer?.affected_node && <IncidentContextPanel nodeId={latestAnswer.affected_node} />}

          <ChatWindow
            messages={messages}
            busy={busy}
            onApprove={() => decide('approve')}
            onReject={() => decide('reject')}
            decision={decision}
          />

          <form
            onSubmit={(event) => {
              event.preventDefault()
              ask(question)
              setQuestion('')
            }}
            className="flex flex-col gap-2 rounded-lg border border-slate-800 bg-slate-900 p-3 sm:flex-row"
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
              <Send size={14} aria-hidden="true" /> {busy ? 'Thinking locally...' : 'Ask'}
            </button>
          </form>

          <div className="flex flex-wrap gap-2">
            {SUGGESTIONS.map((text) => (
              <button
                key={text}
                type="button"
                disabled={busy}
                onClick={() => ask(text)}
                className="rounded-full border border-slate-700 px-2.5 py-1 text-[11px] text-slate-400 hover:border-sky-600 hover:text-sky-300 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {text}
              </button>
            ))}
          </div>
        </div>

        <RetrievedSourcesPanel evidence={latestAnswer?.evidence ?? []} busy={busy} />
      </section>
    </div>
  )
}
