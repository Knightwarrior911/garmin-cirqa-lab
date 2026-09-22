# Dashboard design

Google Health's compact metric hierarchy and Garmin watch glanceability are the design references, not copied branding. Light blue-neutral background, white surfaces, navy instrument panels, lime readiness/session accents, mint Body Battery and lavender sleep. Strong numeric hierarchy, system fonts and inline SVG; no remote assets, gradients or marketing hero copy. A readiness ring displays only Garmin's actual bounded score, not invented progress.

## Hierarchy

- Compact header with CIRQA, sync state and primary action. Today / Training / Activities navigation is persistent at the bottom on mobile and inline on desktop.
- Native readiness instrument plus compact Body Battery and sleep tiles, with dated real mini trends. Sleep stages expand on demand.
- A direct HYROX training link and compact recent activity rows. Health/movement, additional native measurements and large historical charts sit behind labeled disclosures.
- Detailed charts remain two columns on desktop, one on mobile; range changes preserve open overview sections.
- Activity history has All / Running / Strength filters and search. Running rows expose average pace when real recording data supports it.

## Data visualization

- Native scores use 0–100 domains. Body Battery uses floating daily low/high bars.
- Sleep and steps use bars; HRV, resting HR and respiration use lines.
- Every chart uses calendar-spaced dates and preserves missing-day gaps.
- Detailed seven-day charts label every observation; longer views label spaced extrema and the latest value.
- Units, recorded-day counts, latest date, hover titles and expandable value tables provide context.
- Data colors identify series, not unsupported diagnoses. No custom recovery score or generic recommendations.
- Hero and health cards include seven-calendar-day mini charts, with visible date spans and recorded-day counts. Missing days break lines; absent history has an explicit empty state. Mini charts complement rather than replace the detailed charts and value tables.
- Step progress uses the Garmin goal from the same dated record. Hide the progress bar for missing or zero goals; cap only its visual width, not the displayed percentage.

## Freshness and interaction

Date every metric. Add native recorded times for readiness and Body Battery. Historical latest values are never labeled today. Distinguish last successful cloud fetch from the sensor reading time. Readiness/recovery values are recorded snapshots, not live countdowns.

Refresh controls are keyboard accessible. Keep a selected chart range across refreshes. Unchanged polling responses do not rebuild the page or collapse value tables. Empty, unavailable and error states are explicit. Escape external strings before inserting HTML. Test narrow-screen overflow and 7/28/90-day controls.

## Activity detail surface

Up to four primary native statistics, with running pace first when available, expandable additional values, then aligned recording charts. Reuse the homepage palette and spacing. Pace occupies a navy/lime tile. Local-summary fallback can compute recorded average pace from actual distance and timer duration but never creates a chart. All chart panels share a time/distance axis, selection window and hover cursor. SVG dimensions follow the container.

Pace is positioned on an equal-speed scale to preserve near-stationary samples without flattening the moving portions; exact pace values remain available on hover. Nonnegative metrics never have negative axis labels. Do not connect missing readings or gaps longer than 30 seconds.

Native zones, laps, typed intervals, strength sets and an optional local GPS trace follow the charts. Comparison uses explicit units; pace and speed are separate rows across different sports. Missing streams and partial download failures remain visible. No inferred interval classification, performance ranking or coaching.

## Training workspace

Keep load, comparisons and the planner on `/training`, linked from overview and activity detail. Native Garmin load, native acute load and optional session-RPE occupy separate cards with independent units. Unknown values use an em dash with accessible “Unavailable” text; valid zero remains numeric. Calendar load bars retain unknown gaps, mark partial totals, and provide a recorded-value table.

The training workspace separates Today / Your week / Load & trends. Today's session is a navy panel with demand, effort target and numbered warm-up/main/cool-down steps. Recorded running pace and 28-day running volume are adjacent summaries. Source, reasons and limitations remain available without repeating paragraphs in the feed. The week combines running and gym days; its future entries are intentions, not recovery clearance.

Preferences, daily check-in and session feedback use labeled native dialogs, with focus containment and inline errors. HYROX/running/gym may be prefilled from the owner's stated intent, but nothing is persisted until explicit save; availability, experience, symptoms and exercise loads are never invented. Preserve unsaved entries across reads and dialog closes. Show 12 recent session cards initially in the load view, with an expansion control. Native calendar status remains separate from CIRQA's planner and watch suggestions.
