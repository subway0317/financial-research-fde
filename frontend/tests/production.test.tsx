import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { App } from '../src/App'
import { generateEquityResearchReport } from '../src/api/client'
import { reportFixture } from './fixtures'

const code = 'synthetic-user-entered-code'

it('preserves the Stage 7 development form without a demo input', () => {
  render(<App production={false} />)
  expect(screen.queryByLabelText('Demo access code')).not.toBeInTheDocument()
})

it('requires a masked, memory-only code in production and sends it only as a header', async () => {
  const fixture = reportFixture()
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture)))
  vi.stubGlobal('fetch', fetch)
  const user = userEvent.setup()
  const { unmount } = render(<App production />)
  await user.type(screen.getByLabelText('Ticker'), 'TEST')
  expect(screen.getByRole('button', { name: 'Generate Research' })).toBeDisabled()
  expect(screen.getByLabelText('Demo access code')).toHaveAttribute('type', 'password')
  await user.type(screen.getByLabelText('Demo access code'), code)
  await user.click(screen.getByRole('button', { name: 'Generate Research' }))
  await screen.findByRole('heading', { name: 'TEST' })
  const [url, options] = fetch.mock.calls[0]!
  expect(url).toBe('/v1/reports/equity-research')
  expect(options.headers['X-Demo-Access']).toBe(code)
  expect(Object.keys(JSON.parse(options.body))).toEqual(['ticker', 'as_of_date', 'response_language'])
  expect(options.body).not.toContain(code)
  expect(localStorage.length).toBe(0)
  expect(sessionStorage.length).toBe(0)
  unmount()
  render(<App production />)
  expect(screen.getByLabelText('Demo access code')).toHaveValue('')
  expect(fetch).toHaveBeenCalledTimes(1)
})

it.each([
  [401, 'A valid demo access code is required.'],
  [403, 'A valid demo access code is required.'],
  [429, 'Another research report is currently being generated.'],
])('shows production HTTP %i safely without retrying automatically', async (status, text) => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error_code: 'DEMO_BUSY',
    message: code + ' private server details', request_id: '11111111-1111-4111-8111-111111111111' }), { status: Number(status) }))
  vi.stubGlobal('fetch', fetch)
  render(<App production />)
  fireEvent.change(screen.getByLabelText('Ticker'), { target: { value: 'TEST' } })
  fireEvent.change(screen.getByLabelText('Demo access code'), { target: { value: code } })
  fireEvent.click(screen.getByRole('button', { name: 'Generate Research' }))
  expect(await screen.findByRole('alert')).toHaveTextContent(String(text))
  expect(screen.queryByText(/private server details/)).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Generate Research' })).toBeEnabled()
  expect(fetch).toHaveBeenCalledTimes(1)
})

it('supports the Chinese production shell and busy message', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 429 })))
  const user = userEvent.setup()
  render(<App production />)
  await user.selectOptions(screen.getByLabelText('Language'), 'CHINESE')
  await user.type(screen.getByLabelText('股票代码'), 'TEST')
  await user.type(screen.getByLabelText('演示访问码'), code)
  await user.click(screen.getByRole('button', { name: '生成研究报告' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('当前已有研究任务正在生成，请稍后重试。')
})

it('omits the access header when no code is supplied', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(reportFixture())))
  vi.stubGlobal('fetch', fetch)
  await generateEquityResearchReport({ ticker: 'TEST', as_of_date: '2026-06-30', response_language: 'ENGLISH' })
  expect(fetch.mock.calls[0]![1].headers).not.toHaveProperty('X-Demo-Access')
})
