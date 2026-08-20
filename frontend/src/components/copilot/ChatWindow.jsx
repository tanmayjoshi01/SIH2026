import { Bot, ShieldQuestion, ThumbsDown, ThumbsUp } from 'lucide-react'
import MessageBubble from './MessageBubble'

/**
 * Scrollable message list plus the approve/reject action row for the
 * most recent assistant answer. `busy` renders a "Thinking locally..."
 * bubble so the wait for gemma3:4b is never silent.
 */
export default function ChatWindow({ messages, busy, onApprove, onReject, decision }) {
  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant' && m.answer)

  return (
    <div className="flex flex-col rounded-lg border border-slate-800 bg-slate-900 p-4">
      <div className="flex max-h-[28rem] min-h-[10rem] flex-col gap-3 overflow-y-auto pr-1">
        {messages.length === 0 && !busy && (
          <p className="text-xs text-slate-500">
            Ask a question, or pick a suggestion below, to query the local copilot.
          </p>
        )}
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}
        {busy && (
          <div className="flex items-center gap-2 self-start rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs text-slate-400">
            <Bot size={14} className="animate-pulse text-violet-400" aria-hidden="true" />
            Thinking locally...
          </div>
        )}
      </div>

      {lastAssistant?.answer?.requires_human_approval && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-800 pt-3">
          <ShieldQuestion size={14} className="text-violet-400" aria-hidden="true" />
          <span className="text-xs text-slate-400">This recommendation needs human approval:</span>
          <button
            type="button"
            onClick={onApprove}
            className="inline-flex items-center gap-1.5 rounded-md bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-slate-950 hover:bg-emerald-400"
          >
            <ThumbsUp size={13} aria-hidden="true" /> Approve
          </button>
          <button
            type="button"
            onClick={onReject}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:bg-slate-800"
          >
            <ThumbsDown size={13} aria-hidden="true" /> Reject
          </button>
          {decision && <span className="text-xs text-emerald-300">{decision}</span>}
        </div>
      )}
    </div>
  )
}
