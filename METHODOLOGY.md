# Methodology

The declared [experiment](metadata/verified_experiment.json) fixes capture identities, cohorts, crop coordinates and ten compression distances. The original primary research question and equally prominent 200 MiB DNG route are retained; their evidence is never pooled into a score.

## Rendered comparison

Retained neutral TIFF renders are adopted sources. Legacy reference PPMs must equal their TIFF pixels exactly. Every frame receives a real-image lossless pilot with pixel, profile and photographic-metadata checks. Existing encodes are audited and decoded with libjxl 0.11.2; metadata repair is independently checked to preserve the image codestream. Original encode-time input hashes were not recorded, so current hashes freeze the adopted snapshot without proving historical cryptographic lineage.

The actual embedded RGB ICC matrix and transfer curves define linear working values and XYZ D50. Lossy decoder ICC profiles may differ from the source profile and are converted rather than relabeled. Exposure is applied in linear light. Five reference-calibrated modes are shared by reference, candidate and RAW baseline: normal, shadow recovery, highlight separation, hard density inversion, and hard inversion with shadow recovery. Inversion is an edit-sensitivity proxy, not a calibrated negative conversion. Unsupported color profiles fail rather than silently falling back to sRGB or gamma 2.2.

Approved native crops retain PS16 coordinates. RAW is resampled in linear light and registered, with the transformation and common valid rectangle recorded. Filled and filter-border pixels are excluded. Registration acceptance and at least 80% valid support are necessary for favorable relative screens. No candidate-specific tone, color or exposure fit is allowed in this route.

Color differences use 64×64 linear patch means converted to Lab D50 and CIEDE2000; edge patches may be smaller. Structure loss is RMS high-pass mismatch divided by reference high-pass RMS, using a float64 5×5 box filter with reflect padding at the boundary of the valid measurement crop. Favorable structure screens require reference high-pass RMS above 2^-23, a float32 precision guard. A zero-energy perfect-match convention in the underlying numerical output is not evidence of retained structure. A separate sensitivity audit removes the two padding-dependent output pixels on every side and records any changed comparisons. Native outcomes are retained separately from a full-frame diagnostic using nonoverlapping 10×10 linear-light box means; incomplete edge blocks are omitted.

The primary storage threshold is exactly final JXL bytes ≤ paired independent compressed RAW61 bytes. Required retained components are included; temporary decodes and report assets are not archival-master cost. MiB is 1,048,576 bytes. Native color and structure screens are separate: color requires candidate patch DeltaE p95 no greater than RAW in normal and hard-inversion modes in every crop; structure requires normal-mode high-pass loss no greater than RAW in every crop. These are relative comparisons, not visibility thresholds. Reported medians use each frame's worst approved crop; crops and distances are not independent captures. Size-crossing intervals only bracket tested distances, and collection-total bytes are separate from per-frame fits.

## Other evidence domains

The DNG route reports camera-code errors, technical metadata preservation, decoder/application acceptance, and the separate ≤200 MiB threshold. Retained full-decode and Adobe acceptance records are reused only for matching file hashes. Selected camera tiles are decoded afresh. Camera codes are not a display color space, and their errors are not divided by rendered RAW61 errors.

Six public 2048-pixel center crops use the same corrected ICC-aware modes and metrics at lossless, 0.03, 0.05 and 0.10. Source precision is declared; promoting an 8-bit source does not create 16-bit information. Grayscale ICC conversion is checked independently.

The combiner audit uses two retained sequences, five crops, actual ICC profiles, common valid support and a scalar midtone exposure match to a newly rendered first-source ARW. A 9×9 low-pass measures tonal agreement; separate high-pass correlation describes detail agreement. This bounded audit does not measure recovered latitude. The controlled exposure experiment remains sensor-domain evidence with source and aggregate audits; its bracket-derived reference is not independent scene truth.

## Display and release integrity

The browser uses RGB16 crop buffers, their actual profiles and the same transform equations, then converts to 8-bit sRGB canvas output. RAW resampling is quantized for browser transport; per-crop errors are disclosed in the lineage audit. Byte-plane shuffle plus gzip is lossless transport, checked against original pixel hashes. Only adjacent quality levels may be prefetched; the pixel cache is bounded.

One complete release binds measurements, source identities, profiles, recipes, tool/code hashes, metadata, previews and viewer pixels. Publication fails on stale code/data, incomplete matrices, wrong cohorts or bytes, mismatched assets, CSV/JSON disagreement or private path leakage. See [reproduction](REPRODUCIBILITY.md) and [limitations](LIMITATIONS.md).
