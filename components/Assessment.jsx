import { useState } from 'react'
import {
  Award, CheckCircle2, ClipboardCheck, Loader2, Lock, RotateCcw, XCircle,
} from 'lucide-react'
import { api } from '../api'

const LETTER = ['A', 'B', 'C', 'D']

/**
 * Milestone checkpoint. Unlocks only once every course in the stage is done,
 * and skills are credited on a pass — evidence rather than a self-ticked box.
 */
export default function Assessment({ status, learnerId, onPassed }) {
  const [stage, setStage] = useState('idle') // idle | taking | done
  const [quiz, setQuiz] = useState(null)
  const [answers, setAnswers] = useState([])
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const start = async (regenerate = false) => {
    setBusy(true)
    setError('')
    try {
      const data = await api.getAssessment(learnerId, status.milestone_index, regenerate)
      setQuiz(data)
      setAnswers(new Array(data.questions.length).fill(-1))
      setResult(null)
      setStage('taking')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const submit = async () => {
    setBusy(true)
    setError('')
    try {
      const data = await api.submitAssessment(quiz.assessment_id, answers)
      setResult(data)
      setStage('done')
      if (data.passed) onPassed?.(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const answered = answers.filter((a) => a >= 0).length

  // ---- locked ----
  if (!status.unlocked && stage === 'idle') {
    return (
      <div className="flex items-center gap-2.5 text-xs text-slate-500 bg-slate-900/40 border border-slate-800 border-dashed rounded-lg px-3.5 py-2.5">
        <Lock className="w-3.5 h-3.5 shrink-0" />
        <span>
          Checkpoint unlocks when all {status.courses_total} courses in this stage
          are done ({status.courses_completed}/{status.courses_total}).
        </span>
      </div>
    )
  }

  // ---- results ----
  if (stage === 'done' && result) {
    return (
      <div
        className={`rounded-xl border p-4 ${
          result.passed
            ? 'bg-emerald-500/5 border-emerald-500/30'
            : 'bg-amber-500/5 border-amber-500/30'
        }`}
      >
        <div className="flex items-center gap-2.5 mb-3">
          {result.passed ? (
            <Award className="w-5 h-5 text-emerald-400" />
          ) : (
            <RotateCcw className="w-5 h-5 text-amber-400" />
          )}
          <div>
            <p className="text-sm font-semibold text-white">
              {result.score}/{result.total} correct — {result.percent}%
            </p>
            <p className="text-xs text-slate-400">
              {result.passed
                ? 'Passed. Skills credited to your profile.'
                : `Needs ${result.pass_mark}% to pass. Review and try again.`}
            </p>
          </div>
        </div>

        {result.skills_credited.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-3">
            {result.skills_credited.map((s) => (
              <span
                key={s}
                className="text-[11px] bg-emerald-500/10 text-emerald-300 border border-emerald-500/30 px-2 py-0.5 rounded flex items-center gap-1"
              >
                <CheckCircle2 className="w-3 h-3" /> {s}
              </span>
            ))}
          </div>
        )}

        <div className="space-y-2 mb-3">
          {result.results.map((r, i) => (
            <div key={i} className="text-xs bg-slate-900/60 rounded-lg p-2.5">
              <div className="flex gap-2">
                {r.correct ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-0.5" />
                ) : (
                  <XCircle className="w-3.5 h-3.5 text-rose-400 shrink-0 mt-0.5" />
                )}
                <div className="min-w-0">
                  <p className="text-slate-300">{r.question}</p>
                  {!r.correct && (
                    <p className="text-slate-400 mt-1">
                      <span className="text-emerald-400">
                        Correct: {LETTER[r.correct_answer]}
                      </span>
                      {r.explains ? ` — ${r.explains}` : ''}
                    </p>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => start(false)}
            disabled={busy}
            className="text-xs border border-slate-600 text-slate-200 rounded-lg px-3 py-1.5 hover:bg-slate-700 transition-colors"
          >
            Retake
          </button>
          {!result.passed && (
            <button
              onClick={() => start(true)}
              disabled={busy}
              className="text-xs border border-slate-700 text-slate-400 rounded-lg px-3 py-1.5 hover:bg-slate-800 transition-colors"
            >
              New questions
            </button>
          )}
        </div>
      </div>
    )
  }

  // ---- taking ----
  if (stage === 'taking' && quiz) {
    return (
      <div className="bg-slate-900/60 border border-slate-700 rounded-xl p-4">
        <div className="flex items-center justify-between mb-4">
          <h4 className="text-sm font-semibold text-white flex items-center gap-2">
            <ClipboardCheck className="w-4 h-4 text-blue-400" />
            {quiz.title}
          </h4>
          <span className="text-xs text-slate-500 tabular-nums">
            {answered}/{quiz.questions.length} answered
          </span>
        </div>

        <div className="space-y-4">
          {quiz.questions.map((q, qi) => (
            <div key={qi}>
              <p className="text-sm text-slate-200 mb-2">
                <span className="text-slate-500 font-mono text-xs mr-1.5">
                  {qi + 1}.
                </span>
                {q.question}
              </p>
              <div className="space-y-1.5 pl-5">
                {q.options.map((opt, oi) => {
                  const selected = answers[qi] === oi
                  return (
                    <button
                      key={oi}
                      onClick={() => {
                        const next = [...answers]
                        next[qi] = oi
                        setAnswers(next)
                      }}
                      className={`w-full text-left text-xs rounded-lg px-3 py-2 border transition-colors flex gap-2 ${
                        selected
                          ? 'bg-blue-500/15 border-blue-500/50 text-white'
                          : 'bg-slate-800/60 border-slate-700 text-slate-300 hover:border-slate-600'
                      }`}
                    >
                      <span
                        className={`font-mono shrink-0 ${
                          selected ? 'text-blue-300' : 'text-slate-500'
                        }`}
                      >
                        {LETTER[oi]}
                      </span>
                      <span>{opt}</span>
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>

        {error && <p className="text-xs text-red-400 mt-3">{error}</p>}

        <button
          onClick={submit}
          disabled={busy || answered < quiz.questions.length}
          className="mt-4 w-full text-sm bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 disabled:opacity-40 text-white font-medium py-2.5 rounded-lg transition-colors flex items-center justify-center gap-2"
        >
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
          {answered < quiz.questions.length
            ? `Answer all ${quiz.questions.length} questions`
            : 'Submit checkpoint'}
        </button>
      </div>
    )
  }

  // ---- unlocked, not started ----
  return (
    <div className="bg-slate-900/50 border border-slate-700 rounded-xl p-3.5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2.5 min-w-0">
          <ClipboardCheck
            className={`w-4 h-4 shrink-0 ${
              status.passed ? 'text-emerald-400' : 'text-blue-400'
            }`}
          />
          <div className="min-w-0">
            <p className="text-sm text-white font-medium">
              {status.passed ? 'Checkpoint passed' : 'Stage checkpoint'}
            </p>
            <p className="text-xs text-slate-400">
              {status.passed
                ? `Best score ${status.best_percent}% — skills credited.`
                : status.best_percent !== null
                ? `Best so far ${status.best_percent}%, needs ${status.pass_mark}%.`
                : 'Prove you can apply what this stage taught.'}
            </p>
          </div>
        </div>
        <button
          onClick={() => start(false)}
          disabled={busy}
          className="shrink-0 text-xs bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-white px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1.5"
        >
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
          {status.passed ? 'Retake' : status.attempts > 0 ? 'Try again' : 'Take checkpoint'}
        </button>
      </div>
      {error && <p className="text-xs text-red-400 mt-2">{error}</p>}
    </div>
  )
}
