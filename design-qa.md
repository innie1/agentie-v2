# Agentie reference-layout design QA

- Source visual truth: `C:\Users\user\AppData\Local\Temp\codex-clipboard-6209d927-3cb1-4069-884b-3d726ab1b441.png`
- Implementation screenshot: `C:\Users\user\Documents\Codex\2026-08-24\referenced-chatgpt-conversation-this-is-an-4\agentie-v2\implementation-reference-layout.png`
- Combined comparison: `C:\Users\user\Documents\Codex\2026-08-24\referenced-chatgpt-conversation-this-is-an-4\agentie-v2\design-qa-comparison.png`
- Viewport: 1917 × 1011 CSS px at device scale factor 1
- Source pixels: 1917 × 1011
- Implementation pixels: 1917 × 1011
- State: dark desktop app, Computer panel open, real Computer error/retry state

## Full-view comparison evidence

The implementation follows the source's three-column hierarchy: a dark conversation/agent rail at left, a large restrained chat workspace in the center, and a persistent Computer surface at right. The column proportions, thin separators, compact top bars, bottom-anchored rounded composer, low-chrome black palette, and geometric avatar treatment are materially aligned. Agentie-specific labels and real runtime states replace the source product's names, subscription banner, and placeholder errors as requested.

## Focused comparison evidence

Focused review covered the left agent rail, center composer, and right Computer panel. Typography uses the existing Agentie system stack with comparable weight and hierarchy. Spacing is intentionally slightly roomier in the Agentie composer for accessibility. The right panel embeds the existing interactive noVNC Computer rather than a raster or simulated screen. No source imagery or proprietary logo was copied.

## Required fidelity surfaces

- Fonts and typography: passed; system sans-serif hierarchy, weights, truncation, and contrast are consistent with the reference while retaining Agentie copy.
- Spacing and layout rhythm: passed; 19.2% / flexible center / 25% desktop structure, compact bars, separators, and bottom composer match the reference hierarchy.
- Colors and visual tokens: passed; near-black surfaces, charcoal selected states, subtle borders, white primary text, and muted secondary text are aligned.
- Image quality and asset fidelity: passed; no source images were required. The real live Computer iframe is preserved. Avatars use Agentie's generated colors with the requested geometric mask.
- Copy and content: passed; copied subscription, error, and bot placeholder text was excluded. Visible errors are genuine runtime errors.

## Interaction verification

- Company Computer panel opens from the top-bar control.
- Company Computer panel closes immediately with `×` and chat expands into the released space.
- Starting state recovers by retrying the real display connection after a stuck-ready response.
- A failed runtime now shows the real failure and retry action instead of claiming the Computer is ready.
- Browser console: no warnings or errors from the rebuilt UI.

## Comparison history

1. P1: the original Computer close action waited on shutdown and left the card visible. Fixed by making `×` dismiss the view immediately; browser evidence confirms the panel is removed and chat expands.
2. P1: the Computer could remain on `Starting Computer` after a ready response. Fixed with a guarded display reconnect and by preventing the backend from reporting ready without a reachable display.
3. P2: the existing Agentie layout did not preserve the source's persistent right Computer region. Fixed with the 19.2% / flexible / 25% desktop grid and docking of the real Computer component.

## Follow-up polish

- P3: replace remaining legacy emoji tool glyphs with the project's eventual production icon set when that dependency is selected.
- P3: populate agent rows in the isolated QA server to compare dense-list wrapping; the user's normal workspace already supplies these real rows.

final result: passed
