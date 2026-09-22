# Dashboard design

Light neutral background, white metric surfaces, a deep-green readiness panel and pale green/blue Body Battery and sleep panels. Data colors remain consistent across icons, card accents and charts. System font and inline SVG; no remote fonts, icon packages, gradients, animations or decorative gauges.

## Hierarchy

- Header: CIRQA / Garmin Connect, last successful sync, Sync now.
- Three primary panels: native training readiness, Body Battery, sleep with labeled stages.
- Compact health/movement grid, followed by supported Garmin training metrics.
- Two-column chart layout on desktop; single column on smaller screens.
- Six activity cards in two columns on desktop and one on mobile, linking to dedicated detail pages. Keep deep activity analysis off the homepage.

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

Four primary native statistics, expandable additional values, then aligned recording charts. Reuse the homepage palette and spacing. All chart panels share a time/distance axis, selection window and hover cursor. SVG dimensions follow the container so labels remain readable on mobile.

Pace is positioned on an equal-speed scale to preserve near-stationary samples without flattening the moving portions; exact pace values remain available on hover. Nonnegative metrics never have negative axis labels. Do not connect missing readings or gaps longer than 30 seconds.

Native zones, laps, typed intervals, strength sets and an optional local GPS trace follow the charts. Comparison uses explicit units; pace and speed are separate rows across different sports. Missing streams and partial download failures remain visible. No inferred interval classification, performance ranking or coaching.

## Training workspace

Keep load, comparisons and the planner on `/training`, linked from overview and activity detail. Native Garmin load, native acute load and optional session-RPE occupy separate cards with independent units. Unknown values use an em dash with accessible “Unavailable” text; valid zero remains numeric. Calendar load bars retain unknown gaps, mark partial totals, and provide a recorded-value table.

Display a decision's source, policy version, reasons, steps and limitations together. Forms must not assume a goal, equipment, daily symptoms or exercise loads. Preserve unsaved entries across period changes and reads; confirm before discarding session feedback. Save errors remain actionable without clearing inputs. Show 12 recent session cards initially, with an explicit expansion control. Native calendar status remains separate from CIRQA decisions and labels the distinction from watch suggestions.
