# Clone / design-system fidelity review — visual_qa_cjk

## Recommendation

**REQUEST_CHANGES**

The rendered 16:9 demo is visually successful as an inspiration/translation of the Firecrawl sequence: it uses live DOM, retains the kt cloud console frame, has the white hairline-grid Research surface, orange search/citation semantics, a three-card progression, and a valid query → loading → revealed-abstract sequence. Korean is clear at the intended 1920×1080 delivery size, with no observed clipping, tofu, or one-character orphaning.

It does not, however, meet the repository's stated token-driven design-system contract. Several Research-specific colors, opacity values, type sizes, spacing values, radii, shadows, and the Research card gradient remain hard-coded at use sites rather than being named tokens. Under the required fidelity-review criteria, that is a HIGH blocker even though the rendered video appearance is good.

## Evidence inspected

- Reference: `tmp/firecrawl-reference/frame-0.png` through `frame-5.png` (1152×720 RGB), plus `firecrawl-linkedin.mp4.png`.
- Full fresh state set: `tmp/ai-foundry-full-qa/01-tg.png` through `21-loop-end.png`; each verified as 1920×1080 RGB PNG. Directly viewed all 21 and `contact-sheet.png`.
- Responsive captures: `tmp/ai-foundry-research-final/375.png`, `768.png`, `1280.png`, and `1920.png`; directly viewed all four.
- Encoded video: `tmp/ai-foundry-video-verify/contact-sheet.png` and all eight decoded frames; each decoded frame verified as 1920×1080 RGB PNG and directly viewed.
- Source and contract: `ai_foundry_research_ui/AI_Foundry_RAG_Suite_Research_적용본.html`, `ai_foundry_research_ui/DESIGN.md`.
- Freshness: source HTML modified `2026-08-14 13:38:10`; full-state contact sheet modified `13:38:37`; encoded-video contact sheet modified `13:41:47`.
- Browser recheck: unavailable in this runtime, so the claimed empty-console-error result could not be reproduced; this is not treated as product proof.

## Findings

### CRITICAL

None. The source constructs the visible Research surface from live elements (`article`, `div`, `span`, inline SVG) and CSS. No raster screenshot, canvas, or UI-replacing `background-image` is used. The only `background-image` is the CSS hairline grid/neutral texture at [AI_Foundry_RAG_Suite_Research_적용본.html:161](/Users/jason0706.kim/ai-workspace/ai_foundry_research_ui/AI_Foundry_RAG_Suite_Research_적용본.html:161), which is a legitimate decorative layer rather than a substitute UI.

### HIGH

- [product] **Token system is incomplete in the newly introduced Research UI.** The contract requires colors, spacing, and typography to trace to tokens ([DESIGN.md:7](/Users/jason0706.kim/ai-workspace/ai_foundry_research_ui/DESIGN.md:7), [DESIGN.md:35](/Users/jason0706.kim/ai-workspace/ai_foundry_research_ui/DESIGN.md:35), [DESIGN.md:60](/Users/jason0706.kim/ai-workspace/ai_foundry_research_ui/DESIGN.md:60)), but Research styles contain one-off values: `#FFD5C5`, `23px`, `12.5px`, `10.5px`, `16px`, `88px`, `18px`, fixed shadows, and raw `rgba(...)` values at [AI_Foundry_RAG_Suite_Research_적용본.html:166](/Users/jason0706.kim/ai-workspace/ai_foundry_research_ui/AI_Foundry_RAG_Suite_Research_적용본.html:166)–[194](/Users/jason0706.kim/ai-workspace/ai_foundry_research_ui/AI_Foundry_RAG_Suite_Research_적용본.html:194). The Research catalog card also hard-codes its gradient and accent color at [AI_Foundry_RAG_Suite_Research_적용본.html:415](/Users/jason0706.kim/ai-workspace/ai_foundry_research_ui/AI_Foundry_RAG_Suite_Research_적용본.html:415). Define semantic color/type/space/radius/elevation tokens in `:root` and in `DESIGN.md`, then consume them at these sites.

### MEDIUM

None.

### LOW

- [evidence] **Browser-console proof is packet-only.** The local browser controller reported no available browser, so I could not independently repeat the empty-console-error claim. Supply a fresh browser console log or automated capture output alongside the image set if reproducible console proof is required.
- [product] **Mobile captures are intentionally letterboxed rather than reflowed.** At 375×667 and 768×1024 the whole 1920×1080 composition scales down and is not legible as a mobile application. This matches the explicit fixed-video accepted debt and preview-scaling contract ([DESIGN.md:79](/Users/jason0706.kim/ai-workspace/ai_foundry_research_ui/DESIGN.md:79), [DESIGN.md:88](/Users/jason0706.kim/ai-workspace/ai_foundry_research_ui/DESIGN.md:88), [DESIGN.md:183](/Users/jason0706.kim/ai-workspace/ai_foundry_research_ui/DESIGN.md:183)) and is therefore not a blocker for the requested 16:9 demo.

## Visual/CJK assessment

- **Layout grammar:** Pass. The result adapts rather than copies the reference: kt cloud's navy shell remains, while the modal adopts the reference's white grid, centered search console, orange CTA, three stacked paper cards, loading dots, and orange left citation bars.
- **Motion/state coverage:** Pass on supplied evidence. The complete Research progression is represented in captures 17–20: entry page, typed query, loading dots, and settled abstracts. Source timing drives those same live nodes at [AI_Foundry_RAG_Suite_Research_적용본.html:771](/Users/jason0706.kim/ai-workspace/ai_foundry_research_ui/AI_Foundry_RAG_Suite_Research_적용본.html:771)–[792](/Users/jason0706.kim/ai-workspace/ai_foundry_research_ui/AI_Foundry_RAG_Suite_Research_적용본.html:792). The encoded 132s Research frame agrees with the source capture's settled state.
- **CJK:** Pass at 1920×1080. The Korean Research description, modal explainer, query, footer, and all earlier RAG scenes display fully with no visible clipping, glyph fallback, or semantic orphan wrap. The PII scene uses synthetic `example.go.kr` data and demonstrates replacement tokens rather than exposing a real identifier.
- **Video parity:** Pass on the supplied decoded samples. The eight frames show the same shell, hierarchy, Korean rendering, and Research final state as the HTML captures; no black/partial compositing artifact is visible.

## Blockers

1. Replace the Research UI's hard-coded visual values with documented semantic tokens. This is required before approval.

