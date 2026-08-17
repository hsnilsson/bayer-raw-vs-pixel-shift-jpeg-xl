# Test Material Strategy

This document defines what input material is needed for a credible JPEG XL,
DNG, and PixelShift camera-scanning study.

The goal is not to collect random images. The goal is to collect enough
purposefully varied material that the study can say something defensible about
the workflow's strengths, failure modes, and limits.

## Primary Scope

Primary material:

- color negative film camera scans
- PixelShift2DNG output
- Adobe DNG Converter DNG 1.7 JPEG XL output
- storage-budget comparisons between single-shot raw and PixelShift 16

Secondary material:

- positive transparencies or slide film
- black-and-white negatives
- reflective prints

Positive film is relevant, but it should be treated as a secondary track until
the color-negative question is represented well. It has different failure modes:
no orange mask, different density distribution, different highlight behavior,
and often less need for aggressive inversion. It is useful for personal archive
decisions, but it should not be mixed into the main color-negative conclusion.

## Statistical Posture

This is not a formal population study unless hundreds of frames, many cameras,
many operators, and repeated lab conditions are added. The more realistic target
is:

```text
stratified practical evidence
```

That means the corpus should deliberately cover the kinds of frames where the
workflow may fail:

- dense negatives
- thin negatives
- very wide scene brightness range
- smooth color gradients
- skin-like tones
- fine grain or dye-cloud texture
- hard edges
- dust and scratches
- saturated color
- near-clipped highlights
- deep shadows
- different film stocks

The study should report results by category, not only as one average across all
files. A compression setting can look good on average while failing in dense
shadows, smooth skies, skin tones, or fine texture.

## Recommended Corpus Tiers

### Tier 1: Minimum Credible

Use this if we need a compact first public result.

Color negatives:

- 8-12 frames total
- at least 2 film stocks
- at least 1 full storage-budget comparison set
- at least 1 dense or underexposed negative
- at least 1 thin or overexposed negative
- at least 2 high-latitude frames
- at least 2 fine-detail or grain/dye-cloud frames
- at least 1 smooth color or skin-like tone frame
- at least 1 hard-edge, dust, scratch, or high-contrast detail frame

Capture-quality target:

- 1 target capture if available, preferably with single-shot and PixelShift 16

Positive film:

- optional
- 2-3 frames only, clearly marked as secondary

Interpretation allowed:

- good enough to show the method and invite critique
- not enough for a strong archival recommendation

### Tier 2: Good Study

This is the practical target for a serious public writeup.

Color negatives:

- 18-24 frames total
- 4-6 film stocks
- 3 full storage-budget comparison sets
- 3-4 normal exposure frames
- 3-4 dense or underexposed frames
- 3-4 thin or overexposed frames
- 4-6 high-latitude frames
- 3-4 smooth color, sky, wall, or skin-like tone frames
- 4-6 fine texture, grain, dye-cloud, fabric, foliage, or lettering frames
- 3-4 hard-edge, dust, scratch, or high-contrast frames

Capture-quality target:

- 1-2 target captures
- include single-shot, PixelShift 4, and PixelShift 16 when possible

Positive film:

- 4-6 frames
- at least 2 film stocks if available
- include one dense slide, one bright/highlight-heavy slide, one saturated color
  frame, and one fine-detail frame

Interpretation allowed:

- enough to support a cautious practical recommendation
- enough to compare failure modes across categories
- still not enough to claim universal archival safety

### Tier 3: Stronger Study

Use this if the project becomes a larger community resource.

Color negatives:

- 36-48 frames total
- 6-10 film stocks
- 6 full storage-budget comparison sets
- at least 5 dense or underexposed frames
- at least 5 thin or overexposed frames
- at least 8 high-latitude frames
- at least 6 smooth color or skin-like tone frames
- at least 8 fine texture, grain, dye-cloud, fabric, foliage, or lettering
  frames
- at least 6 hard-edge, dust, scratch, or high-contrast frames

Capture-quality target:

- 2-3 target captures
- repeat at different apertures if lens/diffraction questions matter
- include single-shot, PixelShift 4, and PixelShift 16

Positive film:

- 8-12 frames
- 3-5 film stocks if available
- report separately from color negatives

Black-and-white negatives:

- optional separate track
- 6-10 frames
- include fine grain, dense shadows, skies/smooth gradients, and high-contrast
  edges

Interpretation allowed:

- strong enough to make a useful public argument
- suitable for community critique and replication
- still limited to the tested camera, lens, workflow, scanner setup, and
  software versions

## Frame Categories

Each frame can count toward more than one category, but the final corpus should
not be dominated by easy frames.

| Category | Why It Matters | Suggested Count In Good Study |
| --- | --- | ---: |
| Normal color negative | Baseline behavior | 3-4 |
| Dense or underexposed negative | Tests shadow lifting and inversion latitude | 3-4 |
| Thin or overexposed negative | Tests highlight handling and low density | 3-4 |
| High-latitude scene | Tests dark and bright areas in one frame | 4-6 |
| Smooth color or skin-like tones | Reveals banding, bias, and chroma artifacts | 3-4 |
| Fine grain/dye-cloud texture | Tests whether compression damages film structure | 4-6 |
| Hard edges/dust/scratches | Reveals ringing, edge artifacts, and PixelShift registration issues | 3-4 |
| Saturated color | Tests gamut and channel behavior | 2-3 |
| Near-clipped highlights | Tests highlight recovery and tonal compression | 2-3 |
| Deep shadows | Tests noise, density, and post-inversion amplification | 2-3 |

## Film Stock Coverage

For color negatives, a good study should include at least 4-6 stocks if
available. Try to cover:

- one consumer color negative stock
- one professional color negative stock
- one fine-grain low-ISO stock
- one higher-ISO/grainier stock
- one older or less ideal stock if available
- one frame with strong orange mask or scanning difficulty

Positive film should be separate. If included, try to cover:

- one E-6 slide stock
- one dense or underexposed slide
- one bright/highlight-heavy slide
- one saturated color slide

Black-and-white should also be separate, because the color-management and
orange-mask questions are different.

### Near-Term Stock Priority

For the next private capture batch, prioritize common color-negative stocks
before adding more positive-film material to the main evidence track. Kodak Gold
200 and Kodak Gold 400 are useful next candidates because they are familiar
consumer C-41 films, likely relevant to many camera-scanning users, and good
representatives for the orange-mask inversion workflow this project primarily
tests.

Use Kodachrome as a separate positive-film track. It is historically and
personally valuable, and it may be interesting for saturation, density, and
fine-detail behavior, but it should not be mixed into the core color-negative
claim. It does not exercise the same orange-mask inversion risk that motivates
the JPEG XL latitude-stress tests.

Recommended next order:

1. Kodak Gold 200 color negative with high-latitude content.
2. Kodak Gold 400 color negative with grain/fine texture or deep shadows.
3. One professional or finer-grain color negative stock, if available.
4. Kodachrome positive slide, clearly reported as secondary.
5. Black-and-white negative only after the color-negative and positive tracks
   are not starving for coverage.

## Storage-Budget Comparison Sets

The most important material is not just a set of finished DNGs. It is paired
captures of the same frame.

Each storage-budget comparison set should include:

- single-shot raw capture
- PixelShift 4 raw sequence
- PixelShift 16 raw sequence
- PixelShift2DNG output for PixelShift 4
- PixelShift2DNG output for PixelShift 16
- Adobe DNG Converter lossless JXL DNG from the PixelShift2DNG outputs
- Adobe DNG Converter `d=0.03`, `d=0.05`, and `d=0.10` JXL DNG candidates
- source sidecar with capture and privacy notes

Minimum:

- 1 full set

Good study:

- 3 full sets:
  - one normal exposure frame
  - one high-latitude or dense negative
  - one fine-detail/grain/dye-cloud frame

Stronger study:

- 6 full sets across different film stocks and exposure conditions

## What To Look For When Selecting Negatives

Yes: prefer negatives with both very dark and very bright parts in the same
image. That is one of the most valuable stress cases because inversion and
grading can stretch small errors differently across the frame.

Also look for:

- shadow areas that you would realistically lift
- bright windows, skies, lamps, snow, water, or specular highlights
- faces, hands, or skin-like organic tones
- smooth walls, skies, or backgrounds
- fine fabric, hair, grass, leaves, text, signs, or architectural detail
- visible grain or dye-cloud texture
- dust, scratches, or hard black/white edges
- frames that were not perfectly exposed
- frames that are personally safe to publish or crop

Avoid a corpus made only of well-exposed, low-contrast, easy frames. Those are
useful as baseline material, but they do not answer the archival-risk question.

## Positive Film Track

Positive film is worth testing, but separately.

Why include it:

- personal archive relevance
- no orange-mask inversion
- high density and highlight behavior can still stress compression
- slide film often has saturated color and limited exposure latitude

Why keep it separate:

- the negative-inversion stress tests do not apply directly
- metrics may look better simply because the transform is easier
- conclusions for positives should not be used to justify color-negative
  decisions

Recommended first positive set:

- 4-6 frames
- one normal slide
- one dense slide
- one highlight-heavy slide
- one saturated color slide
- one fine-detail slide
- one smooth-gradient slide if available

## Capture Notes Required For Each Set

Each image set should have a sidecar note with:

- anonymous set ID
- film type: color negative, positive, black-and-white negative, or print
- film stock if known
- exposure/capture condition: normal, dense, thin, high-latitude, etc.
- whether the frame is safe to publish, crop-only, or private
- camera and lens
- aperture, ISO, shutter speed, and light source
- film holder and stability notes
- capture mode: single-shot, PixelShift 4, PixelShift 16
- PixelShift2DNG version and settings
- Adobe DNG Converter version and JXL settings
- source file SHA-256 hashes
- notes about visible content, privacy, and why the frame was selected

For local scan folders, generate an initial machine-readable manifest and
Markdown sidecar with:

```powershell
python scripts\create_scan_manifest.py "D:\scan-folder" --film-stock "Kodak Gold 200" --film-type "color negative"
```

By default this writes `scan_manifest.json` and `scan_manifest.md`, classifies
camera raw originals, PixelShift2DNG masters, Adobe DNG Converter JXL-DNG
candidates, previews, and metadata sidecars, and marks files as `keep`,
`review`, or `regenerate`. Use `--hash` when the folder is stable enough to
compute SHA-256 hashes for every file. The generated recommendations are triage
metadata only; they should not be treated as permission to delete originals.

## Acceptance Criteria For The Corpus

Before calling the study "well represented", the corpus should satisfy:

- at least Tier 2 for color negatives
- at least 3 storage-budget comparison sets
- at least 4 film stocks
- at least 4 high-latitude frames
- at least 3 dense/thin exposure stress frames in each direction
- at least 4 fine-detail or grain/dye-cloud frames
- at least 3 smooth tone frames
- metadata sidecars for every set
- at least one DNG/JXL-compatible render pipeline for pixel comparison
- results reported by category, not only as one global average

The project can publish earlier, but it should label earlier results as
preliminary.

## Practical First Shopping List

If adding material soon, prioritize this order:

1. One full storage-budget comparison set from a high-latitude color negative.
2. One full storage-budget comparison set from a fine-detail/grain-heavy color
   negative.
3. One full storage-budget comparison set from a normal exposure color negative.
4. Four to six additional color negatives covering dense, thin, smooth tone,
   saturated color, and hard-edge cases.
5. Four to six positive frames, clearly marked as a secondary track.
6. One target capture if available.

That gives enough material to start answering the core question without turning
the project into an endless collection exercise.
