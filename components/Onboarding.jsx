import { useState } from 'react'
import { Sparkles, Send, Loader2, Pencil, Target } from 'lucide-react'
import { api } from '../api'

const EXAMPLES = [
  "I'm a final-year CS student. I know basic Python and SQL and want to become a backend engineer. I can study ~10 hours a week and learn best by building things.",
  "I work in marketing and want to move into data analysis. I'm comfortable with Excel but have never coded. Maybe 5 hours a week.",
  "I've been writing React for a year and want to go full stack, ideally with Node. I have about 12 hours a week.",
]

/**
 * Conversational intake: the learner describes their goal in natural language
 * and the LLM extracts a structured profile, which they can then correct.
 */
export default function Onboarding({ onReady }) {
  const [text, setText] = useState('')
  const [stage, setStage] = useState('describe') // describe | review
  const [profile, setProfile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const describe = async () => {
    if (text.trim().length < 10) {
      setError('Tell me a little more — a sentence or two about your goal.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const result = await api.extractProfile(text)
      setProfile(result.profile)
      setPreview(result.skill_gap_preview)
      setStage('review')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const confirm = async () => {
    setBusy(true)
    setError('')
    try {
      const { followup, ...clean } = profile
      const learner = await api.createLearner({
        ...clean,
        name: clean.name || 'Learner',
      })
      onReady(learner)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  const field = (key, label, type = 'text') => (
    <div>
      <label className="block text-xs font-medium text-slate-400 mb-1">{label}</label>
      <input
        type={type}
        value={profile[key] ?? ''}
        onChange={(e) =>
          setProfile({
            ...profile,
            [key]: type === 'number' ? Number(e.target.value) : e.target.value,
          })
        }
        className="w-full bg-slate-900 text-white px-3 py-2 rounded-lg border border-slate-700 focus:border-blue-500 focus:outline-none text-sm"
      />
    </div>
  )

  if (stage === 'review' && profile) {
    return (
      <div className="max-w-3xl mx-auto">
        <div className="bg-slate-800 rounded-2xl border border-slate-700 p-8">
          <div className="flex items-center gap-3 mb-2">
            <Pencil className="w-5 h-5 text-blue-400" />
            <h2 className="text-2xl font-bold text-white">Here's what I understood</h2>
          </div>
          <p className="text-slate-400 text-sm mb-6">
            Correct anything I got wrong before we build your roadmap.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
            {field('name', 'Name')}
            {field('goals', 'Goal')}
            {field('interests', 'Interests')}
            {field('completed_learning', 'Already know')}
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">
                Experience level
              </label>
              <select
                value={profile.experience_level}
                onChange={(e) =>
                  setProfile({ ...profile, experience_level: e.target.value })
                }
                className="w-full bg-slate-900 text-white px-3 py-2 rounded-lg border border-slate-700 focus:border-blue-500 focus:outline-none text-sm"
              >
                <option value="beginner">beginner</option>
                <option value="intermediate">intermediate</option>
                <option value="advanced">advanced</option>
              </select>
            </div>
            {field('weekly_hours', 'Hours per week', 'number')}
          </div>

          {preview?.role && (
            <div className="bg-slate-900/70 rounded-xl p-4 mb-6 border border-slate-700">
              <div className="flex items-center gap-2 mb-2">
                <Target className="w-4 h-4 text-purple-400" />
                <span className="text-sm text-white font-semibold">
                  Matched to: {preview.role}
                </span>
                <span className="text-xs text-slate-400">
                  {preview.coverage_percent}% of required skills already covered
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {preview.missing_skills.slice(0, 10).map((s) => (
                  <span
                    key={s}
                    className="text-[11px] bg-amber-500/10 text-amber-300 border border-amber-500/30 px-2 py-0.5 rounded"
                  >
                    {s}
                  </span>
                ))}
              </div>
              <p className="text-xs text-slate-500 mt-2">
                These are the gaps your path will close.
              </p>
            </div>
          )}

          {profile.followup && (
            <p className="text-sm text-blue-300 bg-blue-500/10 border border-blue-500/25 rounded-lg px-4 py-3 mb-6">
              {profile.followup}
            </p>
          )}

          {error && <p className="text-sm text-red-400 mb-4">{error}</p>}

          <div className="flex gap-3">
            <button
              onClick={confirm}
              disabled={busy}
              className="flex-1 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 disabled:opacity-50 text-white font-semibold py-3 rounded-lg transition-colors flex items-center justify-center gap-2"
            >
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
              Looks right — continue
            </button>
            <button
              onClick={() => setStage('describe')}
              disabled={busy}
              className="px-5 py-3 rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-700 transition-colors"
            >
              Start over
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="bg-slate-800 rounded-2xl border border-slate-700 p-8">
        <div className="flex items-center gap-3 mb-2">
          <Sparkles className="w-6 h-6 text-blue-400" />
          <h2 className="text-2xl font-bold text-white">What do you want to learn?</h2>
        </div>
        <p className="text-slate-400 mb-6">
          Describe your goal in your own words — where you are now, where you want to
          get to, and how much time you have.
        </p>

        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={5}
          placeholder="I'm a CS student who knows some Python. I want to become a backend engineer..."
          className="w-full bg-slate-900 text-white px-4 py-3 rounded-xl border border-slate-700 focus:border-blue-500 focus:outline-none resize-none mb-3"
        />

        <div className="mb-6">
          <p className="text-xs text-slate-500 mb-2">Or try one of these:</p>
          <div className="space-y-1.5">
            {EXAMPLES.map((ex, i) => (
              <button
                key={i}
                onClick={() => setText(ex)}
                className="block w-full text-left text-xs text-slate-400 hover:text-blue-300 bg-slate-900/50 hover:bg-slate-900 border border-slate-700/60 rounded-lg px-3 py-2 transition-colors"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>

        {error && <p className="text-sm text-red-400 mb-4">{error}</p>}

        <button
          onClick={describe}
          disabled={busy}
          className="w-full bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 disabled:opacity-50 text-white font-semibold py-3 rounded-lg transition-colors flex items-center justify-center gap-2"
        >
          {busy ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" /> Understanding your goal...
            </>
          ) : (
            <>
              <Send className="w-4 h-4" /> Continue
            </>
          )}
        </button>
      </div>
    </div>
  )
}
