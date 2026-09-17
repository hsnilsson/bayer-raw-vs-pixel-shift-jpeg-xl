# Current results

The authoritative numerical results are generated together in the [local report](site/index.html), [release JSON](site/data/release.json), and [measurement CSV](site/data/measurements.csv). The manifest identifies sixteen rendered frames, twenty-two native crops, all 160 frame–distance rows, source and candidate hashes, code/runtime identities, actual decoded ICC profiles and measurement recipes.

The primary budget cohort has twelve independent compressed-RAW film frames. Eight decision distances produce 96 repeated frame–distance rows; d=1 and d=2 add 24 stress rows. Two uncompressed/sequence Gold frames, a flat field and the same-sequence f/4.5 target remain separately available. Per-frame tested crossings and aggregate collection bytes are different summaries and are both shown.

The [DNG evidence](site/data/dng-evidence.json) concerns a different historical sixteen-source corpus. At d=0.01, 16/16 meet 200 MiB and 16/16 pass the technical audit; 0/16 are exact in every checked crop. Lossless gives 16/16 technical passes and checked-crop exactness, but 0/16 meet 200 MiB. The old archive-value verdict and camera-RGB DeltaE comparisons are withdrawn.

Corrected [public codec evidence](site/data/public-evidence.json), [combiner evidence](site/data/combiner-evidence.json), [controlled exposure evidence](site/data/controlled-evidence.json), and [render-lineage audit](site/data/lineage-evidence.json) retain their own domains and limitations. Exploratory ADC, FilmLab and earlier public-v2 runs remain historical in the [research log](docs/research-log.md) and Git history; they do not supply current release measurements.
