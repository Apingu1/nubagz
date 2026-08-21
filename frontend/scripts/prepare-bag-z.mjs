import { mkdir, readdir, readFile, rm, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(here, '..')
const masterDir = path.join(frontendRoot, 'bag-z-masters')
const fallbackDir = path.join(frontendRoot, 'public', 'bag-z')
const hqDir = path.join(frontendRoot, 'public', 'bag-z-hq')
const generatedDir = path.join(frontendRoot, 'src', 'generated')
const generatedMap = path.join(generatedDir, 'bag-z-assets.ts')

const variants = [
  'base',
  'hello',
  'detective',
  'wallet',
  'loot',
  'security',
  'warning',
  'confused',
  'sleepy',
  'victory',
]

function parseTopLevelBoxes(buffer) {
  let offset = 0
  const boxes = []

  while (offset < buffer.length) {
    if (offset + 8 > buffer.length) throw new Error(`truncated ISO-BMFF box header at byte ${offset}`)

    let size = buffer.readUInt32BE(offset)
    const type = buffer.toString('ascii', offset + 4, offset + 8)
    let headerSize = 8

    if (size === 1) {
      if (offset + 16 > buffer.length) throw new Error(`truncated extended-size box ${type}`)
      const extended = buffer.readBigUInt64BE(offset + 8)
      if (extended > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error(`box ${type} is too large to validate safely`)
      size = Number(extended)
      headerSize = 16
    } else if (size === 0) {
      size = buffer.length - offset
    }

    if (size < headerSize) throw new Error(`invalid box size ${size} for ${type}`)
    const end = offset + size
    if (end > buffer.length) throw new Error(`truncated ${type} box: expected ${size} bytes, only ${buffer.length - offset} remain`)

    boxes.push({ type, offset, size })
    offset = end
  }

  if (offset !== buffer.length) throw new Error(`ISO-BMFF parse ended at ${offset}, file length is ${buffer.length}`)
  return boxes
}

function findLargestIspeDimensions(buffer) {
  const marker = Buffer.from('ispe', 'ascii')
  let cursor = 0
  let best = null

  while (cursor < buffer.length) {
    const index = buffer.indexOf(marker, cursor)
    if (index === -1) break

    if (index >= 4 && index + 16 <= buffer.length) {
      const boxSize = buffer.readUInt32BE(index - 4)
      const width = buffer.readUInt32BE(index + 8)
      const height = buffer.readUInt32BE(index + 12)
      const plausible = boxSize >= 20 && width > 0 && height > 0 && width <= 10000 && height <= 10000
      if (plausible) {
        const area = width * height
        if (!best || area > best.width * best.height) best = { width, height }
      }
    }

    cursor = index + marker.length
  }

  return best
}

function validateAvif(buffer, variant) {
  if (buffer.length < 32) throw new Error(`${variant}: reconstructed AVIF is unexpectedly small`)

  const boxes = parseTopLevelBoxes(buffer)
  const ftyp = boxes.find((box) => box.type === 'ftyp')
  const meta = boxes.find((box) => box.type === 'meta')
  const mdat = boxes.find((box) => box.type === 'mdat')
  if (!ftyp || !meta || !mdat) throw new Error(`${variant}: reconstructed file is missing required AVIF boxes`)

  const brandWindow = buffer.toString('ascii', ftyp.offset + 8, Math.min(ftyp.offset + ftyp.size, ftyp.offset + 40))
  if (!brandWindow.includes('avif') && !brandWindow.includes('avis')) {
    throw new Error(`${variant}: reconstructed file does not advertise an AVIF brand`)
  }

  const dimensions = findLargestIspeDimensions(buffer)
  if (!dimensions) throw new Error(`${variant}: could not read AVIF dimensions`)
  if (dimensions.width < 1254 || dimensions.height < 1254) {
    throw new Error(`${variant}: ${dimensions.width}x${dimensions.height} is below the 1254px master floor`)
  }

  return dimensions
}

async function assertFallbacksExist() {
  for (const variant of variants) {
    const file = path.join(fallbackDir, `${variant}.webp`)
    let info
    try {
      info = await stat(file)
    } catch {
      throw new Error(`Missing Bag Z fallback asset: public/bag-z/${variant}.webp`)
    }
    if (!info.isFile() || info.size < 1000) throw new Error(`Invalid Bag Z fallback asset: public/bag-z/${variant}.webp`)
  }
}

async function reconstructVariant(variant, chunks) {
  chunks.sort((a, b) => a.part - b.part)
  for (let i = 0; i < chunks.length; i += 1) {
    if (chunks[i].part !== i + 1) throw new Error(`${variant}: master chunks are not contiguous from part 1`)
  }

  const encodedPieces = []
  for (const chunk of chunks) {
    const text = (await readFile(path.join(masterDir, chunk.entry), 'utf8')).replace(/\s+/g, '')
    if (!/^[A-Za-z0-9+/=]+$/.test(text)) throw new Error(`${variant}: ${chunk.entry} contains invalid base64 characters`)
    encodedPieces.push(text)
  }

  const buffer = Buffer.from(encodedPieces.join(''), 'base64')
  const dimensions = validateAvif(buffer, variant)
  const output = path.join(hqDir, `${variant}.avif`)
  await writeFile(output, buffer)
  return { dimensions, bytes: buffer.length, buffer, source: `/bag-z-hq/${variant}.avif` }
}

async function reconstructRasterMasters() {
  const entries = await readdir(masterDir)
  const grouped = new Map()

  for (const entry of entries) {
    const match = /^([a-z0-9-]+)\.(\d+)\.part$/i.exec(entry)
    if (!match) continue
    const [, variant, partText] = match
    const part = Number(partText)
    const list = grouped.get(variant) ?? []
    list.push({ part, entry })
    grouped.set(variant, list)
  }

  await rm(hqDir, { recursive: true, force: true })
  await mkdir(hqDir, { recursive: true })

  const hqVariants = new Map()
  let baseBuffer = null

  for (const [variant, chunks] of grouped) {
    try {
      const result = await reconstructVariant(variant, chunks)
      hqVariants.set(variant, { ...result.dimensions, source: result.source })
      if (variant === 'base') baseBuffer = result.buffer
      console.log(`Bag Z HQ raster: ${variant} -> ${result.dimensions.width}x${result.dimensions.height} (${result.bytes} bytes)`)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      if (variant === 'base') throw error
      console.warn(`Bag Z HQ raster skipped: ${variant} (${message})`)
    }
  }

  if (!baseBuffer) throw new Error('The approved high-resolution base Bag Z master was not reconstructed')
  return { hqVariants, baseBuffer }
}

function svgShell(baseDataUri, body, options = {}) {
  const { scale = 0.91, x = 55, y = 55, rotate = 0, accent = '#b7ff38', secondary = '#5be8ff' } = options
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1254" height="1254" viewBox="0 0 1254 1254" role="img" aria-label="Bag Z">
  <defs>
    <radialGradient id="halo" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="${accent}" stop-opacity=".20"/><stop offset="1" stop-color="${accent}" stop-opacity="0"/></radialGradient>
    <filter id="glow"><feGaussianBlur stdDeviation="18" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    <filter id="soft"><feGaussianBlur stdDeviation="34"/></filter>
  </defs>
  <ellipse cx="760" cy="640" rx="410" ry="390" fill="url(#halo)" filter="url(#soft)"/>
  <g transform="translate(${x} ${y}) rotate(${rotate} 570 570) scale(${scale})">
    <image href="${baseDataUri}" width="1254" height="1254"/>
  </g>
  <g stroke-linecap="round" stroke-linejoin="round">${body}</g>
</svg>\n`
}

function contextualSvg(variant, baseDataUri) {
  const lime = '#b7ff38'
  switch (variant) {
    case 'hello':
      return svgShell(baseDataUri, `
        <path d="M122 310 C190 252 268 248 338 298" fill="none" stroke="${lime}" stroke-width="11" opacity=".95"/>
        <path d="M142 355 C202 309 257 309 313 347" fill="none" stroke="${lime}" stroke-width="7" opacity=".72"/>
        <path d="M1060 168 l10 24 24 10-24 10-10 24-10-24-24-10 24-10z" fill="#f4ffe9" filter="url(#glow)"/>
        <path d="M1112 348 l7 17 17 7-17 7-7 17-7-17-17-7 17-7z" fill="#f4ffe9"/>
      `, { scale: .90, x: 55, y: 60, accent: lime })
    case 'detective':
      return svgShell(baseDataUri, `
        <circle cx="278" cy="455" r="130" fill="#07151d" fill-opacity=".34" stroke="#58e8ff" stroke-width="15" filter="url(#glow)"/>
        <circle cx="278" cy="455" r="109" fill="none" stroke="#e5fdff" stroke-opacity=".35" stroke-width="4"/>
        <path d="M370 548 L520 698" stroke="#07151d" stroke-width="46"/>
        <path d="M370 548 L520 698" stroke="#58e8ff" stroke-width="12"/>
        <path d="M856 410 h-72 v72 M1056 410 h72 v72 M856 722 h-72 v-72 M1056 722 h72 v-72" fill="none" stroke="${lime}" stroke-width="7"/>
      `, { scale: .84, x: 110, y: 92, accent: '#58e8ff', secondary: lime })
    case 'wallet':
      return svgShell(baseDataUri, `
        <rect x="70" y="565" width="300" height="290" rx="46" fill="#080d16" stroke="#5799ff" stroke-width="11" filter="url(#glow)"/>
        <rect x="112" y="615" width="216" height="162" rx="26" fill="#141b28" stroke="#ffffff" stroke-opacity=".18" stroke-width="3"/>
        <path d="M157 651 H283 L205 742 H294 L274 764 H150 L228 674 H146 Z" fill="${lime}"/>
        <circle cx="307" cy="813" r="17" fill="${lime}"/>
      `, { scale: .85, x: 118, y: 82, accent: '#5799ff' })
    case 'loot':
      return svgShell(baseDataUri, `
        <path d="M114 540 Q210 450 327 520 Q365 577 345 845 H118 Q82 690 114 540Z" fill="#090b0d" stroke="#ffd05a" stroke-width="8" filter="url(#glow)"/>
        <path d="M164 507 H300" stroke="${lime}" stroke-width="12"/>
        <path d="M155 626 H290 L208 770 H302" fill="none" stroke="${lime}" stroke-width="22"/>
        <g fill="#ffd05a" stroke="#fff1b8" stroke-width="4"><circle cx="367" cy="886" r="45"/><circle cx="301" cy="930" r="32"/><circle cx="1084" cy="768" r="39"/><circle cx="1116" cy="852" r="27"/></g>
      `, { scale: .84, x: 112, y: 78, accent: '#ffd05a' })
    case 'security':
      return svgShell(baseDataUri, `
        <path d="M914 452 L1088 513 L1077 731 Q1048 840 914 923 Q780 840 751 731 L740 513 Z" fill="#06171a" fill-opacity=".92" stroke="#4fece6" stroke-width="12" filter="url(#glow)"/>
        <path d="M824 690 L890 757 L1013 611" fill="none" stroke="${lime}" stroke-width="30"/>
      `, { scale: .84, x: 18, y: 82, accent: '#4fece6' })
    case 'warning':
      return svgShell(baseDataUri, `
        <path d="M125 780 L309 468 L493 780 Z" fill="#1a0d05" stroke="#ffb02e" stroke-width="16" filter="url(#glow)"/>
        <rect x="295" y="566" width="28" height="112" rx="13" fill="#ffb02e"/><circle cx="309" cy="722" r="17" fill="#ffb02e"/>
        <circle cx="1074" cy="352" r="58" fill="#3a0908" stroke="#ff5146" stroke-width="8"/><path d="M1036 352 Q1074 307 1112 352" fill="#ff5146"/>
      `, { scale: .85, x: 112, y: 82, accent: '#ff8d32' })
    case 'confused':
      return svgShell(baseDataUri, `
        <text x="112" y="415" fill="#b873ff" font-size="196" font-family="Arial,sans-serif" font-weight="800" filter="url(#glow)">?</text>
        <text x="1020" y="402" fill="${lime}" font-size="118" font-family="Arial,sans-serif" font-weight="800">?</text>
        <text x="1080" y="738" fill="#b873ff" font-size="104" font-family="Arial,sans-serif" font-weight="800">?</text>
        <text x="142" y="875" fill="${lime}" font-size="96" font-family="Arial,sans-serif" font-weight="800">?</text>
      `, { scale: .86, x: 80, y: 100, rotate: -1.5, accent: '#b873ff' })
    case 'sleepy':
      return svgShell(baseDataUri, `
        <path d="M267 186 A118 118 0 1 0 284 373 A98 98 0 1 1 267 186Z" fill="#a66cff" filter="url(#glow)"/>
        <text x="970" y="384" fill="#a66cff" font-size="118" font-family="Arial,sans-serif" font-weight="800">Z</text>
        <text x="1092" y="292" fill="#6f9dff" font-size="88" font-family="Arial,sans-serif" font-weight="800">Z</text>
        <text x="1117" y="450" fill="#efe9ff" font-size="62" font-family="Arial,sans-serif" font-weight="800">Z</text>
      `, { scale: .85, x: 86, y: 112, rotate: 1.6, accent: '#8f61ff' })
    case 'victory':
      return svgShell(baseDataUri, `
        <g fill="#ffd05a" stroke="#fff1b8" stroke-width="6" filter="url(#glow)"><rect x="152" y="520" width="166" height="188" rx="28"/><rect x="214" y="704" width="42" height="86"/><rect x="148" y="782" width="176" height="58" rx="18"/></g>
        <path d="M150 544 Q76 560 92 662 Q108 713 170 685 M320 544 Q394 560 378 662 Q362 713 300 685" fill="none" stroke="#ffd05a" stroke-width="22"/>
        <path d="M185 574 H286 L222 671 H299" fill="none" stroke="#594300" stroke-width="20"/>
        <g fill="${lime}"><rect x="160" y="175" width="13" height="35" transform="rotate(18 166 192)"/><rect x="365" y="202" width="13" height="35" transform="rotate(-24 371 219)"/><rect x="1010" y="165" width="13" height="35" transform="rotate(26 1016 182)"/><rect x="1120" y="282" width="13" height="35" transform="rotate(-18 1126 299)"/></g>
        <g fill="#ffd05a"><circle cx="225" cy="250" r="12"/><circle cx="430" cy="148" r="10"/><circle cx="1050" cy="310" r="13"/><circle cx="1122" cy="470" r="9"/></g>
      `, { scale: .84, x: 115, y: 76, rotate: -1.1, accent: '#ffd05a' })
    default:
      throw new Error(`No contextual SVG recipe for ${variant}`)
  }
}

async function generateContextualMasters(hqVariants, baseBuffer) {
  const baseDataUri = `data:image/avif;base64,${baseBuffer.toString('base64')}`

  for (const variant of variants) {
    if (variant === 'base' || hqVariants.has(variant)) continue
    const svg = contextualSvg(variant, baseDataUri)
    const output = path.join(hqDir, `${variant}.svg`)
    await writeFile(output, svg, 'utf8')
    const info = await stat(output)
    if (info.size < 50000) throw new Error(`${variant}: generated HQ SVG is unexpectedly small`)
    hqVariants.set(variant, { width: 1254, height: 1254, source: `/bag-z-hq/${variant}.svg` })
    console.log(`Bag Z HQ vector: ${variant} -> 1254x1254 (${info.size} bytes)`)
  }
}

async function writeGeneratedSourceMap(hqVariants) {
  await mkdir(generatedDir, { recursive: true })
  const lines = ['// AUTO-GENERATED by scripts/prepare-bag-z.mjs. Do not edit by hand.', 'export const bagZSources = {']

  for (const variant of variants) {
    const source = hqVariants.get(variant)?.source ?? `/bag-z/${variant}.webp`
    lines.push(`  ${variant}: '${source}',`)
  }

  lines.push('} as const', '')
  lines.push('export const bagZHqSources = {')
  for (const variant of variants) {
    const source = hqVariants.get(variant)?.source
    lines.push(`  ${variant}: ${source ? `'${source}'` : 'null'},`)
  }
  lines.push('} as const', '')

  await writeFile(generatedMap, `${lines.join('\n')}\n`, 'utf8')
}

await assertFallbacksExist()
const { hqVariants, baseBuffer } = await reconstructRasterMasters()
await generateContextualMasters(hqVariants, baseBuffer)

for (const variant of variants) {
  if (!hqVariants.has(variant)) throw new Error(`Missing high-resolution Bag Z master: ${variant}`)
}

await writeGeneratedSourceMap(hqVariants)
console.log(`Bag Z asset map ready. HQ variants: ${variants.join(', ')}`)
