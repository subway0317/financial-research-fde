import type { Claim, EvidenceEntry, Language, ReportResponse, ResearchReport } from '../src/api/client'

const source: EvidenceEntry = {
  display_alias: 'E1', canonical_id: 'synthetic:revenue:current',
  evidence: { evidence_id: 'synthetic:revenue:current', kind: 'SOURCE_FACT', metric: 'revenue',
    provider: 'SYNTHETIC_SEC', source_reference: 'synthetic-filing-current', value: '120', unit: 'USD',
    disclosure: 'FULL_FACT', date: null, period_start: '2025-01-01', period_end: '2025-12-31', filed_at: '2026-02-10',
    available_date: '2026-02-11', data_vintage: 'synthetic-v1', transformation: [] },
}
const prior: EvidenceEntry = {
  display_alias: 'E2', canonical_id: 'synthetic:revenue:prior',
  evidence: { ...source.evidence, evidence_id: 'synthetic:revenue:prior', value: '100',
    source_reference: 'synthetic-filing-prior', period_start: '2024-01-01', period_end: '2024-12-31',
    filed_at: '2025-02-10', available_date: '2025-02-11' },
}
const computed: EvidenceEntry = {
  display_alias: 'E3', canonical_id: 'synthetic:revenue:growth',
  evidence: { ...source.evidence, evidence_id: 'synthetic:revenue:growth', kind: 'COMPUTATION',
    metric: 'revenue_growth', provider: 'DETERMINISTIC_CORE', source_reference: 'synthetic:calculation',
    value: '20', unit: 'percent', filed_at: null, available_date: null, date: '2026-06-30', transformation: ['percentage_change'] },
}

export function reportFixture(status: ResearchReport['status'] = 'COMPLETED', language: Language = 'ENGLISH'): ReportResponse {
  const blocked = status === 'BLOCKED'
  const quality = status === 'COMPLETED' ? 'PASS' : blocked ? 'FAIL' : 'PASS_WITH_WARNINGS'
  const readiness = blocked ? 'NOT_READY' : status === 'COMPLETED' ? 'READY' : 'READY_WITH_WARNINGS'
  const claims: Claim[] = [
    { claim_id: 'source-1', section: 'COMPANY', claim_type: 'SOURCE_FACT',
      statement: language === 'CHINESE' ? '合成样本的收入为 120 美元。' : 'The synthetic company reported revenue of USD 120.',
      evidence_ids: [source.canonical_id] },
    { claim_id: 'computed-1', section: 'FUNDAMENTALS', claim_type: 'COMPUTED_FACT',
      statement: 'The supplied deterministic revenue growth is 20 percent.', evidence_ids: [computed.canonical_id] },
    { claim_id: 'interpretation-1', section: 'MARKET', claim_type: 'INTERPRETATION',
      statement: 'The supplied evidence indicates revenue expansion.', evidence_ids: [source.canonical_id, computed.canonical_id] },
  ]
  const runtime: ResearchReport['runtime_metadata'] = {
    created_at: '2026-06-30T14:00:00Z', provider: 'SYNTHETIC_LLM', model: 'synthetic-model',
    plan_version: 'deterministic-equity-report-plan-v1', planner_used: false, planner_call_count: 0,
    synthesis_call_count: blocked ? 0 : 1, repair_count: 0, planner_prompt_version: null,
    synthesis_prompt_version: 'synthetic-synthesis-v1', report_compiler_version: 'report-compiler-v1',
    llm_usage: blocked ? [] : [{ provider: 'SYNTHETIC_LLM', model: 'synthetic-model', phase: 'SYNTHESIS',
      prompt_version: 'synthetic-synthesis-v1', latency_ms: 20, input_tokens: 100, output_tokens: 50,
      total_tokens: 150, repair_count: 0, success: true }],
    trace: { steps: [] }, synthesis_payload_audit: null,
  }
  const report: ResearchReport = {
    report_version: 'research-report-v1', projection_version: 'public-research-projection-v1',
    integrity_scope: 'INTERNAL_RESEARCH_REPORT', report_id: `report:${'a'.repeat(64)}`,
    run_id: '11111111-1111-4111-8111-111111111111', ticker: 'TEST', as_of_date: '2026-06-30', language,
    status, selected_skill_id: 'equity_research', synthesis_readiness: readiness, quality_status: quality,
    quality: { status: quality, issues: quality === 'PASS' ? [] : [{ code: 'SYNTHETIC_DIAGNOSTIC',
      severity: blocked ? 'ERROR' : 'WARNING', message: 'Synthetic data coverage is limited.',
      affected_field: 'coverage', affected_date: null, affected_context: null }] },
    sections: (['SCOPE', ...(blocked ? [] : ['COMPANY', 'FUNDAMENTALS', 'MARKET']),
      'QUALITY', 'LIMITATIONS', 'EVIDENCE', 'CALCULATIONS', 'AUDIT'] as ResearchReport['sections'][number]['section_id'][])
      .map(section_id => ({ section_id, claims: blocked ? [] : claims.filter(claim => claim.section === section_id) })),
    limitations: ['Synthetic fixture only; coverage is limited.'],
    blocking_reasons: blocked ? ['Synthetic readiness requirement is missing.'] : [],
    evidence_appendix: blocked ? [] : [structuredClone(source), structuredClone(prior), structuredClone(computed)],
    calculation_appendix: blocked ? [] : [{ display_alias: 'C1', canonical_id: computed.canonical_id,
      provenance: { evidence_id: computed.canonical_id, calculation_name: 'percentage_change',
        metric: 'revenue_growth', result: '20', unit: 'percent',
        methodology: 'Deterministic calculation over the cited non-market or derived facts.',
        input_summary: { input_count: 2, withheld_market_input_count: 0,
          input_range_start: '2024-01-01', input_range_end: '2025-12-31',
          input_kind: 'NON_MARKET_OR_DERIVED_FACTS', input_metrics: ['revenue'], internal_input_digest: 'b'.repeat(64) },
        formula: '(current - prior) / abs(prior) * 100', input_evidence_ids: [source.canonical_id, prior.canonical_id],
        parameters: [{ name: 'annualized', value: false }] }, result: '20', result_unit: 'percent',
      date: '2026-06-30', period_start: '2025-01-01', period_end: '2025-12-31', input_display_aliases: ['E1', 'E2'] }],
    runtime_metadata: runtime, integrity: { algorithm: 'SHA-256', semantic_hash: 'a'.repeat(64) },
  }
  return {
    report, markdown: '# Canonical synthetic Markdown\n\nOriginal backend output.\n',
    manifest_summary: { bundle_version: 'research-report-bundle-v1', report_version: report.report_version,
      projection_version: report.projection_version, integrity_scope: report.integrity_scope,
      report_id: report.report_id, run_id: report.run_id, ticker: report.ticker, as_of_date: report.as_of_date,
      language, selected_skill_id: 'equity_research', report_status: status, agent_status: status,
      synthesis_readiness: readiness, quality_status: quality, planner_used: false, planner_call_count: 0,
      synthesis_call_count: runtime.synthesis_call_count, repair_count: 0, claim_count: blocked ? 0 : 3,
      evidence_count: blocked ? 0 : 3, calculation_count: blocked ? 0 : 1, provider: runtime.provider,
      model: runtime.model, plan_version: runtime.plan_version, planner_prompt_version: null,
      synthesis_prompt_version: runtime.synthesis_prompt_version, report_compiler_version: runtime.report_compiler_version,
      created_at: runtime.created_at, integrity: report.integrity, file_hashes: null },
  }
}

export function marketReportFixture(): ReportResponse {
  const response = reportFixture()
  const summaryId = `public-market-summary:${'c'.repeat(64)}`
  const computedId = `computation:${'d'.repeat(64)}`
  response.report.evidence_appendix.push({ display_alias: 'E4', canonical_id: summaryId,
    evidence: { evidence_id: summaryId, kind: 'SOURCE_FACT', metric: 'close', provider: 'synthetic-market',
      source_reference: 'synthetic-market:TEST:2024-06-30:2026-06-30', disclosure: 'MARKET_INPUT_SUMMARY',
      value: null, date: null, unit: 'USD', transformation: ['adjusted-close-basis'], observation_count: 60,
      input_range_start: '2026-04-06', input_range_end: '2026-06-30', internal_input_digest: 'e'.repeat(64) },
  }, { display_alias: 'E5', canonical_id: computedId,
    evidence: { evidence_id: computedId, kind: 'COMPUTATION', metric: 'realized_volatility_daily',
      provider: 'deterministic-python', source_reference: `calculation://${'d'.repeat(64)}`, disclosure: 'FULL_FACT',
      value: '0.025', unit: null, date: '2026-06-30', transformation: ['sample standard deviation'] },
  })
  response.report.calculation_appendix.push({ display_alias: 'C2', canonical_id: computedId,
    provenance: { evidence_id: computedId, calculation_name: 'realized_volatility_daily',
      metric: 'realized_volatility_daily', result: '0.025', unit: null, formula: 'sample_std(close_to_close_returns)',
      input_evidence_ids: [], parameters: [{ name: 'annualized', value: false }],
      methodology: 'Deterministic calculation over internal session observations; full market inputs are retained in the internal audit.',
      input_summary: { input_count: 60, withheld_market_input_count: 60, input_range_start: '2026-04-06',
        input_range_end: '2026-06-30', input_kind: 'SESSION_MARKET_OBSERVATIONS', input_metrics: ['close'],
        internal_input_digest: 'e'.repeat(64) } },
    result: '0.025', result_unit: null, date: '2026-06-30', period_start: null, period_end: null, input_display_aliases: [],
  })
  response.report.sections.find(section => section.section_id === 'MARKET')!.claims = [{
    claim_id: 'market-1', section: 'MARKET', claim_type: 'COMPUTED_FACT',
    statement: 'The supplied daily volatility is 0.025.', evidence_ids: [computedId, summaryId],
  }]
  response.manifest_summary.evidence_count = 5
  response.manifest_summary.calculation_count = 2
  response.markdown = '# Synthetic public report\n\nDaily volatility: 0.025 [E5][C2]\nInput count: 60\nInput range: 2026-04-06 to 2026-06-30\n'
  return response
}
