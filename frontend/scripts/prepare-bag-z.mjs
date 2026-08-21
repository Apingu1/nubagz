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
    if (offset + 8 > buffer.length) {
      throw new Error(`truncated ISO-BMFF box header at byte ${offset}`)
    }

    let size = buffer.readUInt32BE(offset)
    const type = buffer.toString('ascii', offset + 4, offset + 8)
    let headerSize = 8

    if (size === 1) {
      if (offset + 16 > buffer.length) {
        throw new Error(`truncated extended-size box ${type}`)
      }
      const extended = buffer.readBigUInt64BE(offset + 8)
      if (extended > BigInt(Number.MAX_SAFE_INTEGER)) {
        throw new Error(`box ${type} is too large to validate safely`)
      }
      size = Number(extended)
      headerSize = 16
    } else if (size === 0) {
      size = buffer.length - offset
    }

    if (size < headerSize) {
      throw new Error(`invalid box size ${size} for ${type}`)
    }

    const end = offset + size
    if (end > buffer.length) {
      throw new Error(`truncated ${type} box: expected ${size} bytes, only ${buffer.length - offset} remain`)
    }

    boxes.push({ type, offset, size })
    offset = end
  }

  if (offset !== buffer.length) {
    throw new Error(`ISO-BMFF parse ended at ${offset}, file length is ${buffer.length}`)
  }

  return boxes
}

function findLargestIspeDimensions(buffer) {
  const marker = Buffer.from('ispe', 'ascii')
  let cursor = 0
  let best = null

  while (cursor < buffer.length) {
    const index = buffer.indexOf(marker, cursor)
    if (index === -1) break

    // ispe is a FullBox: type (4), version/flags (4), width (4), height (4).
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

  if (!ftyp || !meta || !mdat) {
    throw new Error(`${variant}: reconstructed file is missing required AVIF boxes`)
  }

  const brandWindow = buffer.toString('ascii', ftyp.offset + 8, Math.min(ftyp.offset + ftyp.size, ftyp.offset + 40))
  if (!brandWindow.includes('avif') && !brandWindow.includes('avis')) {
    throw new Error(`${variant}: reconstructed file does not advertise an AVIF brand`)
  }

  const dimensions = findLargestIspeDimensions(buffer)
  if (!dimensions) throw new Error(`${variant}: could not read AVIF dimensions`)

  // The approved canonical Bag Z master is 1254px square. Requiring at least
  // that resolution prevents old 256/384px delivery images from being promoted
  // to "HQ" and still allows larger future masters.
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
    if (!info.isFile() || info.size < 1000) {
      throw new Error(`Invalid Bag Z fallback asset: public/bag-z/${variant}.webp`)
    }
  }
}

async function reconstructVariant(variant, chunks) {
  chunks.sort((a, b) => a.part - b.part)
  for (let i = 0; i < chunks.length; i += 1) {
    if (chunks[i].part !== i + 1) {
      throw new Error(`${variant}: master chunks are not contiguous from part 1`)
    }
  }

  const encodedPieces = []
  for (const chunk of chunks) {
    const text = (await readFile(path.join(masterDir, chunk.entry), 'utf8')).replace(/\s+/g, '')
    if (!/^[A-Za-z0-9+/=]+$/.test(text)) {
      throw new Error(`${variant}: ${chunk.entry} contains invalid base64 characters`)
    }
    encodedPieces.push(text)
  }

  const encoded = encodedPieces.join('')
  const buffer = Buffer.from(encoded, 'base64')
  const dimensions = validateAvif(buffer, variant)
  const output = path.join(hqDir, `${variant}.avif`)
  await writeFile(output, buffer)

  return { dimensions, bytes: buffer.length }
}

async function reconstructMasters() {
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

  for (const [variant, chunks] of grouped) {
    try {
      const { dimensions, bytes } = await reconstructVariant(variant, chunks)
      hqVariants.set(variant, dimensions)
      console.log(`Bag Z HQ: ${variant} -> ${dimensions.width}x${dimensions.height} (${bytes} bytes)`)
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)

      // The canonical base master is mandatory. Optional contextual masters can be
      // added incrementally; an incomplete transfer must never break the product.
      if (variant === 'base') throw error
      console.warn(`Bag Z HQ skipped: ${variant} (${message})`)
    }
  }

  return hqVariants
}

async function writeGeneratedSourceMap(hqVariants) {
  await mkdir(generatedDir, { recursive: true })

  const lines = [
    '// AUTO-GENERATED by scripts/prepare-bag-z.mjs. Do not edit by hand.',
    'export const bagZSources = {',
  ]

  for (const variant of variants) {
    const source = hqVariants.has(variant)
      ? `/bag-z-hq/${variant}.avif`
      : `/bag-z/${variant}.webp`
    lines.push(`  ${variant}: '${source}',`)
  }

  lines.push('} as const', '')
  lines.push('export const bagZHqSources = {')
  for (const variant of variants) {
    const source = hqVariants.has(variant)
      ? `'/bag-z-hq/${variant}.avif'`
      : 'null'
    lines.push(`  ${variant}: ${source},`)
  }
  lines.push('} as const', '')

  await writeFile(generatedMap, `${lines.join('\n')}\n`, 'utf8')
}

await assertFallbacksExist()
const hqVariants = await reconstructMasters()

if (!hqVariants.has('base')) {
  throw new Error('The approved high-resolution base Bag Z master was not reconstructed')
}

await writeGeneratedSourceMap(hqVariants)
console.log(`Bag Z asset map ready. HQ variants: ${[...hqVariants.keys()].join(', ') || 'none'}`)
