import type { FormEvent } from 'react'
import type { Language, ReportRequest } from '../api/client'
import type { Labels } from '../i18n'

export function ResearchForm({ ticker, date, language, loading, labels: t, onTicker, onDate,
  onLanguage, onGenerate, demoAccess }: {
  ticker: string; date: string; language: Language; loading: boolean; labels: Labels
  onTicker: (value: string) => void; onDate: (value: string) => void
  onLanguage: (value: Language) => void; onGenerate: (request: ReportRequest) => void
  demoAccess?: { code: string; onChange: (value: string) => void }
}) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (loading || !ticker.trim() || !date || (demoAccess && !demoAccess.code)) return
    onGenerate({ ticker: ticker.trim().toUpperCase(), as_of_date: date, response_language: language })
  }
  return <form className="research-form" onSubmit={submit} aria-label={t.workspace}>
    <div className="field"><label htmlFor="ticker">{t.ticker}</label>
      <input id="ticker" className="ticker-input" value={ticker} onChange={event => onTicker(event.target.value)}
        required disabled={loading} autoComplete="off" spellCheck={false} placeholder={t.ticker} /></div>
    <div className="field"><label htmlFor="as-of">{t.asOf}</label>
      <input id="as-of" type="date" value={date} onChange={event => onDate(event.target.value)} required disabled={loading} /></div>
    <div className="field"><label htmlFor="language">{t.language}</label>
      <select id="language" value={language} disabled={loading} onChange={event => onLanguage(event.target.value as Language)}>
        <option value="ENGLISH">English</option><option value="CHINESE">中文</option>
      </select></div>
    <button className="primary" type="submit" disabled={loading || !ticker.trim() || !date || Boolean(demoAccess && !demoAccess.code)}>{t.generate}</button>
    {demoAccess && <div className="field demo-access-field"><label htmlFor="demo-access">{t.demoAccess}</label>
      <input id="demo-access" type="password" value={demoAccess.code} required disabled={loading}
        autoComplete="off" spellCheck={false} aria-describedby="demo-access-help"
        onChange={event => demoAccess.onChange(event.target.value)} />
      <p id="demo-access-help" className="muted">{t.demoAccessHelp}</p>
    </div>}
  </form>
}
