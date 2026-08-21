# ai-workspace

Working repository for kt cloud AI video and document production tooling.

## Contents

### `html_to_mp4/`
Scripts that turn a static HTML page into an MP4.

| File | Role |
| --- | --- |
| `render_html.js` | Renders an HTML page to a numbered PNG frame sequence |
| `record_realtime.js` | Captures a page in real time rather than frame-by-frame |
| `encode_frames.swift` | Encodes a frame sequence into H.264 MP4 via AVFoundation |
| `verify_video.swift` | Decodes the result and checks for black or uncomposited frames |

Compiled binaries land in `html_to_mp4/bin/` and are not tracked.

### `.omo/evidence/`
QA gate reviews and clone-fidelity reports from past video renders. Each
record states the outcome, the blockers found, and where they were fixed.
Kept as a written trail of what passed review and why.

### `output/`
Finished deliverables. Currently `kt_cloud_RAG_Suite_AI_Chat_51s.mp4`.

## Conventions

Product naming follows the kt cloud AI naming rules: the formal product
name is **RAG Suite**; externally it is referred to as **kt cloud AI API**.

## Build artifacts

`.gitignore` excludes Swift module caches (`**/.module-cache/`),
`**/node_modules/`, `videokit/swift/.build/`, `html_to_mp4/bin/`, and the
`tmp/` and `dist/` scratch directories. These regenerate on build and had
previously bloated the repository, so keep them out of the index.
