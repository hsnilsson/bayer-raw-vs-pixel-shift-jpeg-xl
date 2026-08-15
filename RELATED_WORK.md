# Related Work

This file frames the project against nearby standards, papers, guidelines, and
practical work. It is intentionally conservative: the claim is not that this
repository invented JPEG XL archiving, raw compression, PixelShift, or film
camera scanning. The claim is narrower.

Review status: primary standards and vendor documentation were rechecked on
2026-08-15. The literature and prior-art search is deliberately non-exhaustive;
it supports cautious project positioning, not a definitive novelty claim.

Adjacent work exists, but this review did not identify the same combination of:

- camera-scanned film
- high-resolution PixelShift captures
- merged, full-color LinearRaw DNG masters from PixelShift2DNG
- JPEG XL lossless and conservative lossy tests
- negative inversion or latitude-stress transforms
- a fixed-storage-budget comparison against lower-resolution raw capture

That combination is the useful niche of this project.

## JPEG XL As A Standardized Image Format

JPEG XL is standardized as ISO/IEC 18181 and is positioned by JPEG as a modern
image coding system for web delivery, professional photography, high bit depth,
wide color gamut, HDR, progressive coding, and both lossy and lossless
compression:

- [JPEG XL official overview](https://jpeg.org/jpegxl/)
- [JPEG XL reference implementation, libjxl](https://github.com/libjxl/libjxl)
- [The JPEG XL Image Coding System: History, Features, Coding Tools, Design
  Rationale, and Future](https://arxiv.org/abs/2506.05987)

The important point for this repository is that JPEG XL is plausible technology
for high-quality photographic storage. The official JPEG material explicitly
mentions high fidelity, high bit depth, wide gamut, lossless coding, metadata in
the file format, and professional photography use cases. The libjxl tools also
expose a `--distance` parameter, where `0` is lossless and larger values are
lossy.

What this prior work does not answer:

- whether a specific film-negative workflow survives conservative lossy JXL
- whether negative inversion amplifies otherwise small errors
- whether a larger PixelShift scan compressed with JXL can be a better use of a
  fixed storage budget than a smaller raw capture
- whether ordinary photography software handles JXL color profiles correctly
  enough for this workflow

So JPEG XL gives the project a credible technical basis, but not the archival
answer.

## DNG And JPEG XL

DNG is directly relevant because the project starts from PixelShift2DNG output,
not from generic TIFF files. Adobe describes DNG as a public archival format for
camera raw data:

- [Adobe Digital Negative page](https://helpx.adobe.com/camera-raw/digital-negative.html)
- [DNG Specification 1.7.1.0, PDF](https://helpx.adobe.com/content/dam/help/en/camera-raw/digital-negative/jcr_content/root/content/flex/items/position/position-par/download_section_733958301/download-1/DNG_Spec_1_7_1_0.pdf)
- [PixelShift2DNG user manual, version 1.1](https://updates.fastrawviewer.com/data/PS2DNG/PixelShift2DNG-Manual-ENG.pdf)

The PixelShift2DNG manual says that the program combines 4 or 16 source files
into one full-color DNG. The files examined in this project report three-channel
16-bit `LinearRaw` image data. That output is a merged raw-like state, not the
original CFA samples or source ARW sequence.

DNG 1.7.0.0 added JPEG XL compression. The 1.7.1.0 specification allows JPEG XL
compression for 8- to 16-bit integer image data and 16-bit floating point image
data, with supported interpretations including RGB, ColorFilterArray, and
LinearRaw. It also defines JXL-related tags such as `JXLDistance`, `JXLEffort`,
and `JXLDecodeSpeed`. The specification describes the newer lossy options as
particularly useful for proxy DNGs; it does not designate lossy JPEG XL DNG as
an archival master.

This matters a lot: JPEG XL is not merely an external side-format in relation to
DNG. It is already part of modern DNG as a compression option.

But that cuts two ways:

- It strengthens the premise that JPEG XL can be relevant to raw-like archival
  workflows.
- It also weakens any claim that this project is "discovering" JXL-for-DNG as a
  concept.
- It establishes format support, not preservation suitability or application
  interoperability.

The remaining project-specific question is therefore not "can DNG mention JPEG
XL?" It is:

```text
Can this exact kind of demosaiced PixelShift film scan survive a practical
JPEG XL workflow well enough to justify the storage tradeoff?
```

That is narrower, and still appears worth testing.

## Preservation Guidance And Cultural Heritage Imaging

The strongest preservation-adjacent baseline is not "use whatever looks fine."
It is "keep high resolution, high bit depth, color profiles, metadata, and
stable formats."

Useful sources:

- [Library of Congress Recommended Formats Statement: Still Image Works](https://www.loc.gov/preservation/resources/rfs/stillimg.html)
- [Library of Congress format description for DNG 1.6](https://www.loc.gov/preservation/digital/formats/fdd/fdd000628.shtml)
- [Library of Congress format description for TIFF](https://www.loc.gov/preservation/digital/formats/fdd/fdd000022.shtml)
- [FADGI Technical Guidelines for Digitizing Cultural Heritage Materials](https://www.digitizationguidelines.gov/guidelines/digitize-technical.html)
- [FADGI OpenDICE and AutoSFR](https://www.digitizationguidelines.gov/guidelines/digitize-OpenDice.html)

The Library of Congress preference language emphasizes highest available
resolution, highest available bit depth, embedded color profiles or specified
color space, and uncompressed or low/lossless compression for digital
photographs. FADGI and OpenDICE point toward measurable capture quality, not
only subjective inspection.

This project should not be framed as a contradiction of those guidelines. It is
better framed as a storage-constrained edge case:

```text
If storage cost prevents keeping the better-sampled scan, can conservative JPEG
XL make the better-sampled scan practical without destroying the useful film
information?
```

That framing matters. It keeps the project from sounding like a general
recommendation to replace TIFF, DNG, or raw masters with lossy files.

## Raw Compression Research

Recent raw-compression work confirms that raw storage size is a real research
problem, not just a personal inconvenience.

Relevant examples, both currently arXiv preprints rather than preservation
standards:

- [RAWIC: Bit-Depth Adaptive Lossless Raw Image Compression](https://arxiv.org/abs/2603.28105)
- [Raw-JPEG Adapter: Efficient Raw Image Compression with JPEG](https://arxiv.org/abs/2509.19624)

RAWIC focuses on learned lossless compression of Bayer-pattern raw images. It
explicitly treats raw images as linear sensor measurements with high bit depth
and sensor-specific characteristics. Raw-JPEG Adapter takes a different route:
it adapts raw images for storage through a standard JPEG-oriented pipeline while
aiming for accurate raw reconstruction.

Both are close in motivation:

- raw files are large
- raw data is valuable for later processing
- ordinary rendered-image compression is not automatically equivalent to raw
  preservation

But they differ from this project in key ways:

- they primarily target sensor raw or raw reconstruction, not demosaiced
  PixelShift2DNG film scans
- they do not focus on color-negative inversion or film-latitude stress
- they do not ask whether more sampling plus conservative compression beats less
  sampling plus raw storage under the same disk budget
- they are codec/reconstruction research, while this repository is a practical
  workflow investigation

The useful lesson is caution: if a method is lossy or reconstructive, it must be
tested after the operations that matter. For this project, that means inversion,
curves, color balancing, shadow lifting, highlight recovery, and wide-gamut
export.

## Multi-Frame Super-Resolution And PixelShift

The sampling side of the hypothesis is supported by broader multi-frame imaging
work. A useful reference is:

- [Handheld Multi-Frame Super-Resolution](https://arxiv.org/abs/1905.03277)

That paper explains why Bayer color filter arrays require demosaicing and how
shifted raw frames can be merged to increase resolution, reduce aliasing, and
produce fuller RGB information from multiple samples. It also discusses the need
for accurate registration and the risk of motion or alignment failure. The
PixelShift2DNG manual makes the narrower workflow claim that supported 4- or
16-frame sequences can be merged into a full-color DNG.

This is not the same as this project, but it supports one important premise:
single-shot Bayer raw is not a magical complete record of the scene. It is a
sampled measurement that depends on demosaicing. More samples, when registered
well, can preserve real spatial and color structure that a lower-resolution
single capture never measured.

That is the intellectual hinge of the project:

```text
Raw precision is valuable, but unsampled detail cannot be recovered later.
```

The remaining test is whether JPEG XL at conservative settings preserves enough
of the higher-sampled PixelShift result to make that tradeoff worthwhile.

## Other High-Resolution Image Compression Domains

Digital pathology and whole-slide imaging are not film archiving, but they are
useful analogies because they deal with huge image files, texture, color, and
the risk that visually acceptable compression can affect later interpretation.

Example, currently an arXiv preprint:

- [Deep learning-based compression of giga-resolution whole slide images](https://arxiv.org/abs/2605.17668)

The paper compares JPEG, JPEG 2000, JPEG XL, and learned methods on large image
pyramids and tissue patches. Its relevance here is limited to the practical
problem of evaluating very large, textured images. It does not establish
archival or diagnostic equivalence for any codec, and it supplies no acceptance
threshold for film scans.

The analogy is useful, but limited. Medical diagnosis and film scanning have
different risk models, visual structures, tools, and tolerance for irreversible
loss.

## Practitioner Work Around Film Scanning

There is extensive practical knowledge around camera scanning, film inversion,
raw-vs-TIFF export, scanner comparisons, and workflows using tools such as
FilmLab, Negative Lab Pro, RawTherapee, darktable, and dedicated film scanners.
The PixelShift2DNG manual is a primary source for the merge workflow itself.
Much of the broader practitioner evidence lives in forums, videos, blog posts,
vendor docs, and personal tests rather than in reusable public benchmarks. This
review therefore treats it as problem-discovery evidence, not as validation of
the project's archival hypothesis.

This repository can be useful precisely because it tries to make part of that
discussion reproducible:

- public input images where possible
- deterministic crops
- recorded tool versions
- JPEG XL settings
- numeric metrics
- visual diff panels
- explicit limitations

The project should still invite critique from practitioners. A technically
correct compression test can miss the things that film scanners care about in
practice: skin tones, dense negatives, underexposure, orange mask handling,
profiles, dust, scratches, and how far the file can be pushed later.

## What Seems Novel Enough To Contribute

The likely contribution is not a new compression algorithm or a universal
archival recommendation. It is a worked example of a hard practical tradeoff:

```text
Under a fixed storage budget, should a film-camera-scanning workflow preserve
fewer raw pixels exactly, or more PixelShift-sampled film detail with carefully
tested JPEG XL compression?
```

The useful parts of the repository are:

- testing JPEG XL lossless as an exact preservation path for a chosen rendered
  state
- testing conservative lossy distances such as `0.03`, `0.05`, and `0.10`
- measuring error before and after negative-like latitude stress
- separating lossless/lossy, pixel-state, color-management, and metadata claims
- treating PixelShift as a sampling question, not only a file-format question
- staying cautious about deleting original raw/DNG files

That is a relevant contribution even if the final recommendation remains
conservative.

## Claims To Avoid

Avoid these claims:

- "JPEG XL is archival-safe as a raw replacement."
- "Lossy JPEG XL preserves all meaningful color depth."
- "PixelShift is always better than raw."
- "DNG is just a big TIFF and can be replaced without loss."
- "Visual inspection before inversion is enough."
- "This project proves a general rule for all film stocks, cameras, and
  software."

Safer claims:

- "JPEG XL lossless can preserve a chosen decoded/rendered image state exactly,
  if the pipeline is verified."
- "DNG 1.7 defines JPEG XL compression, but the specification alone does not
  establish archival suitability or software interoperability."
- "Conservative lossy JPEG XL remains an interesting candidate for storage
  constrained, high-resolution PixelShift film scans."
- "`d=0.05` is worth further testing; `d=0.10` currently looks too aggressive for
  an archival claim."
- "The key unresolved question is whether extra sampling can outweigh
  conservative lossy error at the same storage budget."

## Search Coverage And Limits

Searches performed or refreshed through 2026-08-15 used standards and vendor
documentation, arXiv, general web search, and GitHub. Query combinations
included:

- `JPEG XL PixelShift DNG film scanning`
- `PixelShift2DNG JPEG XL`
- `JPEG XL camera scanning film negative raw DNG`
- `JPEG XL DNG 1.7 compression raw`
- `JPEG XL archival photography raw DNG study`
- `raw image compression DNG JPEG XL`
- `RAWIC raw image compression`
- `Raw-JPEG Adapter efficient raw image compression`
- `JPEG XL cultural heritage digitization TIFF`
- `JPEG XL whole slide compression`
- GitHub searches for `PixelShift2DNG` with `JPEG XL`, `film scanning` with
  `JPEG XL` and `DNG`, and related terms

No exact duplicate was identified in this pass. Search terms, indexing, and
unpublished practitioner work limit that result, so it must not be restated as
"no prior work exists." Refresh the search before any paper, strong public
novelty claim, or final recommendation, especially after adding anonymous real
negative scans and the planned 61 MP raw versus 240 MP PixelShift comparison.
