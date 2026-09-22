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

### Phase 2 — Native Google Slides rebuild (polished, editable)
- [ ] Confirm target deck (existing URL or new) + Google auth
- [ ] Recreate diagram as native Slides shapes + text via google-slides skill
- [ ] Match Superior Plus brand (#174086 blue, #E21836 red, #FFCA37 yellow) + POC tags
- [ ] Verify in-deck at present + zoom

## Review
(to fill in)
