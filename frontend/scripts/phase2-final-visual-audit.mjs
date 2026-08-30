import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium } from 'playwright'

const BASE = process.env.NUBAGZ_AUDIT_BASE_URL || 'http://127.0.0.1:8080'
const OUT = process.env.NUBAGZ_AUDIT_OUT || '/tmp/nubagz-phase2-final-visual'
await fs.mkdir(OUT, { recursive: true })

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 })
const page = await context.newPage()
const consoleEvents = []
page.on('console', msg => {
  if (['error', 'warning'].includes(msg.type())) consoleEvents.push({ type: msg.type(), text: msg.text(), url: page.url() })
})
page.on('pageerror', err => consoleEvents.push({ type: 'pageerror', text: String(err), url: page.url() }))

async function settle() { await page.waitForLoadState('domcontentloaded'); await page.waitForTimeout(1100) }
async function shot(urlPath, name, fullPage = true) { await page.goto(`${BASE}${urlPath}`, { waitUntil: 'domcontentloaded' }); await settle(); await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage }) }
async function apiLogin(email, password) {
  const response = await page.request.post(`${BASE}/api/auth/login`, { data: { email, password } })
  if (!response.ok()) throw new Error(`Login failed for ${email}: ${response.status()} ${await response.text()}`)
  const payload = await response.json()
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.evaluate(({ token }) => { localStorage.setItem('nubagz_token', token); localStorage.setItem('nubagz_auth_source', 'password') }, { token: payload.access_token })
  return payload
}
async function bearer() { return { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('nubagz_token'))}` } }
async function clearAuth() { await page.goto(BASE, { waitUntil: 'domcontentloaded' }); await page.evaluate(() => { localStorage.removeItem('nubagz_token'); localStorage.removeItem('nubagz_auth_source'); sessionStorage.clear() }) }

try {
  await apiLogin('demo@demo.nubagz.com', 'Demo123!')
  await shot('/app/studio', '01-creator-project-list')
  const headers = await bearer()
  const createdProject = await page.request.post(`${BASE}/api/projects`, { headers, data: { name: 'Phase Two Final Visual Audit', symbol: 'P2FV', description: 'Disposable Project created only inside the final Phase 2 visual audit production stack.', website: 'https://example.com', chain: 'Robinhood' } })
  if (!createdProject.ok()) throw new Error(`Audit Project creation failed: ${createdProject.status()} ${await createdProject.text()}`)
  const project = await createdProject.json()
  for (const [view, name] of [
    ['overview','02-control-room-overview'],['challenges','03-control-room-challenges'],['submissions','04-control-room-submissions'],['rewards','05-control-room-rewards'],['trust','06-control-room-trust'],['analytics','07-control-room-analytics'],
  ]) await shot(`/app/studio?project=${project.id}&view=${view}`, name)

  await clearAuth(); await apiLogin('admin@demo.nubagz.com', 'Admin123!')
  await shot('/app/admin/users', '10-admin-users')
  await shot('/app/admin/users/1', '11-admin-user-detail-recovery')
  await shot('/app/admin/security', '12-admin-security')

  await page.setViewportSize({ width: 390, height: 844 })
  await shot(`/app/studio?project=${project.id}&view=overview`, '20-control-room-mobile', false)
  await shot('/app/admin/users', '21-admin-users-mobile', false)

  await fs.writeFile(path.join(OUT, 'console-events.json'), JSON.stringify(consoleEvents, null, 2))
  console.log(`Final Phase 2 visual audit screenshots written to ${OUT}`)
} finally { await browser.close() }
