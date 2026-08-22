# Bag Z legacy master archive

This directory is retained from the original Bag Z art-pack branch as a source/reference archive only.

It is **not** the active website delivery source and is no longer read, reconstructed, composited, or transformed by the frontend build.

The single canonical website implementation is now the authoritative bespoke premium AVIF set committed directly under:

```text
frontend/public/bag-z-premium/
```

Active variants are `base`, `hello`, `detective`, `wallet`, `loot`, `security`, `warning`, `confused`, `sleepy`, and `victory`.

`npm run prepare:bag-z` now validates those committed AVIF binaries against the final handoff SHA-256 hashes and requires exact 1254×1254 dimensions. It does not generate artwork.

The small files under `frontend/public/bag-z/*.webp` are retained only as emergency runtime fallbacks. They are never the primary premium hero artwork.
