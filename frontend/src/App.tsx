import { useEffect, useRef, useState } from 'react'
import { generateEquityResearchReport, type Language, type ReportRequest, type ReportResponse } from './api/client'
import { ResearchForm } from './components/ResearchForm'
import { ErrorState, LoadingState } from './components/RequestFeedback'
import { ReportView } from './components/ReportView'
import { translations } from './i18n'

type RequestState = { status: 'IDLE' } | { status: 'LOADING'; startedAt: number } |
  { status: 'SUCCESS'; response: ReportResponse } | { status: 'ERROR'; error: Error }

function today() {
  const date = new Date()
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

export function App({ production = import.meta.env.PROD }: { production?: boolean } = {}) {
  const [ticker, setTicker] = useState('')
  const [date, setDate] = useState(today)
  const [language, setLanguage] = useState<Language>('ENGLISH')
  const [demoAccessCode, setDemoAccessCode] = useState('')
  const [request, setRequest] = useState<RequestState>({ status: 'IDLE' })
  const activeRequest = useRef<AbortController | null>(null)
  const resultRegion = useRef<HTMLDivElement>(null)
  const t = translations[language]

  useEffect(() => () => { activeRequest.current?.abort() }, [])
  useEffect(() => {
    document.documentElement.lang = language === 'CHINESE' ? 'zh-CN' : 'en'
    document.title = `${t.brand} · ${t.workspace}`
  }, [language, t])
  useEffect(() => {
    if (request.status === 'SUCCESS' || request.status === 'ERROR') resultRegion.current?.focus()
  }, [request.status])

  async function generate(input: ReportRequest) {
    if (activeRequest.current || (production && !demoAccessCode)) return
    const controller = new AbortController()
    activeRequest.current = controller
    setRequest({ status: 'LOADING', startedAt: Date.now() })
    try {
      const response = await generateEquityResearchReport(input, controller.signal, production ? demoAccessCode : undefined)
      if (!controller.signal.aborted) setRequest({ status: 'SUCCESS', response })
    } catch (error) {
      if (!controller.signal.aborted) setRequest({ status: 'ERROR', error: error instanceof Error ? error : new Error('Request failed') })
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null
    }
  }

  return <>
    <a className="skip-link" href="#research-input">{t.workspace}</a>
    <header className="app-header"><div className="brand-mark" aria-hidden="true">FR</div>
      <div><h1>{t.brand}</h1><p>{t.workspace}</p></div></header>
    <main>
      <section className="input-panel" id="research-input" aria-label={t.workspace}>
        <ResearchForm ticker={ticker} date={date} language={language} loading={request.status === 'LOADING'}
          labels={t} onTicker={setTicker} onDate={setDate} onLanguage={setLanguage} onGenerate={generate}
          demoAccess={production ? { code: demoAccessCode, onChange: setDemoAccessCode } : undefined} />
      </section>
      <div ref={resultRegion} tabIndex={-1} className="result-region" aria-label={t.report}>
        {request.status === 'IDLE' && <section className="empty-state"><p className="eyebrow">{t.workspace}</p>
          <h2>{t.idleTitle}</h2><p>{t.idleText}</p><div className="empty-outline" aria-hidden="true"><span /><span /><span /></div></section>}
        {request.status === 'LOADING' && <LoadingState startedAt={request.startedAt} labels={t} />}
        {request.status === 'ERROR' && <ErrorState error={request.error} labels={t} />}
        {request.status === 'SUCCESS' && <ReportView key={request.response.report.run_id} response={request.response} labels={t} />}
      </div>
    </main>
  </>
}
