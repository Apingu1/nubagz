import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'
import sharp from 'sharp'

const variants = ['base','hello','detective','wallet','loot','security','warning','confused','sleepy','victory']
const root = process.cwd()
const inputDir = resolve(root, 'public/bag-z')
const outputDir = resolve(root, 'public/bag-z-hq')
await mkdir(outputDir, { recursive: true })

for (const variant of variants) {
  const input = resolve(inputDir, `${variant}.webp`)
  const output = resolve(outputDir, `${variant}.webp`)
  await sharp(input)
    .resize({ width: 1024, height: 1024, fit: 'inside', withoutEnlargement: false, kernel: sharp.kernel.lanczos3 })
    .sharpen({ sigma: 1.05 })
    .webp({ quality: 96, alphaQuality: 100, smartSubsample: true })
    .toFile(output)
  console.log(`[Bag Z] built ${variant} -> 1024px delivery asset`)
}
