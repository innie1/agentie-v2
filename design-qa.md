# Agentie Layout Design QA

- Source visual truth: the five user-supplied desktop, plugin, avatar, and mobile screenshots.
- Prototype captures: `work/layout-after-desktop-final.png`, `work/layout-computer-final.png`, `work/plugins-after-final.png`, `work/avatar-picker-final.png`, and `work/layout-after-mobile.png`.
- Tested states: expanded desktop navigation, collapsed navigation rail, computer panel open, plugin marketplace open, agent creation, empty composer, typed composer, and 390 × 844 mobile.

## Visual comparison

The implementation follows the supplied three-part desktop composition: a dark agent navigation surface, a flexible central conversation, and an independently sliding computer panel. The collapsed state retains only the character rail. The plugin surface is a large centered overlay with search, category filters, and a two-column list. The mobile layout removes the persistent rail, keeps a compact agent header, and anchors the reduced-height composer to the bottom.

## Findings and fixes

- [P1] Legacy quick-launch controls crowded the sidebar. Fixed by keeping agent search/list plus Plugins and Profile as the primary navigation.
- [P1] The old plugin access injector rendered twice and pushed the marketplace below the fold. Fixed by exposing the connected marketplace directly while retaining real add, inspect, refresh, search, and filter actions.
- [P1] The composer runtime was coupled to the previous layout script. Fixed with a dedicated runtime; empty state is a white microphone and typed state is a blue upward send arrow.
- [P1] Legacy avatar color styles overrode generated assets. Fixed with persistent generated character assignments and an Auto/random fallback.
- [P2] Agent creation initially bypassed avatar selection. Fixed by placing five choices directly in the actual guided creation card.
- [P2] Mobile retained a permanent 64 px rail. Fixed with an off-canvas drawer and full-width chat/composer.
- [P2] Computer identity was static. Fixed so the title and caption follow the active agent, with `New Agentie` as the no-agent fallback.

## Interaction verification

- Sidebar expands/collapses and the mobile drawer leaves the chat full width when closed.
- Computer panel opens/closes and reports the active agent name (`timer's Computer` in the test state).
- Plugin marketplace loaded 13 active skills, the Telegram channel, MCP presets, and working category controls from live endpoints.
- Agent creation displayed Auto plus four generated shape avatars; explicit selection is persisted, and Auto assigns one randomly.
- Composer accessible state changed from `Voice input` to `Send message` after typing and the `has-text` class activated.
- Production TypeScript/Vite build completed successfully.

## Remaining P3 polish

- The current workspace contains an existing agent error (`No space left on device`) supplied by application data; it is not a layout regression.
- Generated characters intentionally have a softly rendered 3D finish while preserving the reference's simple shape-and-two-eyes language.

## Computer and icon follow-up

- The computer panel now uses a responsive 380–480 px quarter-width desktop column, matching the supplied desktop composition more closely.
- The live per-agent routines endpoint renders directly below the computer viewport, including its connected empty and create states.
- A persistent caret is present in the left rail; it reverses direction and updates its accessible label between Expand and Collapse.
- Plugin and profile navigation now use installed Phosphor icons. Marketplace rows use locally bundled Simple Icons brand marks for Telegram, WhatsApp, GitHub, and Google, with distinct Phosphor semantic icons for all generic capabilities.
- Follow-up production build passed and 27 visible marketplace rows received mapped icons during browser verification.

## Compact marketplace and profile follow-up

- The marketplace now uses three-column icon-first tiles on desktop, two columns on medium widths, and one column on mobile. Long descriptions and capability strings are hidden from the browsing surface.
- The collapsed rail shows unframed avatars only; option dots and active-row backgrounds are suppressed.
- The opening line is positioned as `Chatting with <agent> · <role>` and updates with the active agent.
- Clicking the header avatar opens a four-choice focus card after the opening line. The X cancels it, selecting an answer persists the choice and dismisses the card, and custom text submits with Enter.
- The routine empty state now matches the supplied centered reference with concise schedule guidance and a single Create Routine action.
- Final production build and live browser checks passed.
- Plugin search now overrides the grid display rules correctly, filters across names and hidden capability metadata, respects the active category, supports Escape/native search clearing, and shows a no-results state. Browser verification returned only `Telegram` for the query `telegram`.
- Agent face status overlays are now suppressed everywhere. Each generated assistant reply is visually owned by the active agent avatar, and the live working row pairs that avatar with three dots plus a four-direction look animation. Production build passed; live verification found the correct avatar asset beside the reply and zero visible status-dot overlays.

final result: passed
