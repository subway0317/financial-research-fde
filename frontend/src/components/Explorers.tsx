import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { EvidenceEntry, ReportResponse } from '../api/client'
import type { Labels } from '../i18n'
import type { References } from '../reportReferences'
import { CitationChip } from './ReportView'

export type Selection = { kind: 'evidence' | 'calculation'; alias: string }

function Metadata({ rows }: { rows: [string, ReactNode][] }) {
  return <dl className="metadata">{rows.map(([label, value]) => <div className="metadata-row" key={label}>
    <dt>{label}</dt><dd>{value === null || value === undefined || value === '' ? '—' : value}</dd>
  </div>)}</dl>
}

export function EvidenceExplorer({ entries, onSelect, labels: t }: {
  entries: EvidenceEntry[]; onSelect: (selection: Selection) => void; labels: Labels
}) {
  const [query, setQuery] = useState('')
  const filtered = entries.filter(entry => JSON.stringify(entry).toLocaleLowerCase().includes(query.toLocaleLowerCase().trim()))
  return <div>
    <h4>{t.explorer}</h4><label className="filter-label" htmlFor="evidence-search">{t.search}</label>
    <input id="evidence-search" type="search" value={query} placeholder={t.searchHint} onChange={event => setQuery(event.target.value)} />
    {!entries.length ? <p>{t.noEvidence}</p> : !filtered.length ? <p>{t.noMatches}</p> :
      <ul className="entry-list" aria-label={t.explorer}>{filtered.map(entry => <li key={entry.display_alias}>
        <CitationChip alias={entry.display_alias} kind="evidence" onClick={() => onSelect({ kind: 'evidence', alias: entry.display_alias })} labels={t} />
        <span>{entry.evidence.metric}</span><span className="muted">{entry.evidence.provider}</span>
        <span className="entry-value">{entry.evidence.value ?? '—'} {entry.evidence.unit ?? '—'}</span>
      </li>)}</ul>}
  </div>
}

export function DetailDrawer({ selection, references, asOf, onSelect, onClose, labels: t }: {
  selection: Selection; references: References; asOf: string; onSelect: (value: Selection) => void
  onClose: () => void; labels: Labels
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const element = dialog.current
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    element?.showModal()
    closeButton.current?.focus()
    return () => {
      element?.close()
      if (previousFocus?.isConnected) previousFocus.focus()
    }
  }, [])
  useEffect(() => { closeButton.current?.focus() }, [selection.kind, selection.alias])
  const evidence = selection.kind === 'evidence' ? references.evidenceByAlias.get(selection.alias) : undefined
  const calculation = selection.kind === 'calculation' ? references.calculationsByAlias.get(selection.alias) : undefined
  return <dialog ref={dialog} className="detail-drawer" aria-labelledby="detail-title"
    onCancel={event => { event.preventDefault(); onClose() }}
    onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); onClose() } }}>
    <div className="drawer-header"><div><p className="eyebrow">{selection.kind === 'evidence' ? t.evidenceDetail : t.calculationDetail}</p>
      <h2 id="detail-title">{selection.alias}</h2></div>
      <button ref={closeButton} type="button" onClick={onClose} aria-label={t.close}>×</button></div>
    <div className="drawer-body">
      {!evidence && !calculation && <p role="alert">{t.integrity}</p>}
      {evidence && <>
        <p className="pit-note">{t.pit}</p><p className="muted">{t.missing}</p>
        <Metadata rows={[
          [t.alias, evidence.display_alias], [t.canonical, evidence.canonical_id], [t.kind, evidence.evidence.kind],
          [t.metric, evidence.evidence.metric], [t.value, evidence.evidence.value], [t.unit, evidence.evidence.unit],
          [t.periodStart, evidence.evidence.period_start], [t.periodEnd, evidence.evidence.period_end],
          [t.observation, evidence.evidence.date], [t.filed, evidence.evidence.filed_at],
          [t.available, evidence.evidence.available_date], [t.asOf, asOf], [t.vintage, evidence.evidence.data_vintage],
          [t.provider, evidence.evidence.provider], [t.source, evidence.evidence.source_reference],
          [t.transformation, evidence.evidence.transformation?.join('; ')],
        ]} />
        {references.calculationsById.has(evidence.canonical_id) &&
          <button type="button" onClick={() => onSelect({ kind: 'calculation',
            alias: references.calculationsById.get(evidence.canonical_id)!.display_alias })}>{t.calculationDetail}</button>}
      </>}
      {calculation && <>
        <p className="muted">{t.missing}</p>
        <Metadata rows={[
          [t.alias, calculation.display_alias], [t.canonical, calculation.canonical_id],
          [t.operation, calculation.provenance.calculation_name], [t.formula, calculation.provenance.formula],
          [t.result, calculation.result], [t.unit, calculation.result_unit], [t.observation, calculation.date],
          [t.periodStart, calculation.period_start], [t.periodEnd, calculation.period_end], [t.asOf, asOf],
        ]} />
        <h3>{t.inputs}</h3><ul className="calculation-inputs">
          {calculation.provenance.input_evidence_ids.map((id, index) => {
            const alias = calculation.input_display_aliases[index]
            const target = alias ? references.evidenceByAlias.get(alias) : undefined
            return <li key={id}><CitationChip alias={alias ?? id} kind="evidence" missing={!target || target.canonical_id !== id}
              onClick={() => alias && onSelect({ kind: 'evidence', alias })} labels={t} /> <code>{id}</code>
              {target && <p>{target.evidence.metric}: {target.evidence.value ?? '—'} {target.evidence.unit ?? '—'}</p>}</li>
          })}
        </ul>
        <h3>{t.parameters}</h3>{calculation.provenance.parameters?.length ?
          <Metadata rows={calculation.provenance.parameters.map(parameter => [parameter.name, String(parameter.value)])} /> : <p>—</p>}
      </>}
    </div>
  </dialog>
}

export function AuditPanel({ response, labels: t }: { response: ReportResponse; labels: Labels }) {
  const report = response.report
  const runtime = report.runtime_metadata
  const manifest = response.manifest_summary
  return <div><h4>{t.audit}</h4><Metadata rows={[
    [t.reportId, report.report_id], [t.runId, report.run_id], [t.version, report.report_version],
    [t.skill, report.selected_skill_id], [t.model, runtime.model], [t.provider, runtime.provider],
    [t.promptVersion, runtime.synthesis_prompt_version], [t.compiler, runtime.report_compiler_version],
    [t.plan, runtime.plan_version], [t.claimCount, manifest.claim_count], [t.evidenceCount, manifest.evidence_count],
    [t.calculationCount, manifest.calculation_count], [t.plannerUsed, runtime.planner_used ? t.yes : t.no],
    [t.plannerCalls, runtime.planner_call_count], [t.synthesisCalls, runtime.synthesis_call_count], [t.repairs, runtime.repair_count],
    [t.status, report.status], [t.quality, report.quality_status], [t.readiness, report.synthesis_readiness],
    [t.created, runtime.created_at], [t.hash, report.integrity.semantic_hash],
  ]} />
    <h4>{t.usage}</h4>{runtime.llm_usage.length ? runtime.llm_usage.map((usage, index) =>
      <Metadata key={index} rows={[[t.phase, usage.phase], [t.latency, usage.latency_ms],
        [t.inputTokens, usage.input_tokens], [t.outputTokens, usage.output_tokens], [t.totalTokens, usage.total_tokens]]} />)
      : <p>—</p>}
  </div>
}
