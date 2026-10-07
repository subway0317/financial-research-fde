import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { App } from '../src/App'
import { ReportView } from '../src/components/ReportView'
import { LoadingState } from '../src/components/RequestFeedback'
import { translations } from '../src/i18n'
import { reportFixture } from './fixtures'

async function generate(fixture = reportFixture()) {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture)))
  vi.stubGlobal('fetch', fetch)
  const user = userEvent.setup()
  render(<App />)
  await user.type(screen.getByLabelText('Ticker'), ' test ')
  fireEvent.change(screen.getByLabelText('As-of date'), { target: { value: '2026-06-30' } })
  await user.click(screen.getByRole('button', { name: 'Generate Research' }))
  await screen.findByRole('heading', { name: 'TEST' })
  return { user, fetch }
}

describe('analyst workflow', () => {
  it('defaults to English, a local calendar date, and no report or ticker universe', () => {
    render(<App />)
    expect(screen.getByLabelText('Ticker')).toHaveValue('')
    expect((screen.getByLabelText('As-of date') as HTMLInputElement).value).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(screen.getByLabelText('Language')).toHaveValue('ENGLISH')
    expect(screen.getByRole('button', { name: 'Generate Research' })).toBeDisabled()
    expect(screen.queryByRole('textbox', { name: /prompt|skill/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'AUTO' })).not.toBeInTheDocument()
  })
  it('submits ticker/date/language, trims and uppercases ticker, then renders structured claims', async () => {
    const fixture = reportFixture()
    const { fetch } = await generate(fixture)
    expect(JSON.parse(fetch.mock.calls[0]![1].body)).toEqual({ ticker: 'TEST', as_of_date: '2026-06-30', response_language: 'ENGLISH' })
    for (const section of fixture.report.sections) for (const claim of section.claims) {
      expect(screen.getByText(claim.statement)).toHaveTextContent(claim.statement)
    }
    expect(screen.queryByText('Original backend output.')).not.toBeInTheDocument()
    for (const heading of ['Research Scope', 'Company', 'Fundamentals', 'Market Behavior', 'Data Quality', 'Limitations']) {
      expect(screen.getByRole('heading', { name: heading })).toBeInTheDocument()
    }
    expect(screen.getByText('COMPLETED', { selector: '.status-badge' })).toBeInTheDocument()
    expect(document.activeElement).toHaveAttribute('aria-label', 'Equity Research Report')
  })
  it('blocks repeated submissions throughout loading and shows no artificial percentage', async () => {
    let resolve!: (value: Response) => void
    const fetch = vi.fn().mockReturnValue(new Promise<Response>(done => { resolve = done }))
    vi.stubGlobal('fetch', fetch)
    render(<App />)
    fireEvent.change(screen.getByLabelText('Ticker'), { target: { value: 'TEST' } })
    const button = screen.getByRole('button', { name: 'Generate Research' })
    fireEvent.click(button)
    fireEvent.submit(screen.getByRole('form'))
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(button).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('Generating evidence-grounded research')
    expect(screen.getByText(/Financial data, point-in-time validation/)).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.queryByText(/\d+%/)).not.toBeInTheDocument()
    await act(async () => resolve(new Response(JSON.stringify(reportFixture()))))
    expect(button).toBeEnabled()
  })
  it('shows elapsed seconds and releases its timer on unmount', () => {
    vi.useFakeTimers()
    const { unmount } = render(<LoadingState startedAt={Date.now()} labels={translations.ENGLISH} />)
    act(() => { vi.advanceTimersByTime(37_000) })
    expect(screen.getByText('Elapsed: 37s')).toBeInTheDocument()
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
  it('aborts frontend waiting on unmount', () => {
    const fetch = vi.fn().mockReturnValue(new Promise(() => {}))
    vi.stubGlobal('fetch', fetch)
    const { unmount } = render(<App />)
    fireEvent.change(screen.getByLabelText('Ticker'), { target: { value: 'TEST' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate Research' }))
    const signal: AbortSignal = fetch.mock.calls[0]![1].signal
    unmount()
    expect(signal.aborted).toBe(true)
  })
  it('exposes warning status, original diagnostics and limitations', async () => {
    await generate(reportFixture('COMPLETED_WITH_WARNINGS'))
    expect(screen.getByRole('status')).toHaveTextContent('This report contains warnings')
    expect(screen.getByText('PASS_WITH_WARNINGS', { selector: '.status-badge' })).toBeInTheDocument()
    expect(screen.getByText('READY_WITH_WARNINGS', { selector: '.status-badge' })).toBeInTheDocument()
    expect(screen.getByText('Synthetic data coverage is limited.')).toBeInTheDocument()
    expect(screen.getByText('Synthetic fixture only; coverage is limited.')).toBeVisible()
  })
  it('handles BLOCKED as HTTP success with quality/reasons/limitations/audit and no conclusions', async () => {
    const { user } = await generate(reportFixture('BLOCKED'))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('readiness requirements were not satisfied')
    expect(screen.getByText('BLOCKED', { selector: '.status-badge' })).toBeInTheDocument()
    expect(screen.getByText('Synthetic readiness requirement is missing.')).toBeInTheDocument()
    for (const heading of ['Company', 'Fundamentals', 'Market Behavior']) expect(screen.queryByRole('heading', { name: heading })).not.toBeInTheDocument()
    expect(screen.getByText('Synthetic fixture only; coverage is limited.')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Audit' }))
    expect(screen.getByText('Planner used').nextElementSibling).toHaveTextContent('No')
    expect(screen.getByText('Synthesis calls').nextElementSibling).toHaveTextContent('0')
  })
  it.each([
    [422, 'Please check the request fields.'], [404, 'The requested ticker could not be resolved.'],
    [502, 'A financial data provider could not complete the request.'], [503, 'Required backend configuration is unavailable.'],
    [500, 'The report could not be completed because an internal integrity or server error occurred.'],
  ])('shows the HTTP %i error safely and allows retry', async (status, message) => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error_code: 'INTERNAL_ERROR',
      message: 'Traceback SECRET raw-provider-payload', request_id: '11111111-1111-4111-8111-111111111111' }), { status: Number(status) }))
    vi.stubGlobal('fetch', fetch)
    const user = userEvent.setup()
    render(<App />)
    await user.type(screen.getByLabelText('Ticker'), 'TEST')
    await user.click(screen.getByRole('button', { name: 'Generate Research' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(String(message))
    expect(screen.queryByText(/Traceback SECRET/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate Research' })).toBeEnabled()
    fetch.mockResolvedValue(new Response(JSON.stringify(reportFixture())))
    await user.click(screen.getByRole('button', { name: 'Generate Research' }))
    expect(await screen.findByRole('heading', { name: 'TEST' })).toBeInTheDocument()
  })
  it('handles a network rejection without displaying raw exception text', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('SECRET internal connection details')))
    render(<App />)
    fireEvent.change(screen.getByLabelText('Ticker'), { target: { value: 'TEST' } })
    fireEvent.click(screen.getByRole('button', { name: 'Generate Research' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('The backend could not be reached')
    expect(screen.queryByText(/SECRET/)).not.toBeInTheDocument()
  })
  it('switches the Chinese shell, submits CHINESE and preserves backend statements and codes', async () => {
    const fixture = reportFixture('COMPLETED_WITH_WARNINGS', 'CHINESE')
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture)))
    vi.stubGlobal('fetch', fetch)
    const user = userEvent.setup()
    render(<App />)
    await user.selectOptions(screen.getByLabelText('Language'), 'CHINESE')
    expect(document.documentElement.lang).toBe('zh-CN')
    await user.type(screen.getByLabelText('股票代码'), 'TEST')
    await user.click(screen.getByRole('button', { name: '生成研究报告' }))
    expect(await screen.findByText('合成样本的收入为 120 美元。')).toBeInTheDocument()
    expect(JSON.parse(fetch.mock.calls[0]![1].body).response_language).toBe('CHINESE')
    expect(screen.getByRole('heading', { name: '基本面' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '下载 JSON' })).toBeInTheDocument()
    expect(screen.getByText('COMPLETED_WITH_WARNINGS', { selector: '.status-badge' })).toBeInTheDocument()
    expect(screen.getByText('The supplied deterministic revenue growth is 20 percent.')).toBeInTheDocument()
    await user.selectOptions(screen.getByLabelText('语言'), 'ENGLISH')
    expect(screen.getByRole('heading', { name: 'Fundamentals' })).toBeInTheDocument()
    expect(screen.getByText('合成样本的收入为 120 美元。')).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})

describe('evidence and audit exploration', () => {
  it('opens an evidence citation with canonical IDs and PIT metadata, then restores keyboard focus', async () => {
    const { user } = await generate()
    const citation = screen.getAllByRole('button', { name: 'View evidence E1' })[0]!
    citation.focus()
    await user.keyboard('{Enter}')
    const drawer = screen.getByRole('dialog')
    const detail = within(drawer)
    for (const value of ['synthetic:revenue:current', 'revenue', '120', 'USD', '2025-01-01', '2025-12-31',
      '2026-02-10', '2026-02-11', '2026-06-30', 'synthetic-v1', 'SYNTHETIC_SEC', 'synthetic-filing-current']) {
      expect(detail.getByText(value, { exact: true })).toBeInTheDocument()
    }
    expect(detail.getByText('Observation date').nextElementSibling).toHaveTextContent('—')
    expect(detail.getByText('Filed date')).toBeInTheDocument()
    expect(detail.getByText('Available date')).toBeInTheDocument()
    expect(detail.getByRole('button', { name: 'Close detail' })).toHaveFocus()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(citation).toHaveFocus()
    await user.click(citation)
    await user.click(screen.getByRole('button', { name: 'Close detail' }))
    expect(citation).toHaveFocus()
  })
  it('opens calculation provenance and its input evidence without recalculating', async () => {
    const { user } = await generate()
    await user.click(screen.getAllByRole('button', { name: 'View calculation C1' })[0]!)
    const drawer = within(screen.getByRole('dialog'))
    expect(drawer.getByText('percentage_change')).toBeInTheDocument()
    expect(drawer.getByText('(current - prior) / abs(prior) * 100')).toBeInTheDocument()
    expect(drawer.getByText('Result').nextElementSibling).toHaveTextContent('20')
    expect(drawer.getByText('annualized').nextElementSibling).toHaveTextContent('false')
    expect(drawer.getByText('synthetic:revenue:prior')).toBeInTheDocument()
    await user.click(drawer.getByRole('button', { name: 'View evidence E2' }))
    expect(within(screen.getByRole('dialog')).getByText('Value').nextElementSibling).toHaveTextContent('100')
  })
  it('searches only returned evidence with original aliases and no extra fetch', async () => {
    const { user, fetch } = await generate()
    await user.type(screen.getByLabelText('Filter evidence'), 'synthetic-filing-prior')
    const list = screen.getByRole('list', { name: 'Evidence Explorer' })
    expect(within(list).getByRole('button', { name: 'View evidence E2' })).toBeInTheDocument()
    expect(within(list).queryByRole('button', { name: 'View evidence E1' })).not.toBeInTheDocument()
    await user.clear(screen.getByLabelText('Filter evidence'))
    await user.type(screen.getByLabelText('Filter evidence'), 'no-match')
    expect(screen.getByText('No matching evidence.')).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledTimes(1)
  })
  it('shows manifest counts verbatim and planner-free runtime metadata', async () => {
    const fixture = reportFixture()
    fixture.manifest_summary.claim_count = 99 // display backend metadata even when defensive comparison differs
    const { user } = await generate(fixture)
    await user.click(screen.getByRole('button', { name: 'Audit' }))
    expect(screen.getByText('Claim count').nextElementSibling).toHaveTextContent('99')
    expect(screen.getByText('Planner used').nextElementSibling).toHaveTextContent('No')
    expect(screen.getByText('Planner calls').nextElementSibling).toHaveTextContent('0')
    expect(screen.getByText('Model').nextElementSibling).toHaveTextContent('synthetic-model')
    expect(screen.getByText('Synthesis prompt version').nextElementSibling).toHaveTextContent('synthetic-synthesis-v1')
    expect(screen.getByText('Report compiler version').nextElementSibling).toHaveTextContent('report-compiler-v1')
    expect(screen.getByText('Report ID').nextElementSibling).toHaveTextContent(fixture.report.report_id)
    expect(screen.getByText('Total tokens').nextElementSibling).toHaveTextContent('150')
  })
  it('shows missing canonical citations as visible integrity problems', () => {
    const fixture = reportFixture()
    fixture.report.sections[1]!.claims[0]!.evidence_ids = ['synthetic:missing']
    render(<ReportView response={fixture} labels={translations.ENGLISH} />)
    expect(screen.getAllByRole('alert')[0]).toHaveTextContent('Report integrity problem')
    expect(screen.getByText('Unresolved reference: synthetic:missing')).toBeInTheDocument()
  })
  it('shows inconsistent calculation input aliases visibly', async () => {
    const fixture = reportFixture()
    fixture.report.calculation_appendix[0]!.input_display_aliases = ['E99', 'E2']
    render(<ReportView response={fixture} labels={translations.ENGLISH} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Report integrity problem')
    await userEvent.setup().click(screen.getAllByRole('button', { name: 'View calculation C1' })[0]!)
    expect(within(screen.getByRole('dialog')).getByRole('alert')).toHaveTextContent('Unresolved reference: E99')
  })
  it('renders backend HTML-like statements as text', () => {
    const fixture = reportFixture()
    fixture.report.sections[1]!.claims[0]!.statement = '<script>alert("untrusted")</script>'
    const { container } = render(<ReportView response={fixture} labels={translations.ENGLISH} />)
    expect(screen.getByText('<script>alert("untrusted")</script>')).toBeInTheDocument()
    expect(container.querySelector('script')).toBeNull()
  })
})
