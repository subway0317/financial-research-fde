import { useEffect, useState } from 'react'
import { ReportRequestError } from '../api/client'
import type { Labels } from '../i18n'

export function LoadingState({ startedAt, labels: t }: { startedAt: number; labels: Labels }) {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const interval = window.setInterval(() => setSeconds(Math.floor((Date.now() - startedAt) / 1000)), 1000)
    return () => window.clearInterval(interval)
  }, [startedAt])
  return <section className="feedback loading" aria-busy="true">
    <div className="loading-line" aria-hidden="true" />
    <div role="status"><h2>{t.loadingTitle}</h2><p>{t.loadingText}</p></div>
    <p className="elapsed">{t.elapsed}: {seconds}{t.seconds}</p>
  </section>
}

export function ErrorState({ error, labels: t }: { error: Error; labels: Labels }) {
  const status = error instanceof ReportRequestError ? error.status : 0
  const messages: Record<number, string> = { 401: t.errorAccess, 403: t.errorAccess, 429: t.error429,
    422: t.error422, 404: t.error404, 502: t.error502,
    503: t.error503, 500: t.error500, 0: t.errorNetwork }
  return <section className="feedback error" role="alert">
    <h2>{t.errorTitle}</h2><p>{messages[status] ?? t.errorOther}</p>
    {error instanceof ReportRequestError && <dl className="metadata compact">
      {error.code && <><dt>{t.errorCode}</dt><dd>{error.code}</dd></>}
      {error.requestId && <><dt>{t.requestId}</dt><dd>{error.requestId}</dd></>}
    </dl>}
  </section>
}
