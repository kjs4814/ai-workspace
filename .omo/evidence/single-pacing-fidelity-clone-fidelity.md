# Clone Fidelity Review — AI Foundry Rerank Single Scene

**Verdict:** PASS  
**Confidence:** HIGH  
**Scope:** Independent read-only visual fidelity / Korean-CJK pacing pass for the 30-second single-scene Rerank video.

## Evidence inspected

- Design contract: `ai_foundry_service_ui_reference/DESIGN.md`, especially the 2026-08-14 actual-console pacing revision.
- Render source: `ai_foundry_service_ui_reference/AI_Foundry_RAG_Suite_실제콘솔_단일호흡.html` (all 226 lines).
- Reference captures: `tmp/console-reference-mov-verify/화면 기록 2026-08-14 14.13.15.mov.png`, `decoded/frame-01-0000.5s.png`, and `decoded/frame-02-0025.0s.png`.
- Full HTML state sequence — all 10 RGB 1920×1080 PNGs: `tmp/ai-foundry-single-pacing-qa/01-query.png` through `10-hold.png`.
- Responsive final-state evidence — all 4 RGB PNGs: `tmp/ai-foundry-single-pacing-responsive/375x211.png`, `768x432.png`, `1280x720.png`, and `1920x1080.png`.
- Decoded video evidence — all 8 RGB 1920×1080 PNGs: `tmp/ai-foundry-single-pacing-video-verify/frame-01-000.5s.png` through `frame-08-029.5s.png`.
- MP4 artifact: `output/AI_Foundry_RAG_Suite_실제콘솔_단일호흡.mp4` (ISO MP4, 1,903,401 bytes). The supplied metadata states 30.000 seconds, 1920×1080, 30 fps, no audio. Native `ffprobe` is unavailable in this environment, so those stream fields were not independently re-read.

All supplied PNGs have valid PNG signatures and the expected dimensions. The HTML source modification time (14:27:30) precedes the HTML-capture set (14:27:46); the encoded MP4 (14:28:03) precedes its decoded-frame set (14:28:10–11). Thus the visual evidence is fresh relative to the inspected source.

## Evidence trace

| Artifact | Direct visual finding |
|---|---|
| Reference still + 0.5s | Establishes the borrowed grammar: wide off-white guided canvas, a centered floating surface, abundant negative space, and no camera move. It is treated as composition/motion reference only. |
| Reference 25.0s | Establishes a quiet, readable three-card resolved stack and a sustained end hold. Its Firecrawl copy/skin is absent from the implementation. |
| HTML 01-query | One populated Korean Rerank query card, `/v1/rerank`, and navy `재정렬`; no shell, caption, brand lockup, or browser chrome. |
| HTML 02-click | The only cursor is stationary on the submit button. |
| HTML 03-processing | Query surface is gone; only the three-dot loader remains on the same guide canvas. |
| HTML 04-card-one-title | First card exposes source, title, score, and three dots before any body. |
| HTML 05-card-two-title | Second title card joins while first remains in loading state; no result body leaks early. |
| HTML 06-three-titles | All three source/title-only cards and their loaders are shown before body resolution. |
| HTML 07-first-body | First body resolves while cards two and three retain dots. |
| HTML 08-second-body | Second body resolves while the third retains dots. |
| HTML 09-all-bodies / 10-hold | Three complete cards remain in a stable readable stack; 10-hold shows no end-card/transition. |
| Responsive 375×211 / 768×432 / 1280×720 / 1920×1080 | The fixed 16:9 stage scales proportionally; all final Korean text stays within card boundaries, with no clipped glyphs, orphaned CJK fragments, or overflow. |
| Video 0.5s / 4.2s / 5.1s | Query, stationary cursor click, then isolated loader occur without a cut. |
| Video 6.5s / 8.4s | First title-only card, then all three title-only cards appear in the stated order. |
| Video 13.4s / 16.3s / 29.5s | Bodies resolve rank-order; all content is complete by 16.3s and the 29.5s frame is the same still final composition. No rendered player controls, captions, or overlay UI are present. |

## Findings

### CRITICAL

None. The scene is a live DOM tree: query control, button, `role=status` loaders, ordered-list result cards, text, and SVG cursor are defined in source lines 72–113. There is no image/canvas/video substitute for the console component.

### HIGH

None. The result is token-driven: canvas, guide, width, radius, shadow, console colors, font stacks, and motion are declared in `:root` and applied through variables (source lines 9–25, 30–55). The cards are repeated `<li class="result-card">` primitives rather than a pasted final-state image.

### MEDIUM

None. The guide canvas, single centered component/stack, relative scale, faint grid-plus-dot treatment, one-action staging, title-before-body ordering, and long resolved hold match the reference grammar while retaining AI Foundry’s navy/Korean console vocabulary.

### LOW

None. Korean metadata, titles, and body copy are fully legible at the native stage and proportional responsive previews; no CJK clipping, tofu, anomalous break, or detached line was observed.

## Implementation checks supporting the visual result

- The stage is a 1920×1080 clipped surface with sparse guide/grid and central dot field (source lines 30–36), and its fixed composition scales without reflow (lines 133–137).
- The user-visible scene contains no sidebar, browser chrome, logo lockup, caption, or editorial overlay. The local recording harness is separate (`#ui`, lines 117–123) and the record action hides it before render (line 213); it is absent in every decoded MP4 frame.
- The state harness is explicit: cursor only from 3.55–4.58s, loader at 4.5–6.34s, entries at 6.2/7.1/8.0s, and bodies at 10.2/12.9/15.6s (lines 154–183). This agrees with the visual evidence and keeps the cursor stationary.
- Reduced motion removes cursor/ripple and all transform motion while retaining final state visibility (lines 64–67, 179–183).
- No Firecrawl name, orange skin, English query, paper titles, or reference content occurs in either inspected implementation HTML copy.

## Blocking items

None.
