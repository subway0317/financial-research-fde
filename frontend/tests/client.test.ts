import { describe, expect, it, vi } from 'vitest'
import { generateEquityResearchReport, ReportRequestError } from '../src/api/client'
import { reportFixture } from './fixtures'

const request = { ticker: 'TEST', as_of_date: '2026-06-30', response_language: 'ENGLISH' } as const

describe('same-origin report client', () => {
  it('posts only the generated request contract and returns the original response', async () => {
    const fixture = reportFixture()
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture)))
    vi.stubGlobal('fetch', fetch)
    expect(await generateEquityResearchReport(request)).toEqual(fixture)
    expect(fetch).toHaveBeenCalledWith('/v1/reports/equity-research', expect.objectContaining({
      method: 'POST', body: JSON.stringify(request),
    }))
  })
  it('accepts a successful BLOCKED report', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(reportFixture('BLOCKED')))))
    expect((await generateEquityResearchReport(request)).report.status).toBe('BLOCKED')
  })
  it.each([422, 404, 502, 503, 500])('parses the existing sanitized error envelope for HTTP %i', async status => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error_code: 'INTERNAL_ERROR', message: 'Not displayed', request_id: '11111111-1111-4111-8111-111111111111',
    }), { status })))
    await expect(generateEquityResearchReport(request)).rejects.toMatchObject({ status,
      code: 'INTERNAL_ERROR', requestId: '11111111-1111-4111-8111-111111111111' })
  })
  it.each([{ detail: [{ loc: ['body', 'ticker'], msg: 'raw value' }] }, 'raw exception', null, {
    error_code: 'Traceback: SECRET', request_id: '/home/private/path', message: 'private',
  }])('has a safe fallback for unfamiliar error schemas', async body => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 422 })))
    await expect(generateEquityResearchReport(request)).rejects.toMatchObject({ status: 422,
      requestId: undefined, code: undefined })
  })
  it('does not expose non-JSON proxy output', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>private traceback</html>', { status: 502 })))
    await expect(generateEquityResearchReport(request)).rejects.toMatchObject({ status: 502, message: 'Research request failed' })
  })
  it('rejects an incompatible success contract', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ report: {} }))))
    await expect(generateEquityResearchReport(request)).rejects.toBeInstanceOf(ReportRequestError)
  })
  it('passes an AbortSignal to frontend waiting without claiming backend cancellation', async () => {
    const fetch = vi.fn().mockRejectedValue(new DOMException('Aborted', 'AbortError'))
    vi.stubGlobal('fetch', fetch)
    const controller = new AbortController()
    controller.abort()
    await expect(generateEquityResearchReport(request, controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
    expect(fetch).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ signal: controller.signal }))
  })
})
