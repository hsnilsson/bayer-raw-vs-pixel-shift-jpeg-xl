# Film information under a fixed storage budget

Can a better-sampled Pixel-Shift image stored as conservative JPEG XL preserve more useful information about a film original than a conventional lower-resolution Bayer raw capture at similar storage cost?

This investigation retains that primary research question. It grew from a scanning project of approximately 20,000 privately held negatives whose physical originals will remain available. The motivation is to preserve useful sampling, color and editing information without retaining every large intermediate. A more pleasing texture or a closer match to a PS16 render is not, by itself, proof of greater scene accuracy or archival safety.

Open the [published report](https://hsnilsson.github.io/bayer-raw-vs-pixel-shift-jpeg-xl/), first published after owner review on 2026-09-17. Its downloads link to the exact source snapshot and measured evidence. For a local copy, follow the [reproduction instructions](REPRODUCIBILITY.md); the interactive viewer uses a local HTTP server to fetch RGB16 crop data.

Two routes receive separate, equally prominent treatment:

- **Rendered PS16 → JPEG XL:** exact retained JXL bytes compared with each independent compressed RAW61 file. Twelve primary film frames contribute eight decision distances each; two stronger distances are stress controls. Native-crop color and structure comparisons remain separate from reduced full-frame diagnostics.
- **PS16 DNG → JPEG XL inside DNG:** a separate 200 MiB target on sixteen historical sources. All sixteen d=0.01 files meet that budget and the technical audit. Their image-quality advantage over RAW61 remains unresolved. Technical readability and small camera-code differences are not perceptual-quality verdicts.

The complete rendered corpus contains sixteen frames and twenty-two approved crops. Uncompressed or sequence RAWs, the flat field, and the f/4.5 target are separately identified. The DNG corpus instead retains the historical f/8 target. Public FADGI/OpenDICE and Library of Congress files exercise the codec and transformation method, without supplying a RAW61-versus-PS16 comparison.

Current results come from the [release manifest](site/data/release.json), [measurement CSV](site/data/measurements.csv), and linked evidence files. Earlier mixed-precision, mixed-cohort results and camera-RGB DeltaE verdicts have been superseded. Exact counts, tested size-crossing intervals and collection costs are generated in the report from the release, rather than copied into independent summary tables.

Read [findings](FINDINGS.md), [methodology](METHODOLOGY.md), [limitations](LIMITATIONS.md), [reproduction instructions](REPRODUCIBILITY.md), and [remaining work](NEXT_STEPS.md). The [repair acceptance record](docs/report-repair-acceptance.md) maps the review findings to their resolutions. The [research log](docs/research-log.md) and Git history preserve the exploratory work. Data rights and exclusions are documented in [THIRD_PARTY_DATA.md](THIRD_PARTY_DATA.md), [TESTDATA.md](TESTDATA.md), and [PUBLICATION_AUDIT.md](PUBLICATION_AUDIT.md).

The separate [metadata and ICC audit](docs/metadata-icc-audit.md) documents preserved and omitted fields, a reproducible synthetic round trip, and the sidecars recommended for a compact master. Its report section is collapsed by default.
