# Lessons

## Rendering HTML exhibits for Google Slides
- **Bigger PNG is worse.** Google Slides downsamples images past ~4000px on the long
  side with a low-quality resampler, so a huge export (e.g. 12000px) looks *blurrier*
  than a right-sized one. Target ~2.5–3× the nominal slide size (≈2666–3840px wide),
  rendered natively (no upscaling).
- **Fonts:** the headless-Chrome CLI crashes in this env (exit 134), and WeasyPrint
  substitutes Verdana for Montserrat/Open Sans. Use the **chrome-devtools MCP** instead:
  open the file, `emulate` viewport `1333x750x2.5`, reload, `take_screenshot fullPage`.
  Real Chrome loads the page's Google Fonts, so type is correct and layout is faithful.
- **SVG/PDF can't be inserted into Slides as vectors** (user confirmed). For a truly
  native/editable slide, build with **python-pptx** then upload to Drive **with
  conversion** (`mimeType: application/vnd.google-apps.presentation`). This embeds
  images as binary — no hosting needed.
- **Slides createImage refuses private Drive images** (needs a public URL), and the
  google-slides sharing policy forbids `anyone-with-link`. So don't host icons on Drive;
  embed them in the PPTX instead.
- **Slides re-wraps text to the box width on PPTX import**, ignoring the no-wrap flag.
  Widen single-line text boxes (extra empty width) so short labels never break.
- **Exact geometry beats guessing:** extract every element's box + computed style from
  the live DOM (chrome-devtools `evaluate_script`), then at 13.333×7.5" 1 CSS px = 9144
  EMU exactly — every element lands where the browser put it. Zero-thickness elements
  (connector `<line>`s) get filtered by a w/h>0 guard; synthesize those from node coords.
