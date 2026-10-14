# Desktop dependencies and local assets

The exact JavaScript dependency graph is pinned in `package-lock.json`. Install
from the official npm registry with `npm ci --ignore-scripts=false`; no global
packages are required. Electron's official install script obtains its runtime;
if local npm policy suppresses scripts, the native shell cannot launch until
that prerequisite is completed.
The implementation was built with Node 24.16.0 and npm 11.13.0. It does not change
the Python dependency lockfile or the existing release executable.

Nunito and Inter are bundled from `@fontsource-variable/nunito` 5.3.0 and
`@fontsource-variable/inter` 5.3.0. Their SIL Open Font License texts are retained
in `public/licenses/` and copied into the built renderer. Fonts load locally,
including Cyrillic and the Kazakh characters tested by the UI suite.

Icons come from `lucide-react` 1.55.0 (ISC); interface primitives follow
shadcn/ui patterns and use Radix Dialog/Slot (MIT). The preview portrait is a
simple local CSS illustration, not a webcam recording or a student photograph.

Primary implementation references:

- [Electron security checklist](https://www.electronjs.org/docs/latest/tutorial/security)
- [Electron context isolation](https://www.electronjs.org/docs/latest/tutorial/context-isolation)
- [WebContentsView for future isolated external exams](https://www.electronjs.org/docs/latest/api/web-contents-view)
- [Vite runtime requirements](https://vite.dev/guide/)
- [shadcn/ui with Vite](https://ui.shadcn.com/docs/installation/vite)
- [Motion for React](https://motion.dev/docs/react)

Installation can require network access. The built renderer's fonts, icons,
styles and fixtures are local. Stage 1 does not embed remote exams or package a
Windows executable; those remain later migration stages.
