# Explorer finding dispositions

This public mapping preserves stable finding IDs without shipping internal
working conversations or review coordination. All required findings were
resolved before the final round-11 acceptance of `2d65952`.

| Findings | Resolution |
| --- | --- |
| R1-F01 | All required Research Results assets are committed. |
| R1-F02 | Generation tokens and cancellation prevent late A→B→A responses. |
| R1-F03 | Downloads resolve to nonempty, manifest-verified members. |
| R1-F04–F08 | Piston, saturation timing, research windows/wavelengths, estimator bias and narrow legends are explicit. |
| R1-F09–F15; R2-F01–F03; R3-F01 | Labels, playback rate/frame accounting, deep links, identities, gate exit status and records corrected. |
| ER-F01 | R4 plots the paired residual-map statistic, not a difference of arm mean squares. |
| ER-F02 | R1/R2 include source-bound evidence extracts and usable links. |
| ER-F03 | Research wavelength and pre/post-update timing contexts retained. |
| ER-F04 | Semantic checks reject coherently rehashed incompatible science metadata. |
| ER-F05 | Content-addressed page/code bindings refuse mixed cached builds. |
| R5-F01–F03 | 12 m source tied to `573f875`; unexplained research nulls refused; unretained S2 driver disclosed. |
| R6-F01–F04 | Resource record scope corrected; 2 m estimator documented rather than claimed reproduced; source digest and review records corrected. |
| R7-F01; R8-F01; R9-F02; R10-F01 | Source digest isolated from hostile configuration, attributes and environment; order/text/environment protections tested independently. |
| R9-F01; R10-F03 | Coinciding numeric wavelengths retain exact values; nonnumeric inputs are identified clearly. |
| R9-F03–F06; R10-F02 | Stale records, measurements and historical override attribution corrected. |

Round 11 found no new issue at any priority. Its observations concerned
redundant environment protections, corrected historical wording and JSON/Python
quoting conventions; none required a change. Full reports and mutation/browser
fixtures remain in the local review archive. See [acceptance](ACCEPTANCE_REPORT.md)
for the exact identities and limitations.

## After publication

A browser check of the published site at 375 px found three layout issues.
The fix changes only page, script and style bytes (a new code build). The
dataset, manifest and every recorded value are unchanged.

| Findings | Resolution |
| --- | --- |
| PUB-F01 | Table titles were captions inside the horizontal scroll box, so a title wider than the screen was only readable by scrolling the table. Each title now sits above its box and wraps at the box width. |
| PUB-F02 | A shaded-band label ("excluded from the window", "burn-in") was drawn inside the plot area and could overlap recorded curves. Band labels now have their own strip above the plot area. |
| PUB-F03 | Table scroll boxes could not take keyboard focus where the browser does not provide it. Each box is now a focusable region named by its table title. |
