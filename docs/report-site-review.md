# Break-even Report Site Review

This note records the current report-site direction.

## Current Section Review

- Header: needed a real thesis statement. It now states the archive-value
  question directly instead of only saying the page was locally generated.
- Summary cards: `Rows` was ambiguous. It now says `Candidate Rows`, meaning
  material/frame/JXL-level comparisons. Complete rows, PS16 JXL wins and
  under-budget levels are explicit.
- Status labels: `Needs review` was too vague for levels that simply exceeded
  the RAW61 storage budget. Status now distinguishes `Over RAW61 budget`,
  `Budget edge`, `Under budget`, and `Image risk`.
- Level table: repeated RAW61 values were moved out earlier; the table now also
  shows retained MiB, RAW61 median MiB, percent range and MiB range.
- Metric interpretation: a reader no longer has to know whether values such as
  `0.16` are good. The table includes short readings next to DeltaE and ratio
  values, and a metric guide sits directly above the table.
- Review panels: panels are now grouped inside expandable sections. This keeps
  the report scalable when more films, crops and transforms are added.
- Color legend: moved after visual panels as a reference, while the important
  interpretation guidance is now close to the level table.
- FADGI context: remains context only. The report should not claim FADGI
  conformance unless measured with the relevant target workflow.
- Render/profile audit: should stay visible until the RAW61/PS16 render-profile
  issue is resolved or explicitly accepted as part of the workflow comparison.

## Publication Direction

The recommended first publishing target is GitHub Pages. The report is static,
the repository is already on GitHub, and GitHub Actions can publish the `site/`
folder without introducing a separate hosting account.

The local/private report remains under `results/`. The public `site/` folder
must only be generated with publishable test material.

