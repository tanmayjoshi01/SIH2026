import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Sidebar from './components/shared/Sidebar'
import TopHeaderBar from './components/shared/TopHeaderBar'
import LiveMonitoring from './pages/LiveMonitoring'
import AICopilot from './pages/AICopilot'
import AuditTrail from './pages/AuditTrail'

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex min-h-screen bg-slate-950 text-slate-200">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopHeaderBar />
          <main className="flex-1 overflow-y-auto p-5">
            <Routes>
              <Route path="/" element={<LiveMonitoring />} />
              <Route path="/copilot" element={<AICopilot />} />
              <Route path="/audit" element={<AuditTrail />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </main>
        </div>
      </div>
    </BrowserRouter>
  )
}
