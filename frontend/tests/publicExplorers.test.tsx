import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it } from 'vitest'
import { ReportView } from '../src/components/ReportView'
import { translations } from '../src/i18n'
import { marketReportFixture } from './fixtures'

it('shows market calculation summaries with counts and methodology, without session inputs', async () => {
  const fixture = marketReportFixture()
  render(<ReportView response={fixture} labels={translations.ENGLISH} />)
  await userEvent.setup().click(screen.getAllByRole('button', { name: 'View calculation C2' })[0]!)
  const drawer = within(screen.getByRole('dialog'))
  expect(drawer.getByText('Input count').nextElementSibling).toHaveTextContent('60')
  expect(drawer.getByText('Input range start').nextElementSibling).toHaveTextContent('2026-04-06')
  expect(drawer.getByText('Input range end').nextElementSibling).toHaveTextContent('2026-06-30')
  expect(drawer.getByText('Input type').nextElementSibling).toHaveTextContent('SESSION_MARKET_OBSERVATIONS')
  expect(drawer.getByText('Internal input digest').nextElementSibling).toHaveTextContent('e'.repeat(64))
  expect(drawer.getByText('Result').nextElementSibling).toHaveTextContent('0.025')
  expect(drawer.getByText('Methodology').nextElementSibling).toHaveTextContent('internal session observations')
  expect(drawer.queryByRole('button', { name: /View evidence/ })).not.toBeInTheDocument()
  expect(document.querySelector('.calculation-inputs')?.children).toHaveLength(0)
})

it('shows value-free market evidence summaries and the public projection audit version', async () => {
  const fixture = marketReportFixture()
  const user = userEvent.setup()
  render(<ReportView response={fixture} labels={translations.ENGLISH} />)
  await user.click(screen.getAllByRole('button', { name: 'View evidence E4' })[0]!)
  const drawer = within(screen.getByRole('dialog'))
  expect(drawer.getByText(translations.ENGLISH.marketSummary)).toBeInTheDocument()
  expect(drawer.getByText('Input count').nextElementSibling).toHaveTextContent('60')
  expect(drawer.getByText('Value').nextElementSibling).toHaveTextContent('—')
  expect(drawer.getByText('Observation date').nextElementSibling).toHaveTextContent('—')
  await user.click(drawer.getByRole('button', { name: 'Close detail' }))
  await user.click(screen.getByRole('button', { name: 'Audit' }))
  expect(screen.getByText('Public projection version').nextElementSibling).toHaveTextContent('public-research-projection-v1')
  expect(screen.getByText('Internal research semantic hash')).toBeInTheDocument()
})
