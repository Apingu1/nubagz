import { createHash } from 'node:crypto'
import { readFile, readdir, stat } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(here, '..')
const requestedDir = process.argv[2] ?? 'public/bag-z-premium'
const assetDir = path.resolve(frontendRoot, requestedDir)

const expected = {
  base: '7b3ead2c8693fee55e4ed1321b026ce361f2da460dfee7afc6a048cedf3a979d',
  hello: 'bc973909a7a88b17cc248c6586674720864f0323d6a5745eb029217375ed59e1',
  detective: '57c53de5bf3f064f6e8bc1b1db3c0222f4de259094aa13887d0e0c97469976b6',
  wallet: '47b98f02e0c0a5598bce91a92b20104216ddc8ac83d1120a883367f279e79979',
  loot: '34aee69704955aeb0932e1b61befd047371d3219fdaa0ce58905a1924d87d993',
  security: 'fa24ac97d0e31bf96f683d8d3903a0a4e0a3db30c4471859efe6831c5bbc2700',
  warning: '33d5faa6ab2a1e310a54453f170a30b990511a17f6134118b9fdf411f855f818',
  confused: '785629cec729864746d05c7bab908fe9c115cf51171c5b8242c1df80ae512216',
  sleepy: '27bae69bcc081601e487c07ea6a502ddade41b106382028f4285fa5eb5160c95',
  victory: 'c951fbc5385b1997efb39b6ef0593ce5e481f9c693501d301233dd91bb490161',
}

const forbiddenLegacyPaths = [
  'bag-z-master',
  'bag-z-masters',
  'bag-z-final-masters',
  'bag-z-premium-final',
  'bag-z-premium-hd',
  'bag-z-premium-masters',
  'bag-z-premium-v2',
  'public/bag-z',
  'public/bag-z-hq',
  'src/generated/bag-z-assets.ts',
]

async function assertLegacyPathsAbsent() {
  for (const legacyPath of forbiddenLegacyPaths) {
    try {
      await stat(path.resolve(frontendRoot, legacyPath))
    } catch (error) {
      if (error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT') continue
      throw error
    }
    throw new Error(`Obsolete Bag Z path must not exist: ${legacyPath}`)
  }
}

function readAvifDimensions(buffer, variant) {
  if (buffer.length < 32) throw new Error(`${variant}: AVIF is unexpectedly small`)

  const ftypIndex = buffer.indexOf(Buffer.from('ftyp', 'ascii'))
  if (ftypIndex < 4) throw new Error(`${variant}: missing ISO-BMFF ftyp box`)
  const ftypSize = buffer.readUInt32BE(ftypIndex - 4)
  const brandEnd = Math.min(buffer.length, ftypIndex - 4 + ftypSize)
  const brands = buffer.toString('ascii', ftypIndex + 4, brandEnd)
  if (!brands.includes('avif') && !brands.includes('avis')) {
    throw new Error(`${variant}: file does not advertise an AVIF brand`)
  }

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
      if (plausible && (!best || width * height > best.width * best.height)) {
        best = { width, height }
      }
    }

    cursor = index + marker.length
  }

  if (!best) throw new Error(`${variant}: could not read AVIF dimensions`)
  return best
}

async function validateVariant(variant, expectedSha256) {
  const file = path.join(assetDir, `${variant}.avif`)
  let info
  try {
    info = await stat(file)
  } catch {
    throw new Error(`${variant}: missing premium asset ${path.relative(frontendRoot, file)}`)
  }

  if (!info.isFile()) throw new Error(`${variant}: premium asset is not a file`)

  const buffer = await readFile(file)
  const sha256 = createHash('sha256').update(buffer).digest('hex')
  if (sha256 !== expectedSha256) {
    throw new Error(`${variant}: SHA-256 mismatch; expected authoritative handoff binary ${expectedSha256}, got ${sha256}`)
  }

  const { width, height } = readAvifDimensions(buffer, variant)
  if (width !== 1254 || height !== 1254) {
    throw new Error(`${variant}: expected exact 1254x1254 premium render, got ${width}x${height}`)
  }

  console.log(`Bag Z premium OK: ${variant}.avif — ${width}x${height}, ${buffer.length} bytes, sha256 ${sha256}`)
}

await assertLegacyPathsAbsent()

const entries = await readdir(assetDir)
const rejectedPremiumWebps = entries.filter((entry) => entry.toLowerCase().endsWith('.webp'))
if (rejectedPremiumWebps.length) {
  throw new Error(`Rejected legacy WebP files found in canonical premium directory: ${rejectedPremiumWebps.join(', ')}`)
}

for (const [variant, sha256] of Object.entries(expected)) {
  await validateVariant(variant, sha256)
}

const expectedFiles = new Set(Object.keys(expected).map((variant) => `${variant}.avif`))
for (const file of expectedFiles) {
  if (!entries.includes(file)) throw new Error(`Missing expected delivery asset: ${path.join(requestedDir, file)}`)
}

console.log(`Validated ${expectedFiles.size} authoritative Bag Z AVIF assets in ${requestedDir}.`)
