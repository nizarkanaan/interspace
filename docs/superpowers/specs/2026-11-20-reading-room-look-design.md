# Reading-room look for the Mac app UI

Date: 2026-11-20
Status: proposed, awaiting approval
Size: small change (stylesheet plus light markup edits in `app/ui/`)

## Intent

Make the Mac app look professional and tidy, and give it a research identity. Interspace is becoming a research environment: papers, citation checks, reports and BibTeX. The current look (Avenir Next, a stock blue accent, rounded cards everywhere) reads like a generic settings screen. The user left the visual direction to the designer.

## Direction: the reading room

The app should feel like a well-run archive reading room. Reading is calm and serif. The controls are quiet and native. The verification status is written in the margin, the way a careful reviewer annotates a manuscript.

The memorable element is the margin. Reference lists and paper lists become a numbered bibliography with hanging indents. A narrow left gutter holds each reference's number and its checker status, in words, with colour repeating the words. Everything else stays quiet.

## Tokens

Colour (light / dark):

| Name | Light | Dark | Use |
| --- | --- | --- | --- |
| Board | `#F3F5F2` | `#15181C` | page background: cool archival grey-green, not cream |
| Leaf | `#FFFFFF` | `#1C2025` | reading surfaces: reports, the stream, forms |
| Ink | `#1C2230` | `#E4E7E2` | text: blue-black, like iron-gall ink |
| Pencil | `#5D6573` | `#A3AAB5` | secondary text, metadata |
| Rule | `#D6DBD4` | `#2E343B` | separators |
| Archive green | `#1F5C4A` | `#82C4AA` | accent, primary actions, "Verified" |
| Oxblood | `#93302A` | `#F0A196` | problems: mismatch, not found, retracted, errors |

Type uses only the fonts that ship with macOS, so nothing is downloaded and the content security policy is unchanged:

- `ui-serif` (New York): headings, report text, paper titles, the conversation's reading text. Serif body gets a slightly taller line height (1.65).
- `system-ui` (SF Pro): controls, navigation, forms, metadata.
- `ui-monospace` (SF Mono): identifiers only (DOI, arXiv ID, branch names, commands, diffs).

Scale (ratio about 1.25): 13 / 15 / 17 / 21 / 27 / 34 px. Reading columns are capped near 70 characters.

## Layout changes

```
┌ sidebar (Board) ┬ main ───────────────────────────────────┐
│ interspace      │ Research                                 │
│                 │ Literature review: sparse attention      │
│ Tasks           │ ──────────────────────────────────────── │
│ Running         │  1  Vaswani, A., Shazeer, N., et al.     │
│ Research   3    │ ✓   (2017). Attention is all you need.   │
│                 │ Ver-  Advances in NeurIPS.               │
│ Project ▾       │ ified doi:10.48550/arXiv.1706.03762      │
│                 │  2  Child, R., et al. (2019). Generating │
│ Settings        │ ✗   long sequences with sparse ...       │
│                 │ Not   Differs from the published record: │
│                 │ found year                               │
└─────────────────┴──────────────────────────────────────────┘
```

- Main content is left aligned. Reading blocks (report, stream, new-task form) are capped at about 70ch.
- Fewer boxes. Tool and team cards keep a border, with a smaller radius (4px). Paper and reference rows lose the boxes and use the margin gutter.
- Headings are set in the serif at the new scale. Page titles are larger and tighter.
- Paper metadata follows citation punctuation (`Authors (Year). Title. Venue.`) instead of joining fields with middle dots.
- Uppercase badges (`.badge`, `.paper-flag`) become sentence case.

## Approaches considered

1. **Restyle in place (chosen).** Rewrite the tokens and type in `desk.css`. Make small markup changes in `research-cards.js` and `index.html` for the gutter and citation formatting. This keeps behaviour, accessibility and the tests intact.
2. Rebuild the UI with a component framework. This was rejected: it is a large rewrite for a visual change, and it adds a build step to a dependency-free UI.
3. Reuse the design preview's palettes (Blueprint, Fieldwork, Printshop). This was rejected: they were made for the observatory scene, not for reading.

## Goals, non-goals, anti-goals

- Goals: a calm, credible research look; better long-form reading; citation status that can be read at a glance; light and dark modes; the current responsive breakpoints keep working.
- Non-goals: new features, a navigation change, the `design/` preview, the Swift shell.
- Anti-goals: a cream-and-terracotta "editorial" look; animation added for decoration; status shown by colour alone; web fonts that need network access.

## Designer's calls (check these)

- Archive green as the single accent, replacing blue.
- System fonts (New York, SF Pro, SF Mono) instead of bundled web fonts.
- The margin gutter as the one bold element.
- Scope limited to `app/ui/`.

## Verification

Run the existing UI tests. Take screenshots of Tasks, Research, a research task with a citation report, Settings, and the agent stream, in light, dark and narrow (600px) widths.
