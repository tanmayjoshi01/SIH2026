import { createContext, useContext, useRef, useState } from 'react'

const CopilotSessionContext = createContext(null)

/**
 * Copilot chat state lifted above the router so it survives navigating
 * away from and back to the AI Copilot page. React Router unmounts page
 * components on route change -- AICopilot.jsx previously held messages,
 * session_id, busy, and decision as local state/refs, so leaving the page
 * and coming back reset the whole conversation. Worse, a fresh session_id
 * on remount meant backend/routers/copilot.py's bounded 4-turn memory
 * silently reset too, even though nothing about the underlying incident
 * had changed.
 *
 * Deliberately plain useState/useRef, not localStorage/sessionStorage --
 * a full page reload is still meant to start a fresh conversation; only
 * client-side navigation (which never re-executes this module) should
 * survive.
 */
export function CopilotSessionProvider({ children }) {
  const [messages, setMessages] = useState([])
  const [busy, setBusy] = useState(false)
  const [decision, setDecision] = useState(null)
  const sessionIdRef = useRef(null)
  if (sessionIdRef.current === null) {
    sessionIdRef.current = `copilot-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  }

  const value = {
    messages,
    setMessages,
    busy,
    setBusy,
    decision,
    setDecision,
    sessionId: sessionIdRef.current,
  }

  return <CopilotSessionContext.Provider value={value}>{children}</CopilotSessionContext.Provider>
}

export function useCopilotSession() {
  const ctx = useContext(CopilotSessionContext)
  if (!ctx) {
    throw new Error('useCopilotSession must be used within a CopilotSessionProvider')
  }
  return ctx
}
