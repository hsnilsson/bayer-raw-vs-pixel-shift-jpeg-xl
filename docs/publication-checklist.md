# Publication checks

The report was first published after owner review on 2026-09-17. For an updated report, set up the environment in the [reproduction guide](../REPRODUCIBILITY.md), then run these commands from the repository root:

```powershell
.\.venv\Scripts\python.exe scripts/check_verified_release.py
.\.venv\Scripts\python.exe scripts/check_report_site.py
.\.venv\Scripts\python.exe scripts/check_publication_ready.py
```

The readiness command includes the unit-test suite. The verified-release check covers source/code identities, matrix completeness, byte/cohort calculations, viewer pixels, HTML, CSV and the published reproduction guide. The link checker verifies local assets. Review the [publication summary](publication-summary.md), [limitations](../LIMITATIONS.md), data rights in [THIRD_PARTY_DATA.md](../THIRD_PARTY_DATA.md), and staged files before publishing.

## Source snapshot for a new edition

Choose a fresh version tag and update `source.ref` in `scripts/build_verified_release.py` and the tag links and commands in `REPRODUCIBILITY.md` before assembling the release. The renderer takes its source links from that release. Keep previous version tags fixed so earlier readers can reproduce their edition.

After committing the validated report, create the version tag on that final commit and verify that the tag and the intended publication commit resolve to the same SHA. Push the tag together with `main` when publishing. This makes the exact source links available as the Pages workflow deploys the report.

Only approved crop derivatives, context maps, public-source derivatives and sanitized numerical evidence belong in the site. Original scans, full private encodes, scratch files and private inventories remain local. The release manifest identifies all current assets; superseded generated figures do not supply current evidence. Keep exact-byte provenance files unchanged across Git platforms, as declared in `.gitattributes`.
