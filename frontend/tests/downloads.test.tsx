import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { ReportView } from '../src/components/ReportView'
import { downloadReport } from '../src/downloads'
import { translations } from '../src/i18n'
import { marketReportFixture, reportFixture } from './fixtures'

function readBlob(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsText(blob)
  })
}

it.each(['json', 'md'] as const)('downloads the public %s content through its UI control', async format => {
  const fixture = marketReportFixture()
  let blob!: Blob
  const createURL = vi.fn((value: Blob) => { blob = value; return 'blob:synthetic-download' })
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: createURL, revokeObjectURL: vi.fn() }))
  render(<ReportView response={fixture} labels={translations.ENGLISH} />)
  await userEvent.setup().click(screen.getByRole('button', { name: format === 'json' ? 'Download JSON' : 'Download Markdown' }))
  expect(createURL).toHaveBeenCalledTimes(1)
  expect(click.mock.instances[0]).toHaveAttribute('download', `TEST-2026-06-30-research-report.${format}`)
  const content = await readBlob(blob)
  if (format === 'json') expect(JSON.parse(content)).toEqual(fixture.report)
  else expect(content).toBe(fixture.markdown)
  expect(content).not.toContain('#session=')
  expect(fixture.report.calculation_appendix[1]!.provenance.input_evidence_ids).toEqual([])
  expect(document.querySelector('a[download]')).toBeNull()
})

it('sanitizes ticker filenames and revokes the object URL after download starts', () => {
  vi.useFakeTimers()
  const fixture = reportFixture()
  fixture.report.ticker = '../../private/name'
  const revoke = vi.fn()
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:synthetic'), revokeObjectURL: revoke }))
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  downloadReport(fixture, 'json')
  const anchor = click.mock.instances[0] as HTMLAnchorElement
  expect(anchor.download).not.toMatch(/[\\/]/)
  expect(anchor.download).not.toMatch(/^\./)
  expect(revoke).not.toHaveBeenCalled()
  vi.advanceTimersByTime(1000)
  expect(revoke).toHaveBeenCalledWith('blob:synthetic')
})
