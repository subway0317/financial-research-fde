import { readFile, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { describe, expect, it } from 'vitest'
import { scanDirectory, sentinels, unsafeContent } from '../scripts/security-check.mjs'

describe('browser security boundary', () => {
  it.each([...sentinels, 'OPENAI_API_KEY', 'SEC_USER_AGENT', 'VITE_PROVIDER_KEY',
    'https://api.openai.com/v1/responses', 'https://www.sec.gov/data',
    'https://query1.finance.yahoo.com/', 'system_prompt', 'chain_of_thought', 'raw_provider_payload',
    '/home/zbw21/private', 'C:\\Users\\private'])('rejects forbidden browser content %s', content => {
    expect(unsafeContent(content)).toBe(true)
  })
  it('checks the real production source tree and limits fetch to the report endpoint', async () => {
    await expect(scanDirectory(pathToFileURL(join(process.cwd(), 'src') + '/'))).resolves.toBeUndefined()
    const client = await readFile(join(process.cwd(), 'src/api/client.ts'), 'utf8')
    expect(client.match(/fetch\(/g)).toHaveLength(1)
    expect(client).toContain("fetch('/v1/reports/equity-research'")
    const vite = await readFile(join(process.cwd(), 'vite.config.ts'), 'utf8')
    expect(vite).toContain('envDir: false')
    expect(vite).toContain('envPrefix: []')
  })
  it('detects an injected credential in a nested bundle without printing its value', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'financial-research-security-'))
    const secret = '__PRIVATE_TEST_CREDENTIAL_123__'
    try {
      await writeFile(join(directory, 'asset.js'), `const data = ${JSON.stringify(secret)}`)
      await expect(scanDirectory(pathToFileURL(directory + '/'), [secret])).rejects.toThrow('content redacted')
    } finally { await rm(directory, { recursive: true, force: true }) }
  })
})
