# Bag Z master assets

This directory stores the canonical high-resolution Bag Z source in source-safe chunks.

## Canonical master

The approved Bag Z artwork is binary AVIF data. Keeping it as numbered base64 text chunks makes the 1254×1254 source reproducible through GitHub text-file operations without image resampling during the frontend build.

Use:

```text
<variant>.01.part
<variant>.02.part
<variant>.03.part
...
```

The canonical `base` master is mandatory. The build concatenates its chunks in numeric order, base64-decodes the result, validates the AVIF container and enforces a minimum 1254×1254 resolution before publishing it to `public/bag-z-hq/base.avif`.

## Phase 2 contextual masters

The site supports `base`, `hello`, `detective`, `wallet`, `loot`, `security`, `warning`, `confused`, `sleepy`, and `victory`.

To keep every large Bag Z composition sharp and character-consistent without ever enlarging the old thumbnail WebPs, `scripts/prepare-bag-z.mjs` now builds contextual HQ compositions from the genuine canonical master. Each generated 1254×1254 SVG embeds the full-resolution AVIF character and adds crisp mode-specific vector artwork:

- `hello` — welcome/wave energy
- `detective` — magnifying glass and scanner treatment
- `wallet` — wallet/card treatment
- `loot` — reward bag and coin treatment
- `security` — trust shield/check treatment
- `warning` — alert/warning treatment
- `confused` — question/empty-state treatment
- `sleepy` — idle/night treatment
- `victory` — trophy/confetti treatment

This makes the contextual masters resolution-independent at display time while preserving the exact approved Bag Z face, proportions, markings, cross-body bag and Z gem.

If a genuine standalone 1254×1254 contextual AVIF is added later as numbered chunks, it automatically takes priority over the generated vector composition for that variant.

## Build behaviour

- `base` is mandatory and build-failing if invalid.
- Genuine contextual AVIF chunks are validated at the same 1254px floor when present.
- Missing contextual rasters are generated as HQ SVG compositions from the canonical master.
- The generated TypeScript asset map points all ten variants at HQ assets, so large heroes and smaller mascot states no longer need to stretch the low-resolution WebPs.
- `public/bag-z/*.webp` remains only as a defensive runtime fallback.
- Generated delivery assets are recreated by `npm run prepare:bag-z` / `npm run build` and are intentionally not hand-maintained.

Do not create an "HQ" variant by resizing a low-resolution WebP.
