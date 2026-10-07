import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import openapiTS, { astToString } from 'openapi-typescript'

const root = fileURLToPath(new URL('../../', import.meta.url))
const localPython = new URL('../../.venv/bin/python', import.meta.url)
const python = process.env.PYTHON || (existsSync(localPython) ? fileURLToPath(localPython) : 'python')
const exported = spawnSync(python, ['-m', 'financial_research.api.openapi'], {
  cwd: root, encoding: 'utf8', maxBuffer: 10 * 1024 * 1024,
})
if (exported.status !== 0 || !exported.stdout) {
  throw new Error('OpenAPI export failed. Install the repository Python package in your environment.')
}
const schema = JSON.parse(exported.stdout)
const output = '// Generated from FastAPI OpenAPI by scripts/api-types.mjs. DO NOT EDIT.\n' +
  astToString(await openapiTS(schema))
const target = new URL('../src/api/generated.ts', import.meta.url)
if (process.argv.includes('--check')) {
  if (!existsSync(target) || await readFile(target, 'utf8') !== output) {
    throw new Error('OpenAPI contract drift: run npm run api:generate and review generated.ts.')
  }
  console.log('OpenAPI contract current.')
} else {
  await writeFile(target, output)
  console.log('Generated src/api/generated.ts from FastAPI OpenAPI.')
}
