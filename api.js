const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function request(path, options = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })

  // Surface the API's own error detail instead of failing silently, which is
  // what made the previous version impossible to debug from the UI.
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (body?.detail) {
        if (typeof body.detail === 'string') {
          detail = body.detail
        } else if (Array.isArray(body.detail)) {
          // FastAPI returns validation failures as a list of objects; show the
          // messages rather than dumping raw JSON at the user.
          detail = body.detail
            .map((e) => (e?.msg ? e.msg : JSON.stringify(e)))
            .join('; ')
        } else {
          detail = JSON.stringify(body.detail)
        }
      }
    } catch {
      // response had no JSON body; keep the status-based message
    }
    throw new Error(detail)
  }
  return response.json()
}

const post = (path, body) =>
  request(path, { method: 'POST', body: JSON.stringify(body ?? {}) })

export const api = {
  extractProfile: (text) => post('/api/profile/extract', { text }),
  createLearner: (profile) => post('/api/learners', profile),
  getLearner: (id) => request(`/api/learners/${id}`),

  generatePath: (id) => post(`/api/learners/${id}/generate-path`),
  adaptPath: (id, note) => post(`/api/learners/${id}/adapt-path`, { note }),
  getPath: (id) => request(`/api/learners/${id}/path`),

  completeCourse: (pathCourseId, completed) =>
    post(`/api/path-courses/${pathCourseId}/complete`, { completed }),

  getDashboard: (id) => request(`/api/learners/${id}/dashboard`),

  listAssessments: (id) => request(`/api/learners/${id}/assessments`),
  getAssessment: (id, milestoneIndex, regenerate = false) =>
    post(`/api/learners/${id}/assessments/${milestoneIndex}?regenerate=${regenerate}`),
  submitAssessment: (assessmentId, answers) =>
    post(`/api/assessments/${assessmentId}/submit`, { answers }),

  addSkill: (id, skill) => post(`/api/learners/${id}/skills`, { skill }),
  removeSkill: (id, skill) =>
    request(`/api/learners/${id}/skills/${encodeURIComponent(skill)}`, { method: 'DELETE' }),

  sendFeedback: (id, signal, courseId, comment) =>
    post(`/api/learners/${id}/feedback`, { signal, course_id: courseId, comment }),

  chat: (id, message) => post(`/api/learners/${id}/chat`, { message }),
  chatHistory: (id) => request(`/api/learners/${id}/chat`),
}

export { API_URL }
