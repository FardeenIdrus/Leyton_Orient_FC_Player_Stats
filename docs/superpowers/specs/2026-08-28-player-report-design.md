# Design — Player Report

_Status: designed, not implemented. Written 2026-08-28._

A one-page scouting report for a single player, produced from the platform and shared with
people who do not log in — the chairman and the manager — as well as read inside the
recruitment room by the Head of Recruitment and scouts.

Reference: `docs/Samson Tovide - Data Report.pdf` (a Bristol Rovers/Tottenham winger report,
supplied by the club). Confidential, gitignored, never published.

---

## 1. Scope

| In scope | Out of scope (recorded, not built) |
|---|---|
| One-page report, rendered in the dashboard and exported | Squad-involvement / availability donut (§9) |
| Central Mid first, then the other seven position groups | Multi-player comparison reports |
| Narrative written by a scout, optional | Automatic prose generation (§4) |
| PDF export | Emailing or hosting the report |

---

## 2. The central decision — one report, narrative optional

**There is one report, not a "data report" and a "full report".**

The club needs reports for fixtures they are about to attend, where no scout has yet assessed
the player. It also needs reports carrying a scout's judgement once one exists. Building those
as two products would duplicate the layout, the charts and the export, and two exports drift —
one rounds a composite differently and someone notices in a chairman's meeting.

So the narrative is a **conditional section**:

| Assessment state | Report shows | Stamp |
|---|---|---|
| None | Charts, composite, bio, evidence. "No scout assessment recorded — this report presents data only." | Data only |
| `submitted` | Adds Summary, Why sign, Considerations, with the assessor's name | **Provisional** |
| `signed_off` | Same, plus the approver's name and date | **Final** |
| Conflicting (Decision 17) | Bands absent, "assessments conflict — not scored" | Data only |

This is the platform's existing rule applied to a document: absent data reads as absent, never
faked, never blocking. It also lets a reader see at a glance whether they hold data alone or
data plus judgement — which is what makes the report safe to send outside the room.

---

## 3. Layout

One landscape page, two horizontal bands, following the reference.

### Band 1 — the decision (read by the chairman)

- **Identity:** player name, position group, current club, and the club crest where held.
- **Bio panel:** age with date of birth, position, preferred foot, height, nationality,
  contract expiry, minutes played in the reported season. Every field that is absent renders
  as "not recorded", never blank and never zero.
- **Summary** — scout-written prose (§4).
- **Why sign** / **Considerations** — scout-written bullets (§4).
- **The club verdict** — this is the platform's advantage and the reference has no equivalent:
  the 1–5 composite, its dimension bands, the Psychological and Medical bands with the
  assessor's and approver's names, and the player's rank within his league, season and
  position group. Advisory flags appear here **naming the dimension and its band**
  (e.g. "Resale 1.58 is below the club minimum of 2.00"), never as an unexplained warning.

### Band 2 — the evidence (read by the scout)

- **Counting stats:** minutes, goals, assists for the reported season.
- **Technical performance:** horizontal percentile bars, every resolved Performance metric for
  the position, coloured red→green, each value labelled.
- **Named scatter:** two axes per position (§6).
- **Physical radar:** the eight SkillCorner metrics, with three overlaid lines — the player,
  the LOFC positional average, and the league positional average — against banded
  Elite→Subpar rings.
- **Category strips:** the five categories (§5) as bands with a distribution showing where the
  player sits.
- **Availability:** availability %, matches missed, and the coverage caveat. **Not a donut** —
  see §9.

---

## 4. The narrative is written by a human, never generated

Three free-text fields are added to the scout assessment: **summary**, **why_sign**,
**considerations**. The report reads them if present.

**They are not generated.** The reference's summary is six paragraphs of analyst judgement —
"under Steve Evans, Bristol Rovers produced a below-average xG per 90 … which may have limited
his creative output". No model on this platform holds that. Template prose from percentiles
would read as filler to a chairman and would be the same failure as the retired Style-fit: a
number dressed as an insight.

**No new workflow.** The fields go on the assessment form that already exists. A scout who
completes an assessment has written the report's narrative as a side effect.

---

## 5. The five categories, derived from the club's own metrics

Each category is the **mean of its members' percentiles**, so it is inspectable rather than a
black box. The members are the club's own per-position Performance metrics as resolved to live
Impect successors — no metric is invented, and the grouping is presentation, not a new model.

**Central Mid** (16 resolved metrics, all at 100% coverage):

| Category | Metrics |
|---|---|
| Progression | Bypassed opponents (packing), deep progressions, pass value (PxT), dribble & carry value |
| Creation | Expected assists, passes into box, assists, open-play assists |
| Retention | Pass accuracy, turnovers **(inverted — fewer is better)** |
| Pressing | Counterpressures, pressures, ball wins |
| Duels | Ground-duel win %, aerial win % |

Goals falls outside the five for a midfielder; it appears in the bar chart, not a category.

**Every position gets its own grouping**, derived the same way from its own metric list. A
metric that resolves to nothing drops out of its category, and the category renormalises over
what is present — the same rule the composite already uses.

**A category with no populated metrics is not shown**, rather than shown as zero.

---

## 6. Scatter axes per position

Two category scores, chosen to separate the position's genuine styles. For **Central Mid**:
**Progression (x) against Pressing (y)**. Both axes are category percentiles, so the plot is
in the same units as the strips beneath it.

Axes for the remaining positions are set when each is built, from the same categories.

---

## 7. What every figure must state

These rules are what make the report safe to send to someone who cannot interrogate it.

- **Every figure states its comparison set** — league, season, position group, and the
  450-minute threshold. A percentile with no stated peer group is meaningless.
- **Provenance on every judgement** — who assessed, who approved, and when.
- **Absent data reads as absent.** Never zero, never a blank implying nothing happened.
- **Colour never carries meaning alone.** The page is printed and read in black and white.
- **Provisional or Final** is stamped on the page from the sign-off state.
- **The report states the data snapshot date** — the last pipeline run — so a reader knows how
  current it is.

---

## 8. Delivery — page first, export second

**A dashboard page** renders the report live for any player. Built from the existing chart
builders in `dashboard/charts.py` (`bar_chart`, `radar_chart`, `cluster_scatter` already
exist) and the existing loaders.

**The export** produces the same report as a file the chairman can open without logging in.

### The export toolchain — decided

**HTML and CSS, printed to PDF from the browser.**

The container has no way to render a PDF containing charts: no `matplotlib`, no `kaleido`, no
`weasyprint`, no `reportlab`. Only `jinja2`.

The decision rests on one fact: **whichever engine produces the PDF, the document is the same
HTML and the same CSS.** A browser's print engine supports modern CSS at least as well as
`weasyprint` does. So printing from the browser is not a lower-quality path — it is the same
document, rendered by a more capable engine, with the reader (or the sender) performing the
final step.

Automation is not a quality attribute. Deferring it costs a button, not fidelity.

**Today:** a self-contained HTML file, downloadable from the dashboard, laid out for landscape
A4 with print CSS, charts as **inline SVG** so they stay vector and print sharp.

**Later, if the club wants one click:** add `weasyprint` (or a headless browser print). It
consumes the same template and stylesheet. **Nothing built now is discarded** — only the button
is deferred.

Charts are inline SVG rather than Plotly images, so the file is self-contained, needs no
JavaScript to print, and stays sharp at any zoom.

## 9. What the reference has that this deliberately does not

Recorded honestly rather than quietly dropped:

- **Appearances and starts** — the platform holds minutes only. An appearance count needs a
  Transfermarkt scrape previously assessed as brittle (its column layout shifts between
  competition types).
- **The availability donut** — needs squad involvement, unused-sub appearances, suspensions and
  not-in-squad counts. Supplied as `docs/Jaze Kabia - Availability.xlsx`; the platform holds
  none of it. Registered as pending item **P8**.
- **Parent club versus loan club** — no loan status is captured anywhere (**P7** in the
  register).
- **Agency, first academy, birth place, achievements, last international recognition** — held
  in no source the platform ingests.
- **Cut-out player photograph** — no image pipeline.

Where a field is absent the report says so. It does not leave a gap that implies the fact is
zero or unknown-but-unimportant.

---

## 10. Testing

Following the platform's existing pattern: pure logic is unit-tested, Streamlit render layers
are not, and no Streamlit test infrastructure is added.

- **Category derivation** — membership per position, the mean over present metrics, inversion
  of lower-is-better metrics, renormalisation when a metric is absent, and a category with no
  populated metrics being omitted rather than zero.
- **Report assembly** — the four assessment states of §2 each produce the right sections and
  the right stamp; a conflicting assessment shows no bands.
- **Absent fields** — every bio field absent renders as "not recorded", never blank or zero.
- **The comparison set** stated on each figure matches the set the percentile was computed
  over.
- **Export** — the generated file contains the stamp, the provenance and the comparison
  statements; an export that silently drops a caveat is worse than no export.

---

## 11. What does not change

`objective_composite` and the default ranking, the 450-minute threshold, the scoring model,
and every existing test. This feature reads; it computes no new score.
