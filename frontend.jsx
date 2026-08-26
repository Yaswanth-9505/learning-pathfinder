import { useCallback, useEffect, useState } from 'react'
import {
  Brain, LayoutDashboard, Loader2, MessageSquare, Route, Sparkles, UserCog, X,
} from 'lucide-react'
import { api } from './api'
import Onboarding from './components/Onboarding'
import PathView from './components/PathView'
import Dashboard from './components/Dashboard'
import ChatAssistant from './components/ChatAssistant'

const LEARNER_KEY = 'pathfinder.learnerId'

const TABS = [
  { key: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { key: 'path', label: 'My path', icon: Route },
  { key: 'chat', label: 'Assistant', icon: MessageSquare },
]

function Toast({ message, onClose }) {
  useEffect(() => {
    const t = setTimeout(onClose, 4000)
    return () => clearTimeout(t)
  }, [message, onClose])

  return (
    <div className="fixed bottom-5 right-5 z-50 bg-slate-800 border border-slate-600 text-slate-100 text-sm rounded-xl px-4 py-3 shadow-xl flex items-center gap-3 max-w-sm">
      <Sparkles className="w-4 h-4 text-blue-400 shrink-0" />
      <span>{message}</span>
      <button onClick={onClose} className="text-slate-500 hover:text-white">
        <X className="w-4 h-4" />
      </button>
    </div>
  )
}

export default function LearningPathfinder() {
  const [learner, setLearner] = useState(null)
  const [path, setPath] = useState(null)
  const [dashboard, setDashboard] = useState(null)
  const [tab, setTab] = useState('dashboard')
  const [booting, setBooting] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')

  const loadAll = useCallback(async (id) => {
    const [dash, pathResult] = await Promise.all([
      api.getDashboard(id),
      api.getPath(id).catch(() => null), // 404 before the first path exists
    ])
    setDashboard(dash)
    setPath(pathResult)
    return dash
  }, [])

  // Restore the session so a refresh no longer wipes everything.
  useEffect(() => {
    const stored = localStorage.getItem(LEARNER_KEY)
    if (!stored) {
      setBooting(false)
      return
    }
    api
      .getLearner(stored)
      .then(async (l) => {
        setLearner(l)
        await loadAll(l.id)
      })
      .catch(() => localStorage.removeItem(LEARNER_KEY))
      .finally(() => setBooting(false))
  }, [loadAll])

  const onReady = async (newLearner) => {
    localStorage.setItem(LEARNER_KEY, String(newLearner.id))
    setLearner(newLearner)
    await loadAll(newLearner.id)
    setTab('path')
  }

  const generate = async () => {
    setGenerating(true)
    setError('')
    try {
      const result = await api.generatePath(learner.id)
      setPath(result)
      setDashboard(await api.getDashboard(learner.id))
      setTab('path')
      setToast('Your personalised path is ready.')
    } catch (err) {
      setError(err.message)
    } finally {
      setGenerating(false)
    }
  }

  const onPathRefresh = async (updated) => {
    setPath(updated)
    setDashboard(await api.getDashboard(learner.id))
  }

  const refreshSkills = async () => {
    setDashboard(await api.getDashboard(learner.id))
  }

  const reset = () => {
    localStorage.removeItem(LEARNER_KEY)
    setLearner(null)
    setPath(null)
    setDashboard(null)
    setTab('dashboard')
  }

  if (booting) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <Loader2 className="w-6 h-6 text-slate-500 animate-spin" />
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-900 to-slate-950">
      <header className="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-40">
        <div className="max-w-5xl mx-auto px-5 py-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-600 to-purple-600 flex items-center justify-center">
              <Brain className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-white leading-tight">
                Learning Pathfinder
              </h1>
              <p className="text-[11px] text-slate-500">
                AI-personalised learning paths
              </p>
            </div>
          </div>

          {learner && (
            <div className="flex items-center gap-3">
              <div className="text-right hidden sm:block">
                <p className="text-sm text-white leading-tight">{learner.name}</p>
                <p className="text-[11px] text-slate-500 truncate max-w-[180px]">
                  {learner.goals}
                </p>
              </div>
              <button
                onClick={reset}
                title="Start over with a new profile"
                className="text-slate-500 hover:text-white p-2 rounded-lg hover:bg-slate-800 transition-colors"
              >
                <UserCog className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>

        {learner && (
          <div className="max-w-5xl mx-auto px-5 flex gap-1">
            {TABS.map(({ key, label, icon: Icon }) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={`flex items-center gap-2 px-4 py-2.5 text-sm border-b-2 transition-colors ${
                  tab === key
                    ? 'border-blue-500 text-white'
                    : 'border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                <Icon className="w-4 h-4" />
                {label}
              </button>
            ))}
          </div>
        )}
      </header>

      <main className="px-5 py-8">
        {!learner ? (
          <Onboarding onReady={onReady} />
        ) : (
          <>
            {error && (
              <div className="max-w-3xl mx-auto mb-5 text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3">
                {error}
              </div>
            )}

            {tab === 'dashboard' && dashboard && (
              <Dashboard
                data={dashboard}
                onGoToPath={() => (path ? setTab('path') : generate())}
                onRefreshSkills={refreshSkills}
              />
            )}

            {tab === 'path' &&
              (path ? (
                <PathView
                  path={path}
                  learnerId={learner.id}
                  onRefresh={onPathRefresh}
                  onNotify={setToast}
                />
              ) : (
                <div className="max-w-2xl mx-auto bg-slate-800 border border-slate-700 rounded-2xl p-10 text-center">
                  <Route className="w-10 h-10 text-slate-500 mx-auto mb-3" />
                  <h3 className="text-lg font-semibold text-white mb-1">
                    Ready to build your roadmap
                  </h3>
                  <p className="text-slate-400 text-sm mb-6">
                    We'll match {learner.name} against the course catalog, work out
                    the skill gaps for your goal, and sequence a path that closes them.
                  </p>
                  <button
                    onClick={generate}
                    disabled={generating}
                    className="bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 disabled:opacity-50 text-white font-semibold px-6 py-3 rounded-lg inline-flex items-center gap-2 transition-colors"
                  >
                    {generating ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" /> Building your path...
                      </>
                    ) : (
                      <>
                        <Sparkles className="w-4 h-4" /> Generate my learning path
                      </>
                    )}
                  </button>
                </div>
              ))}

            {tab === 'chat' && <ChatAssistant learnerId={learner.id} />}
          </>
        )}
      </main>

      {toast && <Toast message={toast} onClose={() => setToast('')} />}
    </div>
  )
}
