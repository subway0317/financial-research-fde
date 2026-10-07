import type { components, operations } from './generated'

type ReportOperation = operations['equity_research_v1_reports_equity_research_post']
export type ReportRequest = ReportOperation['requestBody']['content']['application/json']
export type ReportResponse = ReportOperation['responses'][200]['content']['application/json']
export type ResearchReport = components['schemas']['ResearchReport']
export type Language = components['schemas']['ReportLanguage']
export type EvidenceEntry = components['schemas']['EvidenceAppendixEntry']
export type CalculationEntry = components['schemas']['CalculationAppendixEntry']
export type Claim = components['schemas']['GroundedClaim']
type ErrorResponse = components['schemas']['ErrorResponse']

export class ReportRequestError extends Error {
  constructor(public readonly status: number, public readonly requestId?: string,
    public readonly code?: ErrorResponse['error_code']) {
    super('Research request failed')
  }
}

function safeErrorMetadata(body: unknown): { requestId?: string; code?: string } {
  if (!body || typeof body !== 'object') return {}
  const envelope = body as Partial<ErrorResponse>
  return {
    requestId: typeof envelope.request_id === 'string' &&
      /^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(envelope.request_id) ? envelope.request_id : undefined,
    code: typeof envelope.error_code === 'string' &&
      /^[A-Z_]{1,80}$/.test(envelope.error_code) ? envelope.error_code : undefined,
  }
}

export async function generateEquityResearchReport(request: ReportRequest,
  signal?: AbortSignal, demoAccessCode?: string): Promise<ReportResponse> {
  const response = await fetch('/v1/reports/equity-research', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json',
      ...(demoAccessCode ? { 'X-Demo-Access': demoAccessCode } : {}) },
    body: JSON.stringify(request),
    signal,
  })
  let body: unknown
  try { body = await response.json() } catch { throw new ReportRequestError(response.ok ? 500 : response.status) }
  if (!response.ok) {
    const { requestId, code } = safeErrorMetadata(body)
    throw new ReportRequestError(response.status, requestId, code)
  }
  // FastAPI validates the success contract. This guard rejects empty/proxy responses;
  // it does not duplicate the backend's report or financial validation.
  if (!body || typeof body !== 'object' || !('report' in body) || !('manifest_summary' in body) ||
    !('markdown' in body) || typeof body.markdown !== 'string' || !body.report ||
    typeof body.report !== 'object' || !('report_version' in body.report) ||
    body.report.report_version !== 'research-report-v1') throw new ReportRequestError(500)
  return body as ReportResponse
}
