import { useState } from 'react'
import {
  ArrowRight, BookOpen, CheckCircle2, Clock, Hammer, Plus, Table2,
  Target, TrendingUp, X, Flag,
} from 'lucide-react'
import { api } from '../api'

/*
 * Chart colors, validated against this app's dark surface (#1e293b) with the
 * dataviz palette validator:
 *   #3987e5 progress / #0ca30c complete  -> all checks pass
 *   blue ordinal ramp                    -> monotone, single hue
 * Blue vs green sits at tritan dE 5.1, so identity never rests on color alone:
 * every bar is direct-labelled and every status carries an icon + text.
 */
const C = {
  progress: '#3987e5',
  complete: '#0ca30c',
  track: 'rgba(148,163,184,0.18)',
}

function StatTile({ icon: Icon, label, value, sub }) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-4 h-4 text-slate-400" />
        <span className="text-xs text-slate-400">{label}</span>
      </div>
      <p className="text-2xl font-semibold text-white tabular-nums">{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
    </div>
  )
}

/** Single ratio against a limit -> meter, not a two-slice pie. */
function Meter({ percent, label, valueLabel, color = C.progress }) {
  return (
    <div>
      <div className="flex justify-between items-baseline mb-1.5">
        <span className="text-sm text-slate-300">{label}</span>
        <span className="text-sm font-semibold text-white tabular-nums">{valueLabel}</span>
      </div>
      <div
        className="h-2.5 rounded-full overflow-hidden"
        style={{ background: C.track }}
        role="img"
        aria-label={`${label}: ${valueLabel}`}
      >
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${Math.min(percent, 100)}%`, background: color }}
        />
      </div>
    </div>
  )
}

export default function Dashboard({ data, onGoToPath, onRefreshSkills }) {
  const [skillInput, setSkillInput] = useState('')
  const [showTable, setShowTable] = useState(false)
  const [busy, setBusy] = useState(false)

  const { learner, path_summary: summary, skill_gap: gap, milestones } = data

  const addSkill = async () => {
    const value = skillInput.trim()
    if (!value) return
    setBusy(true)
    try {
      await api.addSkill(learner.id, value)
      setSkillInput('')
      await onRefreshSkills()
    } finally {
      setBusy(false)
    }
  }

  const dropSkill = async (skill) => {
    await api.removeSkill(learner.id, skill)
    await onRefreshSkills()
  }

  if (!data.has_path) {
    return (
      <div className="max-w-2xl mx-auto bg-slate-800 border border-slate-700 rounded-2xl p-10 text-center">
        <BookOpen className="w-10 h-10 text-slate-500 mx-auto mb-3" />
        <h3 className="text-lg font-semibold text-white mb-1">No path yet</h3>
        <p className="text-slate-400 text-sm mb-5">
          Generate your roadmap and this dashboard will track it.
        </p>
        <button
          onClick={onGoToPath}
          className="bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white font-medium px-5 py-2.5 rounded-lg transition-colors"
        >
          Build my path
        </button>
      </div>
    )
  }

  const selfReported = data.skills_by_source.self_reported
  const fromCourses = data.skills_by_source.from_courses

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Hero figure - the one number the dashboard leads with. */}
      <div className="bg-gradient-to-r from-slate-800 to-slate-800/40 border border-slate-700 rounded-2xl p-6">
        <div className="flex items-end justify-between flex-wrap gap-4">
          <div>
            <p className="text-sm text-slate-400 mb-1">{summary.path_name}</p>
            <div className="flex items-baseline gap-3">
              <span className="text-5xl font-bold text-white tabular-nums">
                {summary.progress_percent}%
              </span>
              <span className="text-sm text-slate-400">complete</span>
            </div>
            {summary.target_role && (
              <p className="text-sm text-purple-300 mt-1.5 flex items-center gap-1.5">
                <Target className="w-3.5 h-3.5" /> Working toward {summary.target_role}
              </p>
            )}
          </div>
          <button
            onClick={onGoToPath}
            className="text-sm text-blue-300 hover:text-blue-200 flex items-center gap-1.5 border border-blue-500/30 rounded-lg px-3 py-2 hover:bg-blue-500/10 transition-colors"
          >
            Open roadmap <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile
          icon={BookOpen}
          label="Courses done"
          value={`${summary.completed_count}/${summary.course_count}`}
        />
        <StatTile
          icon={Clock}
          label="Hours done"
          value={`${summary.completed_hours}h`}
          sub={`of ${summary.total_hours}h total`}
        />
        <StatTile
          icon={TrendingUp}
          label="Weeks left"
          value={data.estimated_weeks_remaining ?? '-'}
          sub={`at ${learner.weekly_hours}h/week`}
        />
        <StatTile
          icon={Target}
          label="Skill coverage"
          value={`${gap.coverage_percent}%`}
          sub={`${gap.covered_skills.length}/${gap.target_skills.length} skills`}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Milestones - compare magnitude across stages, one hue, direct-labelled */}
        <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              <Flag className="w-4 h-4 text-slate-400" /> Milestones
            </h3>
            <div className="flex items-center gap-3 text-[11px] text-slate-400">
              <span className="flex items-center gap-1.5">
                <span
                  className="w-2.5 h-2.5 rounded-sm inline-block"
                  style={{ background: C.complete }}
                />
                reached
              </span>
              <span className="flex items-center gap-1.5">
                <span
                  className="w-2.5 h-2.5 rounded-sm inline-block"
                  style={{ background: C.progress }}
                />
                in progress
              </span>
            </div>
          </div>

          <div className="space-y-3.5">
            {milestones.map((m) => (
              <div key={m.index}>
                <div className="flex justify-between items-baseline mb-1.5 gap-2">
                  <span className="text-sm text-slate-300 flex items-center gap-1.5 min-w-0">
                    {m.reached && (
                      <CheckCircle2
                        className="w-3.5 h-3.5 shrink-0"
                        style={{ color: C.complete }}
                      />
                    )}
                    <span className="truncate">{m.name}</span>
                  </span>
                  {/* Direct label: identity never rests on hue alone. */}
                  <span className="text-xs text-slate-400 tabular-nums shrink-0">
                    {m.completed}/{m.total}
                  </span>
                </div>
                <div
                  className="h-2 rounded-full overflow-hidden"
                  style={{ background: C.track }}
                  role="img"
                  aria-label={`${m.name}: ${m.completed} of ${m.total} complete`}
                >
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{
                      width: `${m.percent}%`,
                      background: m.reached ? C.complete : C.progress,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>

          <button
            onClick={() => setShowTable(!showTable)}
            className="mt-4 text-xs text-slate-500 hover:text-slate-300 flex items-center gap-1.5"
          >
            <Table2 className="w-3.5 h-3.5" />
            {showTable ? 'Hide table view' : 'Table view'}
          </button>

          {showTable && (
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-slate-500 border-b border-slate-700">
                    <th className="text-left py-1.5 font-medium">Milestone</th>
                    <th className="text-right py-1.5 font-medium">Done</th>
                    <th className="text-right py-1.5 font-medium">Total</th>
                    <th className="text-right py-1.5 font-medium">%</th>
                  </tr>
                </thead>
                <tbody className="text-slate-300">
                  {milestones.map((m) => (
                    <tr key={m.index} className="border-b border-slate-800">
                      <td className="py-1.5">{m.name}</td>
                      <td className="text-right tabular-nums">{m.completed}</td>
                      <td className="text-right tabular-nums">{m.total}</td>
                      <td className="text-right tabular-nums">{m.percent}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Skill development */}
        <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-4">
            <Target className="w-4 h-4 text-slate-400" /> Skill development
          </h3>

          <Meter
            percent={gap.coverage_percent}
            label={gap.role ? `Readiness for ${gap.role}` : 'Goal readiness'}
            valueLabel={`${gap.covered_skills.length} of ${gap.target_skills.length}`}
          />

          <div className="mt-5">
            <p className="text-xs text-slate-400 mb-2">
              Covered ({gap.covered_skills.length})
            </p>
            <div className="flex flex-wrap gap-1.5">
              {gap.covered_skills.length === 0 && (
                <span className="text-xs text-slate-600">Nothing yet — finish a course.</span>
              )}
              {gap.covered_skills.map((s) => (
                <span
                  key={s}
                  className="text-[11px] px-2 py-0.5 rounded border flex items-center gap-1"
                  style={{
                    color: '#86efac',
                    borderColor: 'rgba(12,163,12,0.4)',
                    background: 'rgba(12,163,12,0.1)',
                  }}
                >
                  <CheckCircle2 className="w-3 h-3" />
                  {s}
                </span>
              ))}
            </div>
          </div>

          <div className="mt-4">
            <p className="text-xs text-slate-400 mb-2">
              Still missing ({gap.missing_skills.length})
            </p>
            <div className="flex flex-wrap gap-1.5">
              {gap.missing_skills.map((s) => (
                <span
                  key={s}
                  className="text-[11px] bg-amber-500/10 text-amber-300 border border-amber-500/30 px-2 py-0.5 rounded"
                >
                  {s}
                </span>
              ))}
            </div>
          </div>

          <div className="mt-5 pt-4 border-t border-slate-700">
            <p className="text-xs text-slate-400 mb-2">
              Log a skill you already have
            </p>
            <div className="flex gap-2">
              <input
                value={skillInput}
                onChange={(e) => setSkillInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && addSkill()}
                placeholder="e.g. docker"
                className="flex-1 bg-slate-900 text-white text-sm px-3 py-2 rounded-lg border border-slate-700 focus:border-blue-500 focus:outline-none"
              />
              <button
                onClick={addSkill}
                disabled={busy}
                className="bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-white px-3 rounded-lg transition-colors"
              >
                <Plus className="w-4 h-4" />
              </button>
            </div>

            {selfReported.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-3">
                {selfReported.map((s) => (
                  <span
                    key={s}
                    className="text-[11px] bg-slate-700/60 text-slate-300 px-2 py-0.5 rounded flex items-center gap-1"
                  >
                    {s}
                    <button
                      onClick={() => dropSkill(s)}
                      className="text-slate-500 hover:text-red-400"
                      aria-label={`Remove ${s}`}
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
              </div>
            )}

            {fromCourses.length > 0 && (
              <p className="text-[11px] text-slate-500 mt-3">
                +{fromCourses.length} skills credited automatically from completed
                courses.
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Next recommended actions */}
      <div className="bg-slate-800 border border-slate-700 rounded-2xl p-5">
        <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-4">
          <ArrowRight className="w-4 h-4 text-slate-400" /> Next recommended actions
        </h3>
        <div className="space-y-2.5">
          {data.next_actions.length === 0 && (
            <p className="text-sm text-slate-500">Nothing queued.</p>
          )}
          {data.next_actions.map((a, i) => {
            const Icon =
              a.kind === 'project' ? Hammer : a.kind === 'skill' ? Target : BookOpen
            return (
              <div
                key={i}
                className="flex gap-3 bg-slate-900/60 border border-slate-700 rounded-xl p-3.5"
              >
                <div className="shrink-0 w-7 h-7 rounded-lg bg-slate-800 flex items-center justify-center">
                  <Icon className="w-4 h-4 text-blue-400" />
                </div>
                <div className="min-w-0">
                  <p className="text-sm text-white font-medium">{a.title}</p>
                  <p className="text-xs text-slate-400 mt-0.5">{a.detail}</p>
                  {a.url && (
                    <a
                      href={a.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-xs text-blue-400 hover:text-blue-300 mt-1 inline-block"
                    >
                      Open course &rarr;
                    </a>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
