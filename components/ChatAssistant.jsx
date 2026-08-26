import { useEffect, useRef, useState } from 'react'
import { Bot, Loader2, Send, User } from 'lucide-react'
import { api } from '../api'

const SUGGESTIONS = [
  'Why was this course recommended to me?',
  'What should I do this week?',
  'Which skill am I furthest behind on?',
  'Can you explain the order of my path?',
]

/** Minimal markdown rendering: fenced code, **bold**, and paragraph breaks. */
function renderContent(text) {
  const blocks = text.split(/```/)
  return blocks.map((block, i) => {
    if (i % 2 === 1) {
      return (
        <pre
          key={i}
          className="bg-slate-950 border border-slate-700 rounded-lg p-3 my-2 overflow-x-auto text-xs text-slate-200"
        >
          <code>{block.replace(/^\w+\n/, '')}</code>
        </pre>
      )
    }
    return (
      <span key={i}>
        {block.split('\n').map((line, j) => (
          <span key={j} className="block">
            {line.split(/(\*\*[^*]+\*\*)/).map((part, k) =>
              part.startsWith('**') && part.endsWith('**') ? (
                <strong key={k} className="text-white font-semibold">
                  {part.slice(2, -2)}
                </strong>
              ) : (
                part
              )
            )}
          </span>
        ))}
      </span>
    )
  })
}

export default function ChatAssistant({ learnerId }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const endRef = useRef(null)

  useEffect(() => {
    api
      .chatHistory(learnerId)
      .then((r) => setMessages(r.messages))
      .catch(() => {})
  }, [learnerId])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, busy])

  const send = async (text) => {
    const question = (text ?? input).trim()
    if (!question || busy) return

    setMessages((prev) => [...prev, { role: 'user', content: question }])
    setInput('')
    setBusy(true)
    setError('')

    try {
      const result = await api.chat(learnerId, question)
      setMessages((prev) => [...prev, { role: 'assistant', content: result.response }])
    } catch (err) {
      setError(err.message)
      // Roll the failed question back into the box so it is not lost.
      setInput(question)
      setMessages((prev) => prev.slice(0, -1))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto">
      <div className="bg-slate-800 border border-slate-700 rounded-2xl flex flex-col h-[70vh]">
        <div className="px-5 py-4 border-b border-slate-700 flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-600 to-purple-600 flex items-center justify-center">
            <Bot className="w-4 h-4 text-white" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">Learning assistant</h3>
            <p className="text-xs text-slate-400">
              Knows your path, progress and skill gaps
            </p>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {messages.length === 0 && !busy && (
            <div className="text-center py-8">
              <Bot className="w-9 h-9 text-slate-600 mx-auto mb-3" />
              <p className="text-sm text-slate-400 mb-4">
                Ask about your roadmap, or why anything was recommended.
              </p>
              <div className="space-y-1.5 max-w-sm mx-auto">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="block w-full text-left text-xs text-slate-400 hover:text-blue-300 bg-slate-900/50 hover:bg-slate-900 border border-slate-700/60 rounded-lg px-3 py-2 transition-colors"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <div
              key={i}
              className={`flex gap-3 ${m.role === 'user' ? 'justify-end' : ''}`}
            >
              {m.role === 'assistant' && (
                <div className="shrink-0 w-7 h-7 rounded-lg bg-slate-700 flex items-center justify-center">
                  <Bot className="w-4 h-4 text-blue-400" />
                </div>
              )}
              <div
                className={`rounded-xl px-4 py-2.5 text-sm leading-relaxed max-w-[80%] ${
                  m.role === 'user'
                    ? 'bg-blue-600 text-white'
                    : 'bg-slate-900 text-slate-200 border border-slate-700'
                }`}
              >
                {m.role === 'assistant' ? renderContent(m.content) : m.content}
              </div>
              {m.role === 'user' && (
                <div className="shrink-0 w-7 h-7 rounded-lg bg-slate-700 flex items-center justify-center">
                  <User className="w-4 h-4 text-slate-300" />
                </div>
              )}
            </div>
          ))}

          {busy && (
            <div className="flex gap-3">
              <div className="shrink-0 w-7 h-7 rounded-lg bg-slate-700 flex items-center justify-center">
                <Bot className="w-4 h-4 text-blue-400" />
              </div>
              <div className="bg-slate-900 border border-slate-700 rounded-xl px-4 py-2.5 flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 text-slate-400 animate-spin" />
                <span className="text-sm text-slate-400">Thinking...</span>
              </div>
            </div>
          )}
          <div ref={endRef} />
        </div>

        {error && (
          <p className="px-5 pb-2 text-xs text-red-400">{error}</p>
        )}

        <div className="p-4 border-t border-slate-700 flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && send()}
            placeholder="Ask about your learning path..."
            className="flex-1 bg-slate-900 text-white text-sm px-4 py-2.5 rounded-lg border border-slate-700 focus:border-blue-500 focus:outline-none"
          />
          <button
            onClick={() => send()}
            disabled={busy || !input.trim()}
            className="bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 disabled:opacity-40 text-white px-4 rounded-lg transition-colors"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  )
}
