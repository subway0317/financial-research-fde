import { readdir, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

export const sentinels = ['__FRONTEND_SECRET_SENTINEL__', '__SEC_CONTACT_SENTINEL__', '__VITE_SECRET_SENTINEL__',
  '__OPENAI_SECRET_SENTINEL__', '__DEMO_ACCESS_SENTINEL__', '__SEC_SENTINEL__', '__TIINGO_SECRET_SENTINEL__']
const forbidden = [
  /OPENAI_API_KEY|SEC_USER_AGENT|DEMO_ACCESS_TOKEN|TIINGO_API_TOKEN|VITE_[A-Z_]*(?:KEY|SECRET|TOKEN)/,
  /api\.openai\.com|(?:www\.)?sec\.gov|query[12]\.finance\.yahoo\.com|api\.tiingo\.com/,
  /system_prompt|chain_of_thought|raw_provider_payload/,
  /\/home\/zbw21\/|[A-Z]:\\(?:Users|Windows)\\/,
]

export function unsafeContent(content, secrets = []) {
  return forbidden.some(pattern => pattern.test(content)) ||
    [...sentinels, ...secrets].some(value => value.length >= 8 && content.includes(value))
}

export async function scanDirectory(directory, secrets = []) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = new URL(entry.name + (entry.isDirectory() ? '/' : ''), directory)
    if (entry.isDirectory()) await scanDirectory(path, secrets)
    else if (unsafeContent(await readFile(path, 'utf8'), secrets)) {
      throw new Error(`Frontend security boundary failed in ${entry.name}; content redacted.`)
    }
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const secrets = Object.entries(process.env)
    .filter(([key]) => /(?:KEY|SECRET|TOKEN|USER_AGENT)$/.test(key))
    .map(([, value]) => value || '')
  await scanDirectory(new URL('../src/', import.meta.url), secrets)
  await scanDirectory(new URL('../dist/', import.meta.url), secrets)
  console.log('Frontend source and production bundle security boundary passed.')
}
