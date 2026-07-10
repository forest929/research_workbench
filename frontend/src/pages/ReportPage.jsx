import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchReport } from '../api'
import LoadingSpinner from '../components/LoadingSpinner'
import { Download, RefreshCw, BarChart3 } from 'lucide-react'

function inlineFormat(text) {
  // bold **...**
  return text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
}

function renderMarkdown(md) {
  const lines = md.split('\n')
  const elements = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Table detection: line contains | and next line is separator (---|---)
    if (line.includes('|') && i + 1 < lines.length && /^[\s|:-]+$/.test(lines[i + 1])) {
      const tableLines = [line]
      i += 2 // skip separator
      while (i < lines.length && lines[i].includes('|')) {
        tableLines.push(lines[i])
        i++
      }
      const parseRow = (r) => r.split('|').map(c => c.trim()).filter(Boolean)
      const headers = parseRow(tableLines[0])
      const rows = tableLines.slice(1).map(parseRow)
      elements.push(
        <div key={i} className="overflow-x-auto my-4">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200">
                {headers.map((h, j) => (
                  <th key={j} className="px-3 py-2 text-left font-semibold text-slate-700 text-xs uppercase tracking-wide"
                    dangerouslySetInnerHTML={{ __html: inlineFormat(h) }} />
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, ri) => (
                <tr key={ri} className="border-b border-slate-100 hover:bg-slate-50">
                  {row.map((cell, ci) => (
                    <td key={ci} className="px-3 py-2 text-slate-700 align-top"
                      dangerouslySetInnerHTML={{ __html: inlineFormat(cell) }} />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )
      continue
    }

    if (line.startsWith('### ')) { elements.push(<h3 key={i} className="text-base font-semibold text-slate-800 mt-5 mb-1">{line.slice(4)}</h3>); i++; continue }
    if (line.startsWith('## '))  { elements.push(<h2 key={i} className="text-lg font-semibold text-slate-900 mt-6 mb-2">{line.slice(3)}</h2>); i++; continue }
    if (line.startsWith('# '))   { elements.push(<h1 key={i} className="text-xl font-bold text-slate-900 mt-6 mb-3">{line.slice(2)}</h1>); i++; continue }
    if (line.startsWith('- ') || line.startsWith('* ')) {
      elements.push(<li key={i} className="text-sm text-slate-700 ml-4 leading-relaxed" dangerouslySetInnerHTML={{ __html: inlineFormat(line.slice(2)) }} />)
      i++; continue
    }
    if (line.startsWith('> ')) {
      elements.push(<blockquote key={i} className="border-l-4 border-slate-300 pl-4 text-sm text-slate-500 italic my-2">{line.slice(2)}</blockquote>)
      i++; continue
    }
    if (line === '---' || line === '***') { elements.push(<hr key={i} className="border-slate-200 my-4" />); i++; continue }
    if (line.trim() === '') { elements.push(<div key={i} className="h-2" />); i++; continue }
    elements.push(<p key={i} className="text-sm text-slate-700 leading-relaxed mb-1" dangerouslySetInnerHTML={{ __html: inlineFormat(line) }} />)
    i++
  }
  return elements
}

export default function ReportPage() {
  const { id: projectId } = useParams()
  const [enabled, setEnabled] = useState(true)

  const { data: reportMd, isLoading, error, refetch } = useQuery({
    queryKey: ['report', projectId],
    queryFn: () => fetchReport(projectId),
    enabled,
    staleTime: 60_000,
  })

  function downloadReport() {
    const blob = new Blob([reportMd], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `portfolio_report_${projectId.slice(0, 8)}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 py-4 border-b border-slate-200 bg-white flex items-center justify-between shrink-0">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">Portfolio Report</h1>
          <p className="text-sm text-slate-500">Verified criteria and analysis artifact</p>
        </div>
        <div className="flex gap-2">
          <button className="btn-secondary text-xs" onClick={() => { setEnabled(true); refetch() }}>
            <RefreshCw size={13} /> Refresh
          </button>
          {reportMd && (
            <button className="btn-primary text-xs" onClick={downloadReport}>
              <Download size={13} /> Download Markdown
            </button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        {isLoading && (
          <div className="flex justify-center py-10">
            <LoadingSpinner label="Loading report…" />
          </div>
        )}

        {error && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-4 py-3">
            {error.message} — Make sure the project has been analyzed.
          </div>
        )}

        {!isLoading && !reportMd && !error && (
          <div className="text-center py-16 text-slate-400">
            <BarChart3 size={40} className="mx-auto mb-3 opacity-30" />
            <p className="font-medium">No report available</p>
            <p className="text-sm mt-1">Complete the research analysis to generate a report</p>
          </div>
        )}

        {reportMd && (
          <div className="max-w-3xl mx-auto">
            <div className="card px-8 py-6">
              <div className="prose-content">
                {renderMarkdown(reportMd)}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
