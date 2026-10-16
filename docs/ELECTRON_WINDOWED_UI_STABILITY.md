# Windowed monitoring layout stability

## Result and scope

Targeted student-renderer CSS fix completed. Fourteen focused Playwright tests and the affected student source build passed. No real devices, native protection, teacher dashboard changes, detector changes, packaging or public networking were used. Earlier protected-mode source/build identities are invalidated; no native audit was run.

The supplied 5.38-second video was sampled before editing. It shows a windowed monitoring pane with nested scrollbars, then a maximized view. Filming introduces perspective movement, moire and doubled edges; those are not treated as measured application movement. Synthetic renderer measurements reproduce layout instability independently. This does not establish that every physical jitter visible in the video is fixed.

## Reproduction and cause

The actual LiveExam renderer was exercised through its mocked backend contract, including synthetic 1280x720 JPEG preview frames, timer/quiz UI, warning activation, repeated updates of one event ID, additional observations, warning closure and a second active event. No detector simulation changed production detection rules.

1. At <=780px, the legacy `.monitor-panel` two-column grid still applied inside the newer, already narrow `.live-exam-grid` sidebar. Its children (preview dock, teacher status, monitoring, audio and warning) were auto-placed into these tiny columns. At a 600px viewport the preview was only 75.59px wide, and its inherited 150px minimum height overrode the intended 16:9 shape.
2. The warning slot had only a minimum height. Wrapped warning text expanded it from 108px to 284.48px, moving the recent-observations section by 176.48px. The growing recent list changed the sidebar's scrollable extent even at larger widths. This can alter scrollbar presence, wrapping and the geometry of the sticky preview/scroll region.
3. The existing event cache and React keys preserve event identities. Sustained-warning and preview DOM identity checks passed; no warning-animation restart was reproduced. The native-quiz preview has no ResizeObserver. The observer in ExternalExam controls external-exam bounds, outside this native-quiz reproduction. No event-driven focus or scrollIntoView behavior was found in the affected path. No remount, detector or IPC-rate changes were needed.

Matched English measurements, CSS pixels (same synthetic sequence and user-scroll phase):

| Viewport | Preview before | Preview after | Panel scrollHeight before | After |
| --- | --- | --- | --- | --- |
| 600x620 | 75.59x150 | 225x126.56 | 648–1121 | 885, constant |
| 1100x720 | 355.80x200.13 | 340.80x191.69 | 698–961 | 949, constant |

At 1920x1080 the original panel extent also grew from 754 to 1017px as observations accumulated. In all final cases the reserved warning height is 156px and recent-observations height is 240px. Preview bounds, warning/list region bounds, quiz/timer bounds, document scrollTop, sidebar scrollTop and document scrollHeight remain stable during updates (bounds tolerance <1px). Explicit user scrolling establishes a new baseline rather than being undone. `comparison.json` and per-case `measurements.json` under `build/ui-jitter/` preserve the underlying values.

## Exact changes

- `desktop/src/styles.css`: scope the live monitoring sidebar to one column; maintain preview 16:9 without the incompatible minimum height; reserve scrollbar gutters and disable anchoring for changing monitoring content; reserve warning and observation regions with overflow scrolling rather than hiding their contents; reserve status-line height. At narrow widths give the sidebar 240px; at <=560px use a normal single-column layout so controls are not squeezed. Existing colors, typography and component appearance remain.
- `desktop/tests/ui/live-teacher.spec.ts`: add twelve layout cases (360x640, 600x620, 1100x720, 1920x1080; EN/RU/KK), synthetic image frames, event lifecycle updates, DOM identity checks, scroll and bounds measurements, resize/maximized-size transitions, no-horizontal-overflow assertions, screenshots and no-capture/start-command assertions.
- This report.

Warnings and all five existing recent-observation rows remain accessible by scrolling. The main monitor retains its sticky preview at supported side-by-side widths. Very narrow layouts deliberately use normal page scrolling instead of a cramped sticky column.

## Verification

Before-fix run with the original stylesheet: all three matched English cases failed the expanded geometry assertions; all narrow EN/RU/KK cases had also failed the initial comparison. The original CSS was restored only for this bounded comparison, and the fix was restored in a finally block.

Final command, run from desktop:

```
node node_modules/@playwright/test/cli.js test live-teacher.spec.ts -g "monitor layout stability|webcam preview stays|native quiz interaction" --output=../build/ui-jitter/verified-after
npm.cmd run build
```

Result: **14/14 passed** (12 new layout cases plus two existing preview/quiz regressions); TypeScript, Vite and Electron source bundling passed. Existing Vite future-loader/chunk-size warnings remain. An initial build caught a test-only string-index typing error, corrected with a literal tuple annotation; the final build passed. No broad test suite was run.

Visual inspection: inspected rendered narrow English/Russian and 360px Kazakh screenshots. Fixed previews have the correct shape; translations wrap, controls stay readable and horizontal overflow is absent. Browser tests use Edge/Chromium and the real student React UI, not a newly launched native Electron window or real capture. Native compositor/driver behavior is therefore not physically verified.

Evidence:

- `build/ui-jitter/measured-before/`: matched original-CSS screenshots and measurements.
- `build/ui-jitter/verified-after/`: final screenshots and measurements.
- `build/ui-jitter/measured-before.log`, `verified-after.log`, `build.log`.
- Supplied-video sample frames: `build/ui-jitter/video-*.jpg`.

## Optional manual confirmation

With separate approval before any camera/microphone launch, run an unprotected student exam in a small resizable window. Trigger one harmless observation, allow it to clear, scroll both the page and monitoring panel, then maximize and restore. Confirm the preview and controls do not jump as updates arrive, and warning/history content remains reachable. Do not run native protection tests for this change. No physical confirmation was launched in this task.
