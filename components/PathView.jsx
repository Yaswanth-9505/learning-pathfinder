import { useCallback, useEffect, useState } from 'react'
import {
  CheckCircle2, Circle, ExternalLink, Lightbulb, Loader2, RefreshCw,
  ChevronDown, ChevronRight, Flag, Hammer, ThumbsUp, TrendingDown,
  TrendingUp, XCircle, Clock,
} from 'lucide-react'
import { api } from '../api'
import Assessment from './Assessment'

const SIGNALS = [
  { key: 'helpful', label: 'Helpful', icon: ThumbsUp, tone: 'text-emerald-300 border-emerald-500/40 hover:bg-emerald-500/10' },
  { key: 'too_hard', label: 'Too hard', icon: TrendingUp, tone: 'text-amber-300 border-amber-500/40 hover:bg-amber-500/10' },
  { key: 'too_easy', label: 'Too easy', icon: TrendingDown, tone: 'text-sky-300 border-sky-500/40 hover:bg-sky-500/10' },
  { key: 'not_relevant', label: 'Not relevant', icon: XCircle, tone: 'text-rose-300 border-rose-500/40 hover:bg-rose-500/10' },
]

function CourseCard({ course, learnerId, onToggle, onFeedback }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(null)

  const toggle = async () => {
    setBusy(true)
    try {
      await onToggle(course.path_course_id, !course.completed)
    } finally {
      setBusy(false)
    }
  }

  const rate = async (signal) => {
    setSent(signal)
    await onFeedback(signal, course.course_id)
  }

  return (
    <div
      className={`rounded-xl border transition-colors ${
        course.completed
          ? 'bg-emerald-500/5 border-emerald-500/30'
          : 'bg-slate-800 border-slate-700 hover:border-slate-600'
      }`}
    >
      <div className="p-5">
        <div className="flex items-start gap-4">
          <button
            onClick={toggle}
            disabled={busy}
            title={course.completed ? 'Mark as not done' : 'Mark as complete'}
            className="mt-0.5 shrink-0 disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="w-6 h-6 text-slate-400 animate-spin" />
            ) : course.completed ? (
              <CheckCircle2 className="w-6 h-6 text-emerald-400" />
            ) : (
              <Circle className="w-6 h-6 text-slate-500 hover:text-blue-400" />
            )}
          </button>

          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <span className="text-xs text-slate-500 font-mono">
                  Step {course.position + 1}
                </span>
                <h3
                  className={`text-lg font-semibold leading-snug ${
                    course.completed ? 'text-emerald-200 line-through' : 'text-white'
                  }`}
                >
                  {course.title}
                </h3>
                <p className="text-sm text-slate-400 mt-0.5">
                  {course.provider} &middot; {course.level} &middot;{' '}
                  <Clock className="w-3 h-3 inline -mt-0.5" /> {course.hours}h
                </p>
              </div>
              <a
                href={course.url}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1 border border-blue-500/30 rounded-lg px-2.5 py-1.5 hover:bg-blue-500/10 transition-colors"
              >
                Open <ExternalLink className="w-3 h-3" />
              </a>
            </div>

            {/* The explanation is the core deliverable: why THIS course, for THIS learner. */}
            {course.reason && (
              <div className="mt-3 flex gap-2 bg-blue-500/5 border border-blue-500/20 rounded-lg p-3">
                <Lightbulb className="w-4 h-4 text-blue-400 shrink-0 mt-0.5" />
                <p className="text-sm text-blue-100/90 leading-relaxed">{course.reason}</p>
              </div>
            )}

            {course.targets_skills?.length > 0 && (
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] text-slate-500">closes gap:</span>
                {course.targets_skills.map((s) => (
                  <span
                    key={s}
                    className="text-[11px] bg-purple-500/10 text-purple-300 border border-purple-500/30 px-2 py-0.5 rounded"
                  >
                    {s}
                  </span>
                ))}
              </div>
            )}

            <button
              onClick={() => setOpen(!open)}
              className="mt-3 text-xs text-slate-400 hover:text-white flex items-center gap-1"
            >
              {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
              {open ? 'Hide details' : 'Details, project & feedback'}
            </button>

            {open && (
              <div className="mt-3 space-y-3 border-t border-slate-700 pt-3">
                <p className="text-sm text-slate-300">{course.description}</p>

                {course.prerequisites?.length > 0 && (
                  <p className="text-xs text-slate-400">
                    <span className="text-slate-500">Builds on: </span>
                    {course.prerequisites.join(', ')}
                  </p>
                )}

                {course.project && (
                  <div className="flex gap-2 bg-slate-900/60 border border-slate-700 rounded-lg p-3">
                    <Hammer className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs text-amber-300 font-semibold mb-0.5">
                        Project to prove it
                      </p>
                      <p className="text-sm text-slate-300">{course.project}</p>
                    </div>
                  </div>
                )}

                <div className="flex flex-wrap gap-1.5">
                  {course.skills.map((s) => (
                    <span
                      key={s}
                      className="text-[11px] bg-slate-700/60 text-slate-300 px-2 py-0.5 rounded"
                    >
                      {s}
                    </span>
                  ))}
                </div>

                <div>
                  <p className="text-xs text-slate-500 mb-1.5">
                    How is this course working for you? Feedback reshapes your next path.
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {SIGNALS.map(({ key, label, icon: Icon, tone }) => (
                      <button
                        key={key}
                        onClick={() => rate(key)}
                        disabled={sent === key}
                        className={`text-xs flex items-center gap-1.5 border rounded-lg px-2.5 py-1.5 transition-colors disabled:opacity-100 disabled:bg-slate-700 ${tone}`}
                      >
                        <Icon className="w-3.5 h-3.5" />
                        {sent === key ? 'Recorded' : label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default function PathView({ path, learnerId, onRefresh, onNotify }) {
  const [assessments, setAssessments] = useState([])
  const [adapting, setAdapting] = useState(false)
  const [note, setNote] = useState('')
  const [showAdapt, setShowAdapt] = useState(false)
  const [error, setError] = useState('')

  const loadAssessments = useCallback(async () => {
    try {
      const r = await api.listAssessments(learnerId)
      setAssessments(r.assessments)
    } catch {
      setAssessments([])
    }
  }, [learnerId])

  // Completing a course can unlock a checkpoint, so keep them in step.
  useEffect(() => {
    loadAssessments()
  }, [loadAssessments, path.path_id, path.completed_count])

  const toggleCourse = async (pathCourseId, completed) => {
    try {
      const updated = await api.completeCourse(pathCourseId, completed)
      onRefresh(updated)
    } catch (err) {
      setError(err.message)
    }
  }

  const sendFeedback = async (signal, courseId) => {
    try {
      await api.sendFeedback(learnerId, signal, courseId, '')
      onNotify?.('Feedback recorded — use "Adapt path" to rebuild around it.')
    } catch (err) {
      setError(err.message)
    }
  }

  const adapt = async () => {
    setAdapting(true)
    setError('')
    try {
      const updated = await api.adaptPath(learnerId, note)
      onRefresh(updated)
      setShowAdapt(false)
      setNote('')
      onNotify?.(`Path rebuilt as version ${updated.version}.`)
    } catch (err) {
      setError(err.message)
    } finally {
      setAdapting(false)
    }
  }

  // Group courses under their milestone so the roadmap reads as stages.
  const groups = path.milestones.map((name, i) => ({
    name,
    index: i,
    courses: path.courses.filter((c) => c.milestone_index === i),
  }))
  const ungrouped = path.courses.filter(
    (c) => c.milestone_index >= path.milestones.length
  )
  if (ungrouped.length) {
    groups.push({ name: 'Further work', index: groups.length, courses: ungrouped })
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div className="bg-gradient-to-r from-slate-800 to-slate-800/50 rounded-2xl border border-slate-700 p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <h2 className="text-2xl font-bold text-white">{path.path_name}</h2>
              <span className="text-[11px] bg-slate-700 text-slate-300 px-2 py-0.5 rounded font-mono">
                v{path.version}
              </span>
            </div>
            {path.target_role && (
              <p className="text-sm text-purple-300 mb-2">Target role: {path.target_role}</p>
            )}
            <p className="text-slate-300 text-sm max-w-2xl">{path.description}</p>
          </div>
          <button
            onClick={() => setShowAdapt(!showAdapt)}
            className="shrink-0 text-sm flex items-center gap-2 border border-slate-600 text-slate-200 rounded-lg px-3 py-2 hover:bg-slate-700 transition-colors"
          >
            <RefreshCw className="w-4 h-4" /> Adapt path
          </button>
        </div>

        {path.adaptation_note && (
          <p className="mt-3 text-xs text-slate-400 italic border-l-2 border-slate-600 pl-3">
            {path.adaptation_note}
          </p>
        )}

        <div className="mt-5">
          <div className="flex justify-between text-xs text-slate-400 mb-1.5">
            <span>
              {path.completed_count} of {path.course_count} courses &middot;{' '}
              {path.completed_hours}h of {path.total_hours}h
            </span>
            <span className="text-white font-semibold">{path.progress_percent}%</span>
          </div>
          <div className="h-2 bg-slate-900 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-blue-500 to-emerald-500 transition-all duration-500"
              style={{ width: `${path.progress_percent}%` }}
            />
          </div>
        </div>

        {showAdapt && (
          <div className="mt-5 bg-slate-900/70 border border-slate-700 rounded-xl p-4">
            <p className="text-sm text-white font-medium mb-1">Rebuild this path</p>
            <p className="text-xs text-slate-400 mb-3">
              Your recorded feedback and completed courses are taken into account.
              Add anything else you want changed.
            </p>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="e.g. keep it practical, less theory, focus on APIs"
              className="w-full bg-slate-900 text-white text-sm px-3 py-2 rounded-lg border border-slate-700 focus:border-blue-500 focus:outline-none mb-3"
            />
            <button
              onClick={adapt}
              disabled={adapting}
              className="text-sm bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 disabled:opacity-50 text-white font-medium px-4 py-2 rounded-lg flex items-center gap-2 transition-colors"
            >
              {adapting ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
              {adapting ? 'Rebuilding...' : 'Rebuild path'}
            </button>
          </div>
        )}

        {path.career_outcome && (
          <p className="mt-5 text-sm text-emerald-300 bg-emerald-500/5 border border-emerald-500/20 rounded-lg px-4 py-3">
            <span className="font-semibold">Outcome: </span>
            {path.career_outcome}
          </p>
        )}
      </div>

      {error && (
        <p className="text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3">
          {error}
        </p>
      )}

      {groups.map((group) =>
        group.courses.length === 0 ? null : (
          <div key={group.index}>
            <div className="flex items-center gap-2 mb-3">
              <Flag className="w-4 h-4 text-purple-400" />
              <h3 className="text-sm font-semibold text-purple-300 uppercase tracking-wide">
                {group.name}
              </h3>
              <span className="text-xs text-slate-500">
                {group.courses.filter((c) => c.completed).length}/{group.courses.length}
              </span>
              <div className="flex-1 h-px bg-slate-700" />
            </div>
            <div className="space-y-3">
              {group.courses.map((course) => (
                <CourseCard
                  key={course.path_course_id}
                  course={course}
                  learnerId={learnerId}
                  onToggle={toggleCourse}
                  onFeedback={sendFeedback}
                />
              ))}
              {assessments[group.index] && (
                <Assessment
                  status={assessments[group.index]}
                  learnerId={learnerId}
                  onPassed={async (r) => {
                    onNotify?.(
                      `Checkpoint passed at ${r.percent}% - ${r.skills_credited.length} skills credited.`
                    )
                    await loadAssessments()
                    onRefresh(await api.getPath(learnerId))
                  }}
                />
              )}
            </div>
          </div>
        )
      )}
    </div>
  )
}
