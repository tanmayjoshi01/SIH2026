import { FileText } from 'lucide-react'

/**
 * One retrieved evidence citation. Day 2 swaps the stub evidence array
 * for real RAG hits without changing these props.
 */
export default function CitationBadge({ source, snippet, score }) {
  return (
    <div className="rounded-md border border-slate-700 bg-slate-900/60 p-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-sky-300">
          <FileText size={13} aria-hidden="true" />
          {source}
        </span>
        {Number.isFinite(score) && (
          <span className="font-mono text-[11px] text-slate-400">match {score.toFixed(2)}</span>
        )}
      </div>
      {snippet && <p className="mt-1.5 text-xs leading-relaxed text-slate-400">{snippet}</p>}
    </div>
  )
}
