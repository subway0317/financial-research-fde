import type { ReportResponse } from './api/client'

export function downloadReport(response: ReportResponse, format: 'json' | 'md') {
  const ticker = response.report.ticker.replace(/[^A-Za-z0-9.-]/g, '_').replace(/^\.+/, '') || 'report'
  const date = response.report.as_of_date.replace(/[^0-9-]/g, '_')
  const blob = new Blob([format === 'json' ? JSON.stringify(response.report, null, 2) + '\n' : response.markdown],
    { type: format === 'json' ? 'application/json;charset=utf-8' : 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${ticker}-${date}-research-report.${format}`
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  // Give the browser time to start consuming the URL before releasing it.
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
