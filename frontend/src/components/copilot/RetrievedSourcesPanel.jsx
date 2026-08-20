import { BookOpen } from 'lucide-react'
import CitationBadge from '../shared/CitationBadge'

/** Side panel listing every runbook chunk retrieved for the latest answer, independent of the citations shown inline in the chat bubble. */
export default function RetrievedSourcesPanel({ evidence }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900 p-4">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-slate-200">
        <BookOpen size={14} className="text-sky-400" aria-hidden="true" /> Retrieved Sources
      </h3>
      <p className="mt-0.5 text-[11px] text-slate-500">Top runbook chunks retrieved from the local knowledge base.</p>
      <div className="mt-3 space-y-2">
        {evidence.length === 0 ? (
          <p className="text-xs text-slate-500">No citations yet &mdash; ask a question to query the local runbooks.</p>
        ) : (
          evidence.map((item, index) => (
            <CitationBadge key={index} source={item.source} snippet={item.snippet} score={item.score} />
          ))
        )}
      </div>
    </div>
  )
}
