import { useMemo, useState } from 'react'
import type { Claim, ReportResponse } from '../api/client'
import { downloadReport } from '../downloads'
import type { Labels } from '../i18n'
import { reportReferences, type References } from '../reportReferences'
import { AuditPanel, DetailDrawer, EvidenceExplorer, type Selection } from './Explorers'

export function StatusBadge({ code }: { code: string }) {
  const tone = code === 'BLOCKED' || code === 'FAIL' || code === 'NOT_READY' ? 'bad'
    : code.includes('WARNINGS') ? 'warning' : 'good'
  return <span className={`status-badge ${tone}`}>{code}</span>
}

export function CitationChip({ alias, kind, missing, onClick, labels: t }: {
  alias: string; kind: 'evidence' | 'calculation'; missing?: boolean; onClick: () => void; labels: Labels
}) {
  if (missing) return <span className="citation unresolved" role="alert">{t.unresolved}: {alias}</span>
  return <button className={`citation ${kind}`} type="button" onClick={onClick}
    aria-label={`${kind === 'evidence' ? t.evidenceButton : t.calculationButton} ${alias}`}>[{alias}]</button>
}

function ClaimView({ claim, references, onSelect, labels: t }: {
  claim: Claim; references: References; onSelect: (selection: Selection) => void; labels: Labels
}) {
  return <article className="claim">
    <span className="claim-type">{claim.claim_type}</span>
    <p className="claim-statement">{claim.statement}</p>
    <div className="citations">{claim.evidence_ids.map(id => {
      const evidence = references.evidenceById.get(id)
      const calculation = references.calculationsById.get(id)
      return <span key={id}>
        <CitationChip alias={evidence?.display_alias ?? id} kind="evidence" missing={!evidence}
          onClick={() => evidence && onSelect({ kind: 'evidence', alias: evidence.display_alias })} labels={t} />
        {calculation && <CitationChip alias={calculation.display_alias} kind="calculation"
          onClick={() => onSelect({ kind: 'calculation', alias: calculation.display_alias })} labels={t} />}
      </span>
    })}</div>
  </article>
}

export function ReportView({ response, labels: t }: { response: ReportResponse; labels: Labels }) {
  const report = response.report
  const references = useMemo(() => reportReferences(report), [report])
  const [selection, setSelection] = useState<Selection | null>(null)
  const [tab, setTab] = useState<'evidence' | 'calculation' | 'audit'>('evidence')
  const headings = { SCOPE: t.scope, COMPANY: t.company, FUNDAMENTALS: t.fundamentals,
    MARKET: t.market, QUALITY: t.quality, LIMITATIONS: t.limitations }
  const sections = report.sections.filter(section => section.section_id in headings &&
    !(report.status === 'BLOCKED' && ['COMPANY', 'FUNDAMENTALS', 'MARKET'].includes(section.section_id)))
  const documentLanguage = report.language === 'CHINESE' ? 'zh-CN' : 'en'

  return <div className="report-workspace">
    <section className="report-header" aria-labelledby="report-title">
      <div><p className="eyebrow">{t.report}</p><h2 id="report-title" tabIndex={-1}>{report.ticker}</h2>
        <p>{t.asOf}: <strong>{report.as_of_date}</strong></p></div>
      <div className="report-statuses">
        <div><span>{t.status}</span><StatusBadge code={report.status} /></div>
        <div><span>{t.quality}</span><StatusBadge code={report.quality_status} /></div>
        <div><span>{t.readiness}</span><StatusBadge code={report.synthesis_readiness} /></div>
      </div>
      <div className="download-actions">
        <button type="button" onClick={() => downloadReport(response, 'json')}>{t.json}</button>
        <button type="button" onClick={() => downloadReport(response, 'md')}>{t.markdown}</button>
      </div>
    </section>

    {report.status === 'COMPLETED_WITH_WARNINGS' && <div className="banner warning" role="status">{t.warnings}</div>}
    {report.status === 'BLOCKED' && <div className="banner blocked" role="status">{t.blocked}</div>}
    {references.problems.length > 0 && <div className="banner blocked" role="alert">
      <strong>{t.integrity}</strong><ul>{references.problems.map((problem, index) => <li key={index}>{problem}</li>)}</ul>
    </div>}

    <div className="report-layout">
      <nav className="section-nav" aria-label={t.report}>
        {sections.map(section => <a key={section.section_id} href={`#section-${section.section_id}`}>
          {headings[section.section_id as keyof typeof headings]}</a>)}
        <a href="#exploration">{t.evidence} / {t.calculations} / {t.audit}</a>
      </nav>
      <div className="report-content">
        {sections.map(section => <section className="report-section" key={section.section_id}
          id={`section-${section.section_id}`} aria-labelledby={`heading-${section.section_id}`}>
          <h3 id={`heading-${section.section_id}`}>{headings[section.section_id as keyof typeof headings]}</h3>
          {section.section_id === 'SCOPE' && <><p>{t.pit}</p>
            <dl className="metadata compact"><dt>{t.asOf}</dt><dd>{report.as_of_date}</dd>
              <dt>{t.workflow}</dt><dd>{report.selected_skill_id}</dd></dl></>}
          <div lang={documentLanguage}>{(section.claims ?? []).map(claim => <ClaimView key={claim.claim_id}
            claim={claim} references={references} onSelect={setSelection} labels={t} />)}</div>
          {section.section_id === 'QUALITY' && <>
            {report.quality.issues?.length ? <ul className="diagnostics" lang={documentLanguage}>
              {report.quality.issues.map((issue, index) => <li key={index}>
                <span className="diagnostic-code">{issue.severity} · {issue.code}</span><p>{issue.message}</p>
                {(issue.affected_field || issue.affected_date || issue.affected_context) &&
                  <p className="muted">{[issue.affected_field, issue.affected_date, issue.affected_context].filter(Boolean).join(' · ')}</p>}
              </li>)}
            </ul> : <p className="muted">{t.noIssues}</p>}
            {report.status === 'BLOCKED' && <div className="blocking-reasons"><h4>{t.reasons}</h4>
              <ul lang={documentLanguage}>{report.blocking_reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul>
            </div>}
          </>}
          {section.section_id === 'LIMITATIONS' && (report.limitations.length ?
            <ul className="limitations" lang={documentLanguage}>{report.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul>
            : <p className="muted">{t.noLimitations}</p>)}
        </section>)}

        <section className="report-section exploration" id="exploration" aria-labelledby="explorer-heading">
          <h3 id="explorer-heading">{t.evidence} / {t.calculations} / {t.audit}</h3>
          <div className="explorer-controls" aria-label={t.explorer}>
            <button type="button" aria-pressed={tab === 'evidence'} onClick={() => setTab('evidence')}>{t.evidence}</button>
            <button type="button" aria-pressed={tab === 'calculation'} onClick={() => setTab('calculation')}>{t.calculations}</button>
            <button type="button" aria-pressed={tab === 'audit'} onClick={() => setTab('audit')}>{t.audit}</button>
          </div>
          {tab === 'evidence' && <EvidenceExplorer entries={report.evidence_appendix} onSelect={setSelection} labels={t} />}
          {tab === 'calculation' && <div><h4>{t.calculations}</h4>
            {report.calculation_appendix.length ? <ul className="entry-list">{report.calculation_appendix.map(entry =>
              <li key={entry.display_alias}><CitationChip alias={entry.display_alias} kind="calculation"
                onClick={() => setSelection({ kind: 'calculation', alias: entry.display_alias })} labels={t} />
                <span>{entry.provenance.calculation_name}</span><span className="muted">{entry.result ?? '—'} {entry.result_unit ?? '—'}</span>
              </li>)}
            </ul> : <p>{t.noCalculations}</p>}
          </div>}
          {tab === 'audit' && <AuditPanel response={response} labels={t} />}
        </section>
      </div>
    </div>
    {selection && <DetailDrawer selection={selection} references={references} asOf={report.as_of_date}
      onSelect={setSelection} onClose={() => setSelection(null)} labels={t} />}
  </div>
}
