# JPEG XL inside DNG

The [current DNG section](../site/index.html#dng) and [technical evidence](../site/data/dng-evidence.json) replace the earlier archive-value qualification. The route retains equal report prominence and its separate ≤200 MiB budget.

The historical corpus contains twelve primary film frames, two secondary Gold frames, a flat field and the old f/8 target. It differs from the rendered corpus, which uses the f/4.5 target. All sixteen d=0.01 candidates meet 200 MiB and pass the technical audit. Lossless passes technically but none meets the budget.

Current hashes are checked before reusing historical full-decode and Adobe acceptance records. Metadata and selected camera-sample tiles are checked afresh with the pinned decoder. Camera-code errors remain in their native domain. Lossless pixel exactness refers to all checked crops, not a newly repeated comparison of every full-image tile.

Camera-RGB CIEDE2000, ratios against rendered RAW61 errors and the old 15/16 archive-value verdict are withdrawn. A validated common rendering and inversion comparison is still required to establish a RAW61 image-quality advantage.
