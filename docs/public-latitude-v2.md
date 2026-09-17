# Public codec stress evidence

The earlier public-v2 figures and gamma assumptions are superseded by the [corrected public section](../site/index.html#public) and [evidence JSON](../site/data/public-evidence.json).

Six FADGI/OpenDICE and Library of Congress TIFF center crops are tested at lossless, 0.03, 0.05 and 0.10 with libjxl 0.11.2. Actual ICC transfer curves and primaries define the working domain. Source precision is declared, including original 8-bit sources. The grayscale conversion has an independent color-management check.

The same five reference-derived linear-light transformations and native metrics used by the private rendered route are applied. Lossless pixels and profiles must match exactly. Small comparison panels are resampled illustrations; measurements use the full 2048-pixel crops. These public files test codec edit sensitivity, not PS16 sampling gain or recoverable camera latitude. See [reproduction instructions](../REPRODUCIBILITY.md).
