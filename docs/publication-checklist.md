# Publication checks

The current delivery is local review. Before a separately authorized publication, run:

```powershell
python -m unittest discover -s tests -v
python scripts/check_verified_release.py
python scripts/check_report_site.py
python scripts/check_publication_ready.py
```

The verified-release check rejects mixed source/code identities, incomplete matrices, wrong byte/cohort calculations, altered viewer pixels, stale HTML and inconsistent CSV. The link checker verifies local assets. Review the [publication summary](publication-summary.md), [limitations](../LIMITATIONS.md), data rights in [THIRD_PARTY_DATA.md](../THIRD_PARTY_DATA.md), and staged files before publishing.

Only approved crop derivatives, context maps, public-source derivatives and sanitized numerical evidence belong in the site. Original scans, full private encodes, scratch files and private inventories remain local. The release manifest identifies all current assets; superseded generated figures do not supply current evidence. Keep exact-byte provenance files unchanged across Git platforms, as declared in `.gitattributes`.
