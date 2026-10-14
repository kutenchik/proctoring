# Local Proctoring — desktop design system

Stage 1, reference-led. The supplied Willow Kennels reference contributes warmth,
rounded typography, sand surfaces, moss actions and measured spacing. It does not
contribute branding, imagery, website sections or claims.

## Workflow and decisions

Installed skill: `C:/Users/kuten/.codex/skills/ui-ux-pro-max/SKILL.md`.
Actual search: `scripts/search.py "education desktop exam calm" --design-system`.
Its landing-page pattern did not fit. One narrower retry, `desktop application
workflow`, also returned marketing structure. Neither unverified pattern/palette
was persisted. This master instead applies the user's specified reference and
the skill's verified accessibility/interaction principles. No previous master existed.

Relevant successful searches: `forms validation keyboard focus --stack shadcn`,
`error summary validation --domain ux`, and `memo rerender --stack react` (retry
after no results for live meters). Apply associated errors, dialog focus trapping,
visible focus and isolated live rendering. General web/native guidance is adapted
to Windows desktop, not imposed as mobile navigation or marketing layouts.

## Tokens

Canonical starting palette (HSL only): background `40 36% 96%`; foreground
`120 16% 17%`; primary `120 30% 34%`; primary foreground `40 36% 97%`;
muted foreground `120 6% 45%`; border `38 18% 87%`; card `40 38% 92%`;
warm decorative accent `28 76% 58%`. Define darker secondary text where necessary
to achieve 4.5:1 on sand cards. Essential input borders need 3:1; quiet decorative
borders do not carry control/state meaning. Warning text is dark amber, never the
decorative accent alone. Error text is dark red. Disabled/unavailable have words
and icons, not just color. Verify computed colors in frontend tests.

Nunito 700/800 headings, Inter 400/500/600 body. Bundle Latin, Cyrillic and
Cyrillic-extended subsets locally; verify Kazakh Ә Ғ Қ Ң Ө Ұ Ү Һ І coverage.
Headings 26–34px, sections 18–22px, body/controls 14–16px. Tabular numerals for
time and measurements. Spacing 4/8px rhythm, cards 18px, controls 11px.

## Layout and behavior

Compact product/stage/language/status header. Setup stepper, no dashboard sidebar.
Devices before registration; consent before explicit camera or audio activation.
Two columns where useful, stack naturally at effective smaller viewports. No fixed
footer hiding content. Exam questions take priority over compact monitoring.
No automatic horizontal scrolling. State previews remain visibly labeled fixtures.
Unconnected real actions stay disabled with a reason.

Use lucide icons, shadcn/Radix accessible primitives themed with these tokens,
semantic form controls and associated inline errors. Motion only short opacity or
transform transitions; honor reduced motion and stop decoration in exam fixtures.
No live-region announcements for timer ticks/meters. Language changes retain fields.
Preview and audio meters subscribe independently from page state.

## Verification targets

1280×720, 1366×768, 1920×1080; equivalent effective viewports at 125/150/200%
scaling. EN/RU/KK, keyboard focus, disconnected/empty/error states and reduced
motion. Inspect actual screenshots, not only DOM assertions. No fake health,
gaze success, exam completion, scores or protected status in live mode.

## Stage 2 application

Reuse these tokens and existing screens. The installed skill's focused
`keyboard focus modal --stack shadcn` search returned Radix dialog focus trapping
and modal-content guidance. Apply it to real PIN actions, with explicit native
external-view hiding because DOM z-index cannot cover a WebContentsView. Keep
collection readiness, accepted samples and fitted calibration separate. Only
backend state may move the real workflow; preview fixtures remain isolated.
