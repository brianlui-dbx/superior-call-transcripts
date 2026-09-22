# Task: Better Google Slides rendering for superior_arch_cio

## Problem
- 12000×6750 PNG looks blurry in Google Slides. Root cause: Slides downsamples
  images past ~4000px wide with a low-quality resampler → oversized PNG is softer,
  not sharper. Also the WeasyPrint export path substitutes Verdana for the brand
  fonts (Montserrat + Open Sans).
- SVG/PDF can't be inserted as vectors in Slides (confirmed by user).

## Chosen approach: BOTH
### Phase 1 — Right-sized, correctly-fonted PNG (quick drop-in) ✅ DONE
- [x] Render at the size Slides actually displays — 3333×1875 (2.5×, under ~4000px), native, no upscale
- [x] Fix fonts: real Chrome loads Montserrat + Open Sans + DM Mono from Google Fonts link
- [x] Used chrome-devtools MCP (headless Chrome CLI crashes here); WeasyPrint fallback not needed
- [x] Verified visually: fonts correct, blue POC tags on all 4 shapes, ontology box contained, crisp
- Output: docs/superior_arch_cio.png (627 KB)

### Phase 2 — Native Google Slides rebuild (polished, editable) ✅ DONE
- [x] New deck, Google auth via CLI path (gcloud ADC + quota project)
- [x] Extracted exact DOM geometry from live Chrome (boxes/text/styles/graph) → docs/_arch_geom.json
- [x] Built native slide with python-pptx (1 CSS px = 9144 EMU at 13.333×7.5"), brand fonts,
      composited dark-row rgba to solid, synthesized 10 ontology connectors, embedded rasterized icons
- [x] Uploaded PPTX to Drive WITH conversion → native, editable Google Slides (no image hosting needed)
- [x] Thumbnail QA loop (4 passes): fixed Lakeflow icon overlap, single-line wrap (Superior badge),
      source-pill dot overlap
- Deck: https://docs.google.com/presentation/d/1-RdUmgf5LiS2VC08fR8lIHDYbs4IMjGoP55nNbqYjAA/edit
- Source artifacts: docs/build_arch_pptx.py, docs/_arch_geom.json, docs/superior_arch_cio.pptx

## Review
- PNG (Phase 1): docs/superior_arch_cio.png @ 3333×1875 via chrome-devtools MCP at 2.5× — crisp,
  correct fonts, under Slides' downsample threshold. Drop-in image.
- Native (Phase 2): editable Google Slides deck, vector-crisp at any zoom, on-brand fonts/colors.
- Key learning: bigger PNG is WORSE in Slides (it downsamples >~4000px). SVG/PDF can't be inserted
  as vectors; private Drive images can't be used by Slides createImage (needs public URL) — so the
  PPTX→Drive-convert path (embeds images) is the right way to a native deck without violating the
  no-public-sharing policy. Deck left private (not shared).
