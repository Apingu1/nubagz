# Bag Z master assets

This directory stores source-safe chunks for genuine high-resolution Bag Z artwork.

## Why chunks?

The approved artwork is binary AVIF data. Keeping it as numbered base64 text chunks makes the asset reproducible through GitHub text-file operations without running image resampling during the frontend build.

## Naming

Use:

```text
<variant>.01.part
<variant>.02.part
<variant>.03.part
...
```

Supported variants are `base`, `hello`, `detective`, `wallet`, `loot`, `security`, `warning`, `confused`, `sleepy`, and `victory`.

The build script concatenates each variant's chunks in numeric order, base64-decodes the result, validates the AVIF container and requires a minimum 1254×1254 master resolution before publishing it to `public/bag-z-hq/`.

## Build behaviour

- `base` is the canonical master and is mandatory.
- Incomplete or invalid optional contextual masters are skipped safely instead of breaking the application.
- Large mascot placements prefer a validated HQ contextual master when one exists; otherwise they use the canonical HQ `base` master rather than stretching a low-resolution image.
- Small contextual states can continue to use the existing `public/bag-z/*.webp` fallbacks until their genuine masters are supplied.
- Generated delivery assets and the generated TypeScript source map are intentionally gitignored and recreated by `npm run prepare:bag-z` / `npm run build`.

Do not create an "HQ" variant by enlarging a low-resolution WebP. Add the genuine master instead.
