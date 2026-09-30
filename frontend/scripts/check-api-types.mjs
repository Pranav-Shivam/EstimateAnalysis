import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const dir = mkdtempSync(join(tmpdir(), 'api-types-'))
const spec = join(dir, 'openapi.json')
const generated = join(dir, 'schema.d.ts')
const shell = process.platform === 'win32'

execFileSync(
  'uv',
  ['run', '--directory', '../backend', 'python', 'scripts/export_openapi.py', spec],
  { stdio: 'inherit', shell },
)
execFileSync('npx', ['openapi-typescript', spec, '-o', generated], { stdio: 'inherit', shell })

if (readFileSync('src/api/schema.d.ts', 'utf8') !== readFileSync(generated, 'utf8')) {
  console.error('src/api/schema.d.ts is stale: run `npm run gen:api` and commit the result')
  process.exit(1)
}
console.log('api types are current')
