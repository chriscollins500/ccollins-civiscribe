# CCollins' CiviScribe V2 Image Conformance Tooling

Status: accepted for V2 development and release validation.

This decision covers independent validation of CiviScribe's three output
formats: PNG, JPEG, and WebP. It does not add runtime dependencies, change
writer behavior, or expand the product format surface.

## 1. Decision

CiviScribe uses a layered still-image conformance gate.

### Required release profile

1. Pillow reopens and fully loads every just-written file as the in-process
   writer post-check.
2. ExifTool reads metadata in batched JSON mode. The validator compares
   expected carriers and values, rather than treating a successful parse as
   sufficient.
3. PNGCheck validates PNG chunk rules, CRC values, and the decompressed image
   stream.
4. libjpeg-turbo `djpeg` fully decodes JPEG output.
5. libwebp `webpinfo -diag -summary` validates WebP RIFF/chunk and bitstream
   structure.
6. libwebp `dwebp` fully decodes WebP output.

### Deep cross-reader profile

The periodic deep profile adds:

- Exiv2 metadata readback for EXIF cross-reader compatibility;
- ImageMagick full decode and identification under a dedicated restrictive
  policy.

External conformance tools are development and release tools only. They are not
installed by CiviScribe, imported by the custom node, invoked during a user's
save, or included in the ZIP or wheel.

## 2. Why The Gate Is Layered

No candidate covered all three responsibilities:

- file/container structure;
- complete pixel decoding;
- exact metadata semantics expected from CiviScribe.

The audit found concrete gaps:

- Pillow `Image.verify()` accepted JPEG files with missing end markers and
  truncated scans.
- ExifTool's generic validation did not detect an invalid PNG image-data zlib
  stream or malformed-but-absent WebP EXIF.
- PNGCheck did not validate the TIFF structure inside a PNG `eXIf` chunk.
- `djpeg` correctly ignored malformed EXIF when JPEG pixels remained valid.
- `webpinfo` correctly treated malformed EXIF TIFF data as outside its
  container/bitstream responsibility.
- ImageMagick was an excellent broad decoder but did not replace an exact
  metadata reader.

The validator therefore owns expected-output assertions. For example, a
successful ExifTool parse is still a failure when the expected EXIF
`UserComment`, PNG `parameters`, or dimensions are absent or disagree with the
save request.

## 3. Official Capability Review

The current official documentation establishes the intended roles:

- ExifTool reads metadata from many formats and provides structured JSON
  output:
  <https://exiftool.org/exiftool_pod2.html>.
- PNGCheck checks PNG CRC values, decompresses image data, and reports
  chunk-level information:
  <https://www.libpng.org/pub/png/apps/pngcheck.html>.
- libjpeg-turbo publishes official binaries and supplies `djpeg` as its JPEG
  decoder:
  <https://libjpeg-turbo.org/Documentation/OfficialBinaries>.
- `webpinfo` performs WebP chunk-level inspection and basic integrity checks:
  <https://developers.google.com/speed/webp/docs/webpinfo>.
- `dwebp` exercises libwebp's full decoder:
  <https://developers.google.com/speed/webp/docs/dwebp>.
- Exiv2 reads EXIF in PNG, JPEG, and WebP and provides an independent metadata
  implementation:
  <https://exiv2.org/manpage.html>.
- ImageMagick `identify` reports incomplete or corrupt images, while its
  security policy controls formats, delegates, paths, and resource limits:
  <https://imagemagick.org/identify/> and
  <https://imagemagick.org/security-policy/>.

## 4. Controlled Audit

The local Windows audit used:

| Candidate | Audited version | Local extracted size |
| --- | ---: | ---: |
| Pillow internal baseline | 12.3.0 | Existing development environment |
| ExifTool | 13.59 | 32.99 MiB |
| Exiv2 | 0.28.8 | 23.52 MiB |
| ImageMagick | 7.1.2-27 Q16 x64 | 239.38 MiB |
| PNGCheck | 3.0.3 Windows binary | 2.50 MiB |
| libjpeg-turbo | 3.2.0 | 6.83 MiB |
| libwebp | 1.6.0 | 8.77 MiB |

PNGCheck 4.0.1 was the current source release during the audit. It did not
publish a current Windows release binary, so the local behavior test used the
last official Windows package. CI and package-manager installations should use
the current maintained release where available. CiviScribe does not redistribute
either binary.

The audit generated 19 deterministic files:

- three valid files, one per supported format;
- six damaged PNG files;
- four damaged JPEG files;
- six damaged WebP files.

Controlled faults covered:

- bad PNG ancillary and image-data CRC values;
- invalid PNG zlib data with a valid chunk CRC;
- an illegal empty PNG text keyword;
- malformed PNG EXIF;
- a truncated PNG;
- invalid JPEG APP1 length;
- malformed JPEG EXIF;
- missing JPEG end marker;
- truncated JPEG scan data;
- incorrect WebP RIFF size;
- truncated WebP;
- invalid WebP image signature;
- corrupted WebP entropy data after a valid header;
- impossible WebP EXIF chunk size;
- malformed WebP EXIF TIFF data.

Every candidate accepted all applicable valid files.

| Candidate | Defects signaled | Mean process time |
| --- | ---: | ---: |
| ExifTool generic validation | 11 of 16 | 201.94 ms |
| ExifTool expected-field assertions | 10 of 16 | 200.59 ms |
| Exiv2 metadata read | 8 of 16 | 21.92 ms |
| ImageMagick full identify | 13 of 16 | 36.71 ms |
| PNGCheck | 5 of 6 PNG | 14.25 ms |
| `djpeg` | 3 of 4 JPEG | 22.54 ms |
| `jpegtran` | 3 of 4 JPEG | 21.72 ms |
| `webpinfo` | 5 of 6 WebP | 19.49 ms |
| `dwebp` | 4 of 6 WebP | 25.28 ms |
| Pillow full load | 9 of 16 | 0.33 ms |
| Pillow verify | 7 of 16 | 2.54 ms |

The generic validation and expected-field rows were separate audit invocations.
The production wrapper should request both sets of tags in one batched ExifTool
process.

Distinctive results were:

- ExifTool provided the broadest metadata and structure diagnostics.
- ExifTool expected-field assertions detected every malformed metadata case,
  including WebP EXIF that generic validation treated as absent.
- Exiv2 exposed malformed WebP EXIF TIFF data.
- ImageMagick provided the strongest broad independent decode.
- PNGCheck covered every tested PNG structure and pixel fault; only malformed
  EXIF TIFF data was outside its scope.
- `djpeg` covered every tested JPEG structure and pixel fault; malformed EXIF
  was outside its scope.
- `jpegtran` added no detection beyond `djpeg`.
- `webpinfo` covered every tested WebP structure and pixel fault; malformed
  EXIF TIFF data was outside its scope.
- `dwebp` provided an independent full WebP decode.
- Pillow full load remained a necessary runtime check, not independent
  evidence.
- Pillow `verify()` was too shallow to serve as the sole post-check.

Times are single-machine observations over tiny fixtures and are not product
performance claims. ExifTool should process multiple outputs in one invocation
to amortize its packaged-Perl startup cost.

The selected release tools plus exact metadata assertions detected every
controlled defect. The raw result matrix and generated fault fixtures remained
under `.tmp/conformance-audit/`; they are development evidence, not package
content.

## 5. Invocation Contract

V2's validation wrapper must:

- discover an executable by an explicit configured path or a reviewed
  development-tool lookup;
- record the tool name and version;
- invoke tools with argument arrays and `shell=False`;
- use bounded input size, process time, output size, and concurrency;
- inspect only CiviScribe-generated test artifacts;
- batch ExifTool inputs;
- compare decoded dimensions and expected metadata values;
- treat an absent expected field as a failure even when a reader reports no
  syntax error;
- redact absolute paths from reports;
- write reports only below the ignored validation directory;
- return typed pass, fail, unavailable, and infrastructure-error results;
- distinguish a malformed output from an unavailable validator.

The canonical release environment must contain the required release-profile
tools. A developer's ordinary fast test run may report a missing external tool
as an explicit skip. A release gate may not silently skip it.

## 6. ImageMagick Security Profile

ImageMagick remains deep-profile only. Its dedicated policy must:

- allow decoding only PNG, JPEG, and WebP;
- deny every external delegate;
- deny network coders and indirect reads;
- deny write operations for the conformance invocation;
- deny `@` path expansion;
- cap width, height, area, list length, files, memory, map, disk, threads, and
  elapsed time;
- use a private temporary directory below the validation workspace.

This follows ImageMagick's documented policy model and avoids inheriting the
portable distribution's broader delegate surface.

## 7. Alternatives Not Selected

### `jpegtran`

It found exactly the same four-fixture JPEG failures as `djpeg` and added no
coverage. `djpeg` is the clearer full-decode assertion.

### `jpeginfo`

`jpeginfo` is a focused checker, but its current release does not provide an
official Windows binary and its core JPEG validation overlaps libjpeg-turbo.
It does not justify a second JPEG-only installation or source build.

### Exiv2 in the required release profile

Exiv2 is valuable as a second EXIF reader and caught one malformed WebP EXIF
case that generic ExifTool validation ignored. Exact expected-field assertions
with ExifTool cover the production requirement, so Exiv2 remains a deep
cross-reader rather than a second mandatory metadata parser.

### ImageMagick in the required release profile

ImageMagick caught 13 of 16 controlled defects and is worth retaining
periodically. Its 239 MiB local footprint, broad coder/delegate surface, and
policy burden are excessive for the smallest required gate when native format
tools already cover the supported formats.

### libvips

libvips is a strong image-processing library, not a more authoritative
conformance checker for this three-format scope. It would duplicate the broad
decoder role while adding another substantial native stack.

### Signature-only tools

`file`, MIME sniffers, and extension checks identify a container but do not
prove chunk validity, complete pixel decoding, or metadata correctness.

### Pillow alone

Pillow remains the writer and runtime post-check, but it is not independent
evidence against its own output and its `verify()` behavior was intentionally
less strict than the selected format-native tools.

## 8. Required V2 Tests

The V2 conformance suite must include:

- valid PNG, JPEG, and WebP fixtures accepted by every applicable gate;
- the controlled corruption classes from this audit;
- exact PNG tEXt/iTXt/eXIf carrier and value assertions;
- exact JPEG/WebP EXIF `UserComment`, dimensions, and software assertions;
- PNG CRC and decompression failures;
- JPEG missing-EOI and truncated-scan failures;
- WebP RIFF-size, chunk-size, and deep-bitstream failures;
- malformed EXIF for all three containers;
- Unicode A1111 parameters and deterministic JSON readback;
- no private paths or tokens in reports;
- timeout, unavailable executable, nonzero exit, warning-only, malformed tool
  output, and oversized output handling;
- proof that conformance tooling is absent from runtime imports and release
  artifacts.

This decision creates a development seam only. Production writer and metadata
behavior remain governed by `product_contract.md` and `architecture.md`.
