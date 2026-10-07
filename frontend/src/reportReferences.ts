import type { ResearchReport } from './api/client'

// Lookup and integrity checks concern identities only; financial/PIT validation stays in FastAPI.
export function reportReferences(report: ResearchReport) {
  const evidenceById = new Map(report.evidence_appendix.map(entry => [entry.canonical_id, entry]))
  const evidenceByAlias = new Map(report.evidence_appendix.map(entry => [entry.display_alias, entry]))
  const calculationsById = new Map(report.calculation_appendix.map(entry => [entry.canonical_id, entry]))
  const calculationsByAlias = new Map(report.calculation_appendix.map(entry => [entry.display_alias, entry]))
  const problems: string[] = []
  if (evidenceById.size !== report.evidence_appendix.length || evidenceByAlias.size !== report.evidence_appendix.length ||
    calculationsById.size !== report.calculation_appendix.length || calculationsByAlias.size !== report.calculation_appendix.length) {
    problems.push('DUPLICATE_REFERENCE')
  }
  for (const entry of report.evidence_appendix) {
    if (entry.canonical_id !== entry.evidence.evidence_id) problems.push(entry.display_alias)
    if (entry.evidence.kind === 'COMPUTATION' && !calculationsById.has(entry.canonical_id)) problems.push(entry.display_alias)
  }
  for (const section of report.sections) for (const claim of section.claims) {
    for (const id of claim.evidence_ids) if (!evidenceById.has(id)) problems.push(id)
  }
  for (const entry of report.calculation_appendix) {
    if (entry.canonical_id !== entry.provenance.evidence_id || !evidenceById.has(entry.canonical_id) ||
      entry.input_display_aliases.length !== entry.provenance.input_evidence_ids.length) problems.push(entry.display_alias)
    entry.provenance.input_evidence_ids.forEach((id, index) => {
      if (evidenceByAlias.get(entry.input_display_aliases[index] ?? '')?.canonical_id !== id) problems.push(id)
    })
  }
  return { evidenceById, evidenceByAlias, calculationsById, calculationsByAlias, problems }
}

export type References = ReturnType<typeof reportReferences>
