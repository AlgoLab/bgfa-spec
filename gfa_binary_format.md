# Binary GFA format

## Table of Contents

- [Binary GFA file: overall structure](#binary-gfa-file-overall-structure)
  - [Section IDs Reference](#section-ids-reference)
  - [Block Capacity and Splitting](#block-capacity-and-splitting)
  - [Terminology](#terminology)
  - [How to Read a Block](#how-to-read-a-block)
  - [Payload Byte Layouts](#payload-byte-layouts)
    - [Limits and Validation](#limits-and-validation)
- [File Header Section](#file-header-section)
- [Segments Block](#segments-block)
- [Links Block](#links-block)
- [Paths Block](#paths-block)
- [Walks Block](#walks-block)
- [Conventions](#conventions)
  - [Type Definitions](#type-definitions)
  - [Strategy Code Format Summary](#strategy-code-format-summary)
    - [Byte-by-Byte Strategy Code Formats](#byte-by-byte-strategy-code-formats)
    - [Strategy Code Reference Table](#strategy-code-reference-table)
  - [Encoding Method Reference](#encoding-method-reference)
    - [Integer Encoding Methods](#integer-encoding-methods)
    - [String Encoding Methods](#string-encoding-methods)
    - [CIGAR Decomposition Strategies](#cigar-decomposition-strategies)
  - [Reader Requirements](#reader-requirements)
  - [Error Recovery Guidance](#error-recovery-guidance)
  - [Performance Considerations](#performance-considerations)
  - [Implementation Recommendations](#implementation-recommendations)
  - [Strategy Code Validation Examples](#strategy-code-validation-examples)
- [Walks Type Format](#walks-type-format)
  - [Encoding strategies](#encoding-strategies)
- [Walks and Paths: Type Note](#walks-and-paths-type-note)
- [Packed Bits](#packed-bits)
- [Conformance Requirements](#conformance-requirements)
- [Known Limitations of Version 0](#known-limitations-of-version-0)
- [Appendix A: Example BGFA File](#appendix-a-example-bgfa-file)
  - [A.1 File header](#a1-file-header-17-bytes-offsets-0-16)
  - [A.2 Segments block](#a2-segments-block-82-bytes-offsets-17-98)
  - [A.3 Links block](#a3-links-block-56-bytes-offsets-99-154)
  - [A.4 Paths block](#a4-paths-block-86-bytes-offsets-155-240)
  - [A.5 Walks block](#a5-walks-block-154-bytes-offsets-241-394)
  - [A.6 Round-trip](#a6-round-trip)

## Binary GFA file: overall structure

We divide the file into the following parts.
The first part is the file header, which contains some metadata.
All other parts are a list of blocks. There can be several blocks of the same type.

- File Header
- List of Blocks (segments, links, paths, walks)

Each block contains a `section_id` field that identifies its type, allowing blocks
to appear in any order in the file.

### Section IDs Reference

| ID  | Block Type | Description                                           |
| --- | ---------- | ----------------------------------------------------- |
| 1   | —          | Not defined in BGFA. MUST be treated as a fatal error |
| 2   | Segments   | Segment names and sequences                           |
| 3   | Links      | Link connections and CIGAR alignments                 |
| 4   | Paths      | Paths with oriented segment IDs and CIGAR strings     |
| 5   | Walks      | Walks with sample/haplotype metadata and orientations |

**Unknown section IDs are fatal.** Because the header layout and the payload framing of a block depend on
`section_id`, a reader cannot locate the next block if it does not recognise the current one. A reader
MUST therefore treat any `section_id` not listed above as a fatal error and MUST NOT attempt to skip the
block. There is deliberately no generic block header length, so skipping unknown sections is not possible.

Each block has a header and a payload.
The header contains all metadata, including the strategy used to compress data, the size of the compressed data, and
the size of the uncompressed data.
The payload contains the compressed data blobs.
For each header data we provide a type that allows us to determine its size. The only exception is the file header,
where the `header_len` field must also be read to determine the size of the file header.

### Block Capacity and Splitting

`record_num` is a `uint16` in every block type, so **a single block can hold at most 65535 records**, and a
writer MUST NOT write a block with `record_num = 0` (a block type with no records MUST be omitted entirely).

A writer that needs more than 65535 records of one type MUST split them across several blocks of that type.
Splitting is **by whole records only**: a record is never split across two blocks. The blocks of a split type
are consecutive in meaning but need not be contiguous in the file, since blocks may appear in any order.

Segment IDs are the one case where splitting has an extra consequence: the numbering continues across the
blocks, so segment `i` of the second Segments block follows segment `i - 1` of the first.

### Terminology

- **Record:** A single entry within a block (e.g., one segment, one link, one walk).
- **Block:** A contiguous section of the file containing a header and a payload.
- **Section:** Synonym for block type, identified by `section_id`.
- **Payload:** The encoded data portion of a block, following the header.
- **Field:** A single information written in the file

### How to Read a Block

To read a block from a BGFA file, a reader follows these steps:

1. **Read the block header**: Parse the `section_id` (1 byte) to determine the block type, then parse the remaining header fields according to the block type's header layout.
2. **Determine payload size**: The total payload size is the sum of all `compressed_*_len` fields in the header. Each `compressed_*_len` covers the whole encoded payload of its field, including any integer metadata list and blob.
3. **Parse each payload field**: For each field, use the strategy code to determine how to decode it. The strategy
   codes are different, depending on the type of data we want to store. For `strings` fields, read the metadata (integer positions list encoded per the first-byte strategy), then read the compressed blob (encoded per the second-byte strategy). For `uints` fields, the entire payload is the integer list encoded per the strategy code. For `uints-delta` fields, the payload is the absolute values of the deltas followed by the sign `bits` field (see [Signed Integers](encoding_algorithms.md#signed-integers)). For `bits` fields, read raw bits using the known bit count (see [Packed Bits](#packed-bits)).
4. **Reconstruct data**: Use the metadata and strategy codes to decode each field back to its original form.

For implementation details of each encoding method, see [encoding_algorithms.md](encoding_algorithms.md).

**Key principle:** Every `compressed_*_len` field in the header tells you exactly how many bytes to read for its corresponding payload field. The reader sums these to find the total payload boundary, then processes each field sequentially within the payload.

### Payload Byte Layouts

The `compressed_*_len` fields are the only framing information in a block: the payload is the concatenation of
the byte ranges they describe, in the order listed in each block's _Payload_ table. The tables below state, for
every block, which header field owns which payload fields and how the size of each part is derived.

**Links block**

| `compressed_*_len` field      | Contains (in order)                                        |
| ----------------------------- | ---------------------------------------------------------- |
| `compressed_fromto_len`       | `from_ids`, `to_ids`, `from_orientation`, `to_orientation` |
| `compressed_links_cigars_len` | `links_cigar_strings`                                      |

**Paths block**

| `compressed_*_len` field      | Contains (in order)    |
| ----------------------------- | ---------------------- |
| `compressed_path_names_len`   | `path_names`           |
| `compressed_paths_len`        | `paths` (`walks` type) |
| `compressed_paths_cigars_len` | `paths_cigar_strings`  |

**Walks block**

| `compressed_*_len` field    | Contains (in order)                |
| --------------------------- | ---------------------------------- |
| `compressed_sample_ids_len` | `sample_ids`                       |
| `compressed_haplotype_len`  | `haplotype_indices`                |
| `compressed_sequence_len`   | `sequence_ids`                     |
| `compressed_positions_len`  | `start_positions`, `end_positions` |
| `compressed_walk_len`       | `walks` (`walks` type)             |

**Segments block**

| `compressed_*_len` field       | Contains (in order) |
| ------------------------------ | ------------------- |
| `compressed_segment_names_len` | `segment_names`     |
| `compressed_segment_label_len` | `sequences`         |

**Size rules.** The size of each part follows from these rules, evaluated in this order:

1. **Fixed-size integer fields.** A list encoded with `fixed16`, `fixed32`, or `fixed64` has size
   `n * 2`, `n * 4`, or `n * 8`, where `n` is the number of integers implied by the header
   (`record_num`; `record_num` for **each** of the Walks `start_positions` and `end_positions`
   sub-fields, which have the independent strategies `compression_positions_start` and
   `compression_positions_end`; or `uncompressed_walk_len` for the `walks_segments` absolute values).
   For a `uints-delta` field this fixed-width size applies to the absolute values of the deltas; the
   sign bits are a separate `bits` field covered by rule 3.
2. **Self-delimiting integer fields.** A list encoded with `varint`, `Elias gamma`, `Elias omega`,
   `Golomb`, `Rice`, `StreamVByte`, or `VByte` MUST be decoded for exactly the number of integers
   implied by the header, and MUST consume no more bytes than remain in its owning `compressed_*_len`
   field. Decoding stops at the count, not at the end of the range. (`none` is not a valid integer
   strategy: `0x00` is excluded from integer positions — see
   [Integer Encoding Methods](#integer-encoding-methods).)
3. **`bits` fields.** A `bits` field always occupies `8 * ceil(n / 64)` bytes, where `n` is the number of
   bits (see [Packed Bits](#packed-bits)). A `bits` field is never followed by a non-`bits` field: the
   `bits` fields come at the end of their owning `compressed_*_len` field. When an owning field contains
   more than one `bits` field, they appear in the trailing group in **block field order** — the order in
   which the fields are listed for that block — and a `uints-delta` field's sign bits rank at that field's
   own position in that order. The start offset of the first `bits` field is `compressed_*_len` minus the
   total byte size of all `bits` fields it owns (e.g. `16 * ceil(record_num / 64)` for the Links block's
   `from_orientation` and `to_orientation`); "first" means first in that order.
4. **Blobs.** A `strings` field is `metadata` + `blob`, and the blob carries a leading `varint` blob length, so
   the blob is self-delimiting (see [Blob Framing](encoding_algorithms.md#blob-framing)). The blob length is
   **always a byte count**. The single exception is the Dictionary method (`0x0A`), which replaces this layout
   entirely, including the metadata and the blob length: see
   [Dictionary Encoding](encoding_algorithms.md#dictionary-encoding-0x0a).
5. **`cigar strings` fields.** For decomposition `0x00` the payload is the `record_num` CIGAR entries, each
   followed by `\n`, so splitting on `\n` and dropping the trailing empty piece yields exactly `record_num`
   entries. Decomposition `0x02` is the same buffer, compressed as one blob. Decomposition `0x01` starts with a
   `varint` cigar count and is self-delimiting. See
   [CIGAR 4-byte Strategy Code Details](encoding_algorithms.md#cigar-4-byte-strategy-code-details).
6. **No padding.** Fields are packed contiguously with no inter-field padding and no alignment padding.

#### Limits and Validation

Every size and count used to frame a block comes from the block header or from the payload, and is therefore
attacker-controlled. A reader MUST treat all of them as untrusted input.

A reader MUST perform the following checks, **in this order and before allocating any buffer**:

1. **Header sanity.** `section_id` is known; `version` is not greater than the highest supported version;
   `record_num` is not zero (writers MUST NOT write empty blocks); every strategy code byte is valid and every
   reserved byte is `0x00`.
2. **File extent.** The sum of all `compressed_*_len` fields, plus the block header size implied by
   `section_id`, MUST fit within the remaining bytes of the file. A truncated file is a fatal error.
3. **Derived sizes against their owner.** Every derived size MUST be checked against the
   `compressed_*_len` field that owns it, and MUST be less than or equal to it. In particular,
   `compressed_fromto_len - 16 * ceil(record_num / 64)` MUST NOT be computed without first checking that
   `compressed_fromto_len >= 16 * ceil(record_num / 64)`, because the subtraction underflows otherwise.
4. **Decoded-size caps.** The total number of bytes a reader is willing to decode from one block MUST be
   bounded by an implementation-defined limit. A block whose decoded content would exceed that limit MUST be
   rejected as a fatal error, rather than causing the reader to attempt the allocation. This bound also applies
   to any state a reader retains across blocks, such as the segment ID table needed to resolve segment IDs to
   names: see [Segments Block](#segments-block).
5. **Value widths.** A value that does not fit the width implied by its integer strategy MUST be rejected, not
   truncated: see [Integer Validation Rules](encoding_algorithms.md#integer-validation-rules).
6. **Arithmetic overflow.** Products, sums and roundings derived from header fields — `n * 2`, `n * 4`,
   `n * 8`, `8 * ceil(n / 64)`, `ceil(n / 4)`, `16 * ceil(n / 64)`, and dictionary `N + 1` — MUST be computed
   with overflow checking. On overflow the reader MUST reject the field; it MUST NOT wrap around.
7. **Per-method validation.** Each method additionally carries its own MUST-level validation rules, such as
   Kraft's equality for a Huffman codebook and the position and count checks for 2-bit DNA exceptions. See
   [encoding_algorithms.md](encoding_algorithms.md).

A reader MUST NOT trust the superstring heuristic: string positions MUST be validated against the decoded blob
length, and a position beyond that length is a fatal error.

**Example.** In the Links block, `from_orientation` has `record_num` bits, hence `8 * ceil(record_num / 64)`
bytes, and `to_orientation` the same. The two bit fields therefore occupy `16 * ceil(record_num / 64)`
bytes, and `from_ids` and `to_ids` together occupy `compressed_fromto_len - 16 * ceil(record_num / 64)`
bytes.

## File Header Section

| Field          | Description                                             | Type                      |
| -------------- | ------------------------------------------------------- | ------------------------- |
| `magic_number` | Magic number for bgfa files = "BGFA" (0x41464742)       | `uint32`                  |
| `version`      | Format version (progressive number, starts at 0)        | `uint16`                  |
| `header_len`   | length of the header string (excluding null terminator) | `uint16`                  |
| `header_text`  | GFA header text                                         | `bytes` + null terminator |

**Clarification:** The `header_text` field is stored as `header_len` bytes of ASCII text followed by a single null terminator byte (`\0`). The `header_len` field specifies the length of the text portion only. Total bytes consumed = 8 (`magic` + `version` + `header_len`) + `header_len` + 1 (null terminator).

**Note:** The magic number 0x41464742 corresponds to ASCII "BGFA" when read as little-endian bytes: 0x42='B', 0x47='G', 0x46='F', 0x41='A'.

**Version:** The version field is a progressive integer starting at 0. A reader MUST reject the file with a
fatal error if `version` is **larger** than the highest version it supports; a lower version MUST be accepted
and processed as defined by this specification (readers are forward compatible with the version number, not
with the byte layouts of future versions).

## Segments Block

We associate an internal segment ID to each segment name, where the segment ID is an
incrementing integer starting at 0. Segment IDs are assigned in the order segment names appear in the file.

Segment IDs are **global to the file**: the segment with ID `i` is the `i`-th segment record in file order,
across all Segments blocks. A record in any block MAY reference any segment ID in the file, including one
defined in a block that appears later in the file; readers MUST NOT assume that referenced segments are
already defined.

This is the single definition of the segment ID namespace. Every other field that holds a segment ID — the
Links block `from_ids` and `to_ids`, the `walks_segments` of the Paths and Walks blocks, and the Walks block
`sequence_ids` — uses this same namespace, so one Segments-block scan resolves all of them.

**Resolving a segment ID to a name.** Because a defining Segments block MAY appear later in the file than the
block holding the reference, this check applies only once the whole file has been read:

- A reader that resolves a segment ID to a segment name MUST treat an ID that no Segments block in the file
  defines as a fatal error, and MUST NOT substitute a placeholder or a default name.
- A reader MAY defer resolution until after the final block, and SHOULD do so, because that is the only point
  at which every Segments block is known.
- A reader that decodes segment IDs without resolving them has nothing to check at that point, so it MAY skip
  the check entirely. This includes a streaming reader that emits records as it decodes them, which cannot
  retroactively retract what it has already emitted; such a reader accepts the risk that a dangling ID is
  never detected.

This applies to every field that holds a segment ID — `from_ids` and `to_ids` in the Links block,
`walks_segments` in the Paths and Walks blocks, and `sequence_ids` in the Walks block — not only to
`sequence_id`.

See [Block Capacity and Splitting](#block-capacity-and-splitting) for the limit that applies to every block
type, and how writers split records across blocks. Segment ID numbering continues across Segments blocks.

### Header

| Field                            | Description                                                 | Type       |
| -------------------------------- | ----------------------------------------------------------- | ---------- |
| `section_id`                     | Section type (2 = segments)                                 | `uint8`    |
| `record_num`                     | number of records in the block                              | `uint16`   |
| `compression_segment_names`      | Encoding strategy for the segment names (2 bytes)           | `bytes[2]` |
| `compressed_segment_names_len`   | number of bytes of the encoded segment names payload        | `uint64`   |
| `uncompressed_segment_names_len` | sum of the lengths of the uncompressed segment names        | `uint64`   |
| `compression_segment_label`      | Encoding strategy for the segment sequences (2 bytes)       | `bytes[2]` |
| `compressed_segment_label_len`   | number of bytes of the encoded sequences payload            | `uint64`   |
| `uncompressed_segment_label_len` | sum of the lengths of uncompressed segment_sequences fields | `uint64`   |

The length of the uncompressed segment names does not include any terminator character.

### Payload

| Field           | Description       | Type      |
| --------------- | ----------------- | --------- |
| `segment_names` | Segment names     | `strings` |
| `sequences`     | Segment sequences | `strings` |

**Layout:** The payload consists of encoded segment names followed by encoded sequences.
We have two distinct encoding strategies.

**Empty sequences:** A segment whose sequence is `*` in the corresponding GFA record (i.e. "no sequence") MUST
be encoded as the **empty string**: `start[i] == end[i]`, contributing zero bytes to the superstring. Note
that a set of strings may therefore have `uncompressed_segment_label_len == 0`.

## Links Block

Each block consists of a header and a payload.

### Header

The following is the sequence of fields making up the header.

| Field                           | Description                                                             | Type       |
| ------------------------------- | ----------------------------------------------------------------------- | ---------- |
| `section_id`                    | Section type (3 = links)                                                | `uint8`    |
| `record_num`                    | number of records in the block                                          | `uint16`   |
| **From/To field**               |                                                                         |            |
| `compression_fromto`            | Integer encoding strategy for `from_ids` and `to_ids` (applies to both) | `byte`     |
| `compressed_fromto_len`         | number of bytes of the encoded from/to payload                          | `uint64`   |
| **CIGAR field**                 |                                                                         |            |
| `compression_links_cigars`      | Encoding strategy for the cigar strings (4 bytes)                       | `bytes[4]` |
| `compressed_links_cigars_len`   | number of bytes of the encoded CIGAR strings payload                    | `uint64`   |
| `uncompressed_links_cigars_len` | sum of the lengths of uncompressed cigars                               | `uint64`   |

### Payload

The following is the sequence of fields making up the payload layout.

| Field                 | Description                                       | Type                         |
| --------------------- | ------------------------------------------------- | ---------------------------- |
| `from_ids`            | Tail internal segment IDs                         | `uints`                      |
| `to_ids`              | Head internal segment IDs                         | `uints`                      |
| `from_orientation`    | Orientations of all from segments. 0 is +, 1 is - | `bits` (length = record_num) |
| `to_orientation`      | Orientations of all to segments. 0 is +, 1 is -   | `bits` (length = record_num) |
| `links_cigar_strings` | CIGAR strings                                     | `cigar strings`              |

**Layout:** All four fields listed above are contained in `compressed_fromto_len`, in this order. The two
orientation bit fields come last, so they occupy the final `16 * ceil(record_num / 64)` bytes of the region.
`links_cigar_strings` occupies `compressed_links_cigars_len`. See [Payload Byte Layouts](#payload-byte-layouts).

**Orientation mapping:** The i-th bit in `from_orientation` corresponds to the i-th segment ID in `from_ids`.
Similarly, the i-th bit in `to_orientation` corresponds to the i-th segment ID in `to_ids`.
There are first `record_num` integers for the `from_ids`, then `record_num` integers for the `to_ids`
Therefore there are exactly `record_num` segment IDs in both the `from_ids` and in the `to_ids` lists and there are exactly
`record_num` bits in both the `from_orientation` and in the `to_orientation` lists.

Orientation bits are stored LSB-first within each `uint64` word. See [Packed Bits](#packed-bits) for details.

**Link overlap coordinates:** BGFA does not store the GFA overlap coordinates of an L record. Writers MUST
drop them, and readers MUST NOT attempt to reconstruct them. See
[Known Limitations of Version 0](#known-limitations-of-version-0).

## Paths Block

Each block consists of a header and a payload.

### Header

The following is the sequence of fields making up the header.

| Field                           | Description                                                                           | Type       |
| ------------------------------- | ------------------------------------------------------------------------------------- | ---------- |
| `section_id`                    | Section type (4 = paths)                                                              | `uint8`    |
| `record_num`                    | number of records in the block                                                        | `uint16`   |
| `compression_path_names`        | Encoding strategy for the path names (2 bytes)                                        | `bytes[2]` |
| `compressed_path_names_len`     | number of bytes of the encoded path names payload                                     | `uint64`   |
| `uncompressed_path_names_len`   | sum of the lengths of the uncompressed path names                                     | `uint64`   |
| `compression_paths`             | Encoding strategy for the paths as list of segment IDs                                | `bytes[2]` |
| `compressed_paths_len`          | number of bytes of the encoded paths payload                                          | `uint64`   |
| `uncompressed_paths_len`        | sum of the lengths of uncompressed paths (total segment occurrences across all paths) | `uint64`   |
| `compression_paths_cigars`      | Encoding strategy for the cigar strings (4 bytes)                                     | `bytes[4]` |
| `compressed_paths_cigars_len`   | number of bytes of the encoded CIGAR strings payload                                  | `uint64`   |
| `uncompressed_paths_cigars_len` | sum of the lengths of uncompressed cigars strings                                     | `uint64`   |

### Payload

The following is the sequence of fields making up the payload layout.

| Field                 | Description                                            | Type            |
| --------------------- | ------------------------------------------------------ | --------------- |
| `path_names`          | Path names                                             | `strings`       |
| `paths`               | Paths, each path is a sequence of oriented segment IDs | `walks`         |
| `paths_cigar_strings` | The list of CIGAR strings                              | `cigar strings` |

**Layout:** `path_names` occupies `compressed_path_names_len`, `paths` occupies `compressed_paths_len`, and
`paths_cigar_strings` occupies `compressed_paths_cigars_len`. See
[Payload Byte Layouts](#payload-byte-layouts).

**`uncompressed_paths_len`:** the sum of the lengths of the uncompressed paths, where the length of a path is
its number of oriented segment occurrences, i.e. its number of elements in the `walks` type. This is the
`n` used by the `walks_orientations` field of this block.

**CIGAR strings:** there are exactly `record_num` entries in `paths_cigar_strings`, one per path. A path MAY
carry **several** CIGARs, which MUST be separated by `,` within a single entry (the GFA convention). A path
without CIGARs has the empty string as its entry. A single `,`-separated entry MUST NOT be split across
several entries.

## Walks Block

Each block consists of a header and a payload.

### Header

The following is the sequence of fields making up the header.

| Field                         | Description                                                          | Type       |
| ----------------------------- | -------------------------------------------------------------------- | ---------- |
| `section_id`                  | Section type (5 = walks)                                             | `uint8`    |
| `record_num`                  | number of records in the block                                       | `uint16`   |
| **Compression strategies**    |                                                                      |            |
| `compression_sample_ids`      | Encoding strategy for the sample IDs (2 bytes)                       | `bytes[2]` |
| `compression_haplotype`       | Integer encoding strategy for the haplotype indices                  | `byte`     |
| `compression_sequence`        | Integer encoding strategy for the walk sequence IDs                  | `bytes[2]` |
| `compression_positions_start` | Integer encoding strategy for the start positions                    | `byte`     |
| `compression_positions_end`   | Integer encoding strategy for the end positions                      | `byte`     |
| `compression_walks`           | Encoding strategy for the walks                                      | `bytes[2]` |
| **Samples field**             |                                                                      |            |
| `compressed_sample_ids_len`   | number of bytes of the encoded sample IDs payload                    | `uint64`   |
| `uncompressed_sample_ids_len` | sum of the lengths of uncompressed sample IDs                        | `uint64`   |
| **Haplotype indices field**   |                                                                      |            |
| `compressed_haplotype_len`    | number of bytes of the encoded haplotype indices payload             | `uint64`   |
| `uncompressed_haplotype_len`  | number of haplotype indices = `record_num`                           | `uint64`   |
| **Walk sequence IDs field**   |                                                                      |            |
| `compressed_sequence_len`     | number of bytes of the encoded walk sequence IDs payload             | `uint64`   |
| `uncompressed_sequence_len`   | number of walk sequence IDs = `record_num`                           | `uint64`   |
| **Positions field**           |                                                                      |            |
| `compressed_positions_len`    | number of bytes of the encoded positions payload                     | `uint64`   |
| `uncompressed_positions_len`  | number of positions = `2 * record_num`                               | `uint64`   |
| **Walks field**               |                                                                      |            |
| `compressed_walk_len`         | number of bytes of the encoded walks payload                         | `uint64`   |
| `uncompressed_walk_len`       | sum of the lengths of uncompressed walks (total segment occurrences) | `uint64`   |

### Payload

The following is the sequence of fields making up the payload layout.

| Field               | Description                                            | Type          | Bytes                            |
| ------------------- | ------------------------------------------------------ | ------------- | -------------------------------- |
| `sample_ids`        | Sample IDs                                             | `strings`     | `compressed_sample_ids_len`      |
| `haplotype_indices` | Haplotype indices                                      | `uints`       | `compressed_haplotype_len`       |
| `sequence_ids`      | Walk sequence IDs                                      | `string`      | `compressed_sequence_len`        |
| `start_positions`   | Start positions                                        | `uints-delta` | `compressed_positions_len` (1st) |
| `end_positions`     | End positions                                          | `uints-delta` | `compressed_positions_len` (2nd) |
| `walks`             | Walks, each walk is a sequence of oriented segment IDs | `walks`       | `compressed_walk_len`            |

**Layout:** each payload field occupies the header field that owns it: `sample_ids` →
`compressed_sample_ids_len`, `haplotype_indices` → `compressed_haplotype_len`, `sequence_ids` →
`compressed_sequence_len`, and `start_positions` then `end_positions` → `compressed_positions_len`.
`walks` occupies `compressed_walk_len`. See [Payload Byte Layouts](#payload-byte-layouts).

Since there are `record_num` records in the block, the block contains `record_num` sample IDs, followed by `record_num`
haplotype indices, followed by `record_num` sequence IDs, followed by `record_num` start positions, followed by
`record_num` end positions, followed by `record_num` walks.

**Semantics of the record fields:**

- `sample_id`: the sample name. It MAY be the empty string, meaning "not set", or the literal `*`, meaning
  "unspecified sample".
- `haplotype_index`: a **1-based** index of the haplotype within the sample (GFA W record semantics), so
  valid values start at 1. `0` is not a valid haplotype index and MUST NOT be written.
- `sequence_id`: **the segment ID of the sequence the walk is placed on.** It is an internal segment ID in the
  same global, 0-based, file-order namespace that the Segments block assigns to every segment name (see
  [Segments Block](#segments-block)), i.e. the identical namespace used by the Links block `from_ids` and
  `to_ids` and by `walks_segments` in the Paths and Walks blocks. The walk's reference sequence is therefore
  also a vertex of the pangenome graph, and a converter that wants to preserve a reference MUST emit it as a
  segment record of some Segments block in the same file. This is an internal ID, not a sequence name: a
  reader recovers the name by looking the ID up in the Segments blocks, which is the only mapping this
  format defines.
- `start_position`: the 1-based start coordinate of the walk on `sequence_id`, as in the GFA W record.
- `end_position`: the 1-based end coordinate of the walk on `sequence_id`, as in the GFA W record.
  For both `start_position` and `end_position`, the value `0` encodes a missing position. The bytes MUST still be present and decodable.

  > **This field is reserved for future use and stays in the wire format, including in version 1.0.**
  > It carries no information in version 0: writers must emit `record_num` always-zero values, and readers
  > must decode and discard them. It is kept so that a future version can give it a meaning without a
  > header change. The cost — roughly one varint byte per walk record in every Walks block, which is
  > significant for walk-heavy pangenome files — is an accepted trade-off.

## Conventions

**Block ordering constraints:**

- Blocks of the same type are not required to be contiguous
- Different section types can appear in any order relative to each other.

**Endianness:** All multi-byte integer fields (`uint16`, `uint32`, `uint64`) are encoded in little-endian format. Strategy codes and other byte sequences have no endianness considerations as they are simple sequences of bytes.

**Alignment:** All fields begin at the next byte boundary after the previous field, and no inter-field padding
is applied. `bits` fields are the one exception to byte-granularity: they occupy a whole number of 8-byte
`uint64` words and are therefore padded up to that size. See [Packed Bits](#packed-bits).

All bytes data are packed into bytes.

**Bit packing.** There are exactly two bit orders in BGFA, and each is used by a specific class of encoding:

- The `bits` type (orientations, signs) is packed LSB-first into little-endian `uint64` words. See
  [Packed Bits](#packed-bits).
- All other bit streams — that is, the bit streams produced by Elias gamma/omega, Golomb, Rice, Huffman,
  2-bit DNA, and any other bit-oriented method — are packed **MSB-first**: the first bit of the
  stream occupies bit 7 of the first byte, the second bit 6, and so on.

In both cases, any remaining bits in the final byte or word of a bit stream are set to 0 when writing and MUST
be ignored when reading.

**varint continuation bit.** A varint (or VByte) encodes 7 data bits plus a continuation bit per byte. The
continuation bit is the **most significant bit of the byte**; data bits are stored **least-significant group
first**. This is the same in both endianness conventions and applies to all bit orders.

**C strings:** The reference to C strings (ASCII terminated by `\0`) is for context only.
Input strings to the `strings` type do NOT include null terminators. Strings are stored as raw ASCII bytes without termination.

### Type Definitions

- `uints`: A list of unsigned integers encoded according to the specified integer encoding strategy (see [Encoding Method Reference](#encoding-method-reference)). The number of integers is implied by the containing block header.
- `uints-delta`: A list of unsigned integers encoded as delta differences. See [Signed Integers](encoding_algorithms.md#signed-integers) for the exact encoding. There is **one single delta stream per field**: the first value of the field is stored as-is, and every subsequent value is the signed difference with the immediately preceding value of the same field. The stream is **never reset** at walk boundaries, record boundaries, or any other boundary.
- `strings`: A list of strings encoded according to the string encoding strategy. See [String Encoding Overview](encoding_algorithms.md#string-encoding-overview) for the encoding approach.
- `cigar strings`: A list of CIGAR strings encoded according to the CIGAR decomposition strategy. See [CIGAR 4-byte Strategy Code Details](encoding_algorithms.md#cigar-4-byte-strategy-code-details).
- `bits`: A list of bits packed into uint64 words (see [Packed Bits](#packed-bits)).
- `walks`: A list of walks, where each walk is a sequence of oriented segment IDs (see [Walks Type Format](#walks-type-format)).

### Strategy Code Format Summary

The BGFA format uses strategy codes to specify encoding methods. Strategy codes are simple sequences of bytes with no endianness considerations. The code size depends on what is being encoded.

#### Byte-by-Byte Strategy Code Formats

**1-byte Strategy Codes (Integer-only):**

```
Format: 0xMM
Bytes: [MM]
```

- `MM`: Integer encoding method (any assigned value; `0x03` is reserved and MUST be treated as unknown)
- Used for: Pure integer lists
- Examples:
  - `0x01` = Varint encoding
  - `0x02` = Fixed16 encoding

**2-byte Strategy Codes (Strings):**

```
Format: 0xHHLL
Bytes: [HH, LL]
```

- `HH`: Integer encoding method for metadata (lengths/positions)
- `LL`: String encoding method for blob
- Used for: String lists
- Examples:
  - `0x0102` = Bytes `[01, 02]` (Varint metadata + Fixed16 blob)
  - `0x0104` = Bytes `[01, 04]` (Varint metadata + nibble-level Huffman blob)

**2-byte Strategy Codes (Walks/Paths):**

```
Format: 0xHHLL
Bytes: [HH, LL]
```

- `HH`: Integer encoding method for metadata (lengths/positions)
- `LL`: Integer encoding method for the segment IDs
- Examples:
  - `0x0102` = Bytes `[01, 02]` (Varint metadata + Fixed16 for the segment IDs)
  - `0x0104` = Bytes `[01, 04]` (Varint metadata + elias gamma for the segment IDs)

**4-byte Strategy Codes (CIGAR):**

```
Format: 0xDDRRIISS
Bytes: [DD, RR, II, SS]
```

- `DD`: Decomposition strategy
- `RR`: Integer encoding method for the operation lengths (`0x01` for varint, `0x02` for fixed16)
- `II`: Integer encoding method for the operation counts
- `SS`: String encoding method for the packed operations
- Used for: CIGAR strings
- Note: `RR` is only meaningful when `DD = 0x01`; for `DD = 0x00` and `DD = 0x02` it is a reserved byte and MUST be `0x00`.
- Examples:
  - `0x00000000` = Bytes `[00, 00, 00, 00]` (none decomposition; `RR` and `II` reserved, `SS` = none)
  - `0x01010200` = Bytes `[01, 01, 02, 00]` (numOperations decomposition, varint operation lengths, fixed16 operation counts, none for packed operations)
  - `0x02000003` = Bytes `[02, 00, 00, 03]` (string decomposition, reserved, reserved, LZMA)

#### Strategy Code Reference Table

| Code Type    | Format       | Bytes              | First | Second | Third | Fourth |
| ------------ | ------------ | ------------------ | ----- | ------ | ----- | ------ |
| Integer-only | `0xMM`       | `[MM]`             | `MM`  | -      | -     | -      |
| Strings      | `0xHHLL`     | `[HH, LL]`         | `HH`  | `LL`   | -     | -      |
| CIGAR        | `0xDDRRIISS` | `[DD, RR, II, SS]` | `DD`  | `RR`   | `II`  | `SS`   |
| Walks/Paths  | `0xHHLL`     | `[HH, LL]`         | `HH`  | `LL`   | -     | -      |

### Encoding Method Reference

The following tables map strategy code byte values to encoding methods. Implementation details for each method are in [encoding_algorithms.md](encoding_algorithms.md).

#### Integer Encoding Methods

Used for `uints` fields and for the first byte of 2-byte codes.

| Code   | Strategy    | Extra payload bytes |
| ------ | ----------- | ------------------- |
| `0x01` | varint      | none                |
| `0x02` | fixed16     | none                |
| `0x04` | elias gamma | none                |
| `0x05` | elias omega | none                |
| `0x06` | golomb      | none (see below)    |
| `0x07` | rice        | 1 byte: `k`         |
| `0x08` | streamvbyte | none                |
| `0x09` | vbyte       | none                |
| `0x0A` | fixed32     | none                |
| `0x0B` | fixed64     | none                |

Codes `0x00`, `0x03` and `0x0C`–`0x0FF` are not assigned in an integer position and MUST be treated as
unknown strategy codes. In particular `0x00` is a valid _string_ method but carries no meaning as an integer
method: an integer list has a known element count and therefore no element width. See
[Integer Method: None (0x00)](encoding_algorithms.md#integer-method-none-0x00).

**Golomb parameter `b`.** The Golomb code `0x06` uses a fixed parameter `b = 128`. The parameter is
**per field**, i.e. every field encoded with `0x06` uses `b = 128`, and `b` is NOT transmitted. The number of
bits used for the remainder is therefore always `ceil(log2(128)) = 7`. If a writer needs a different `b`, it
MUST select another strategy.

**Rice parameter `k`.** The code `0x07` derives `b = 2^k`. The parameter `k` is **per field** and MUST be
stored explicitly as the **first byte of that field's integer payload**, before any encoded value. `k` MUST
satisfy `1 <= k <= 31`. The same `k` applies to every value in the field. Since `k` is payload data and not
part of the strategy code, a decoder reads it from the payload rather than from the header; a reader MUST
validate that `k` is in range and MUST treat an out-of-range `k` as a fatal error.

#### String Encoding Methods

Used for the second byte of a 2-byte `strings` code and for `SS` in a
4-byte CIGAR code.

| Code   | Strategy             | Notes                                                                                                   |
| ------ | -------------------- | ------------------------------------------------------------------------------------------------------- |
| `0x00` | none (identity)      | raw bytes of the superstring                                                                            |
| `0x01` | zstd                 | Zstandard                                                                                               |
| `0x02` | gzip                 | gzip                                                                                                    |
| `0x03` | lzma                 | LZMA                                                                                                    |
| `0x04` | Huffman              | nibble-level, 16-symbol codebook                                                                        |
| `0x05` | 2-bit                | 2-bit DNA/RNA                                                                                           |
| `0x06` | —                    | **reserved**, see [Reserved: Arithmetic Coding](encoding_algorithms.md#reserved-arithmetic-coding-0x06) |
| `0x07` | bzip2                | bzip2                                                                                                   |
| `0x08` | RLE                  | hybrid raw/run-length                                                                                   |
| `0x09` | BWT + Huffman        | 64KB blocked BWT + MTF + nibble-level Huffman                                                           |
| `0x0A` | Dictionary           | [replaces the superstring layout](encoding_algorithms.md#dictionary-encoding-0x0a)                      |
| `0xF4` | Huffman (byte-level) | 256-symbol codebook, same wire format as `0x04`                                                         |

`0x06` is reserved (see the table above) and MUST be treated as an unknown strategy code by readers in version 0. All of `0x0B`–`0x0F`, `0x10`–`0xF3` and `0xF5`–`0xFF` are likewise not assigned and MUST be treated as
unknown strategy codes. `0x04` and `0xF4` share one wire format and differ only in alphabet size: see
[Huffman Coding](encoding_algorithms.md#huffman-coding-0x04-0xf4).

#### CIGAR Decomposition Strategies

| Format       | Bytes              | Strategy                             |
| ------------ | ------------------ | ------------------------------------ |
| `0x00??????` | `[00, 00, 00, SS]` | none (identity)                      |
| `0x01??????` | `[01, RR, II, SS]` | numOperations + lengths + operations |
| `0x02??????` | `[02, 00, 00, SS]` | string (treat as plain string)       |

For `DD = 0x00` and `DD = 0x02`, bytes `RR` and `II` are reserved and MUST be `0x00`.

See [CIGAR 4-byte Strategy Code Details](encoding_algorithms.md#cigar-4-byte-strategy-code-details) for wire formats.

### Reader Requirements

- Readers MUST interpret strategy codes as simple byte sequences
- Readers MUST validate that reserved bytes in strategy codes are `0x00`
- Readers MUST validate that strategy code byte patterns match the defined formats
- Readers MUST treat unknown or invalid strategy codes as fatal errors
- Readers MUST treat an unknown `section_id` as a fatal error
- Readers MUST treat a `version` larger than the highest supported version as a fatal error
- Readers MUST treat a truncated block (payload shorter than the sum of the `compressed_*_len` fields) as a
  fatal error

### Error Recovery Guidance

When encountering malformed data, readers should:

1. **Invalid strategy codes**: Treat as fatal errors (cannot recover)
2. **Corrupted payloads**: Treat as a fatal error. A block's payload size is always known from the header,
   so there is no safe way to skip a block whose contents failed to decode: doing so would silently produce
   a file with missing records.
3. **Truncated files**: Report a fatal error with bytes read vs expected.
4. **Unknown section IDs**: Fatal error. Blocks cannot be skipped, because the header layout and the payload
   framing depend on `section_id`.

### Performance Considerations

Different encoding strategies offer tradeoffs between compression ratio and speed:

- **Fastest decompression**: Identity (`0x00??`) and the container compressors, which are a single library call
- **Best compression**: BWT+Huffman (`0x??09`) and Dictionary (`0x??0A`)
- **Balanced approach**: Huffman (`0x??04`) and Zstd (`0x??01`)
- **Specialized**: 2-bit DNA (`0x??05`), RLE (`0x??08`), and the CIGAR decompositions in the 4-byte strategy
  code (see [CIGAR 4-byte Strategy Code Details](encoding_algorithms.md#cigar-4-byte-strategy-code-details))

### Implementation Recommendations

1. **Memory-mapped I/O**: Useful for random access to large BGFA files
2. **Streaming processing**: Process blocks sequentially for memory efficiency
3. **Parallel decompression**: Different blocks can be decompressed in parallel
4. **Caching**: Cache frequently accessed strategy code validations

### Strategy Code Validation Examples

```python
INTEGER_CODES = {0x01, 0x02, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B}
STRING_CODES = {0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x07, 0x08, 0x09, 0x0A, 0xF4}
# SS of a 4-byte CIGAR code operates on an arbitrary byte buffer, so it excludes the
# methods that are defined only for the superstring layout or for DNA columns.
CIGAR_STRING_CODES = {0x00, 0x01, 0x02, 0x03, 0x04, 0xF4}


# Valid 2-byte strategy code. The second byte's set depends on the field type:
# STRING_CODES for `strings`, INTEGER_CODES for `walks` and `uints-delta`.
def is_valid_strings_strategy(code_bytes):
    if len(code_bytes) != 2:
        return False
    integer_byte, string_byte = code_bytes
    return integer_byte in INTEGER_CODES and string_byte in STRING_CODES


def is_valid_integer_strategy(code_bytes):
    if len(code_bytes) != 2:
        return False
    first_byte, second_byte = code_bytes
    return first_byte in INTEGER_CODES and second_byte in INTEGER_CODES


# Valid 4-byte CIGAR strategy code
def is_valid_4byte_cigar_strategy(code_bytes):
    if len(code_bytes) != 4:
        return False
    dd, rr, ii, ss = code_bytes
    # Decomposition strategy
    if dd not in {0x00, 0x01, 0x02}:
        return False
    if dd == 0x00:
        # none decomposition: RR, II and SS are all reserved
        return rr == 0x00 and ii == 0x00 and ss == 0x00
    if dd == 0x02:
        # string decomposition: RR and II reserved, SS compresses the whole buffer
        return rr == 0x00 and ii == 0x00 and ss in CIGAR_STRING_CODES
    # numOperations decomposition: RR and II are integer strategies, SS is the
    # packed operations buffer
    return (rr in INTEGER_CODES and ii in INTEGER_CODES
            and ss in CIGAR_STRING_CODES)
```

Note that a 2-byte code is used for `strings` (first byte integer, second byte string) **and** for
`walks`/`uints-delta` fields (first byte integer, second byte integer). The second byte therefore must be
validated against `STRING_CODES` in the first case and against `INTEGER_CODES` in the second, which is
determined by the field type, not by the code alone. Note also that `SS` in a 4-byte CIGAR code is validated
against `CIGAR_STRING_CODES`, not `STRING_CODES`: see
[CIGAR 4-byte Strategy Code Details](encoding_algorithms.md#cigar-4-byte-strategy-code-details).

## Walks Type Format

The `walks` type encodes a list of walks, where each walk is a sequence of oriented segment IDs. This type is used in the Paths and Walks blocks.
Since we know that there are `record_num` walks in the block, we do not have to store that information again.
The `walks` layout is made by the following sequence of fields.

| Field                | Description                                                                             | Type          |
| -------------------- | --------------------------------------------------------------------------------------- | ------------- |
| `walks_lengths`      | The lengths of the walks                                                                | `uints`       |
| `walks_segments`     | The segment IDs of the walks, delta-encoded (see [Type Definitions](#type-definitions)) | `uints-delta` |
| `walks_orientations` | The orientations of the walks                                                           | `bits`        |

- All lengths of the walks are followed by all segment IDs of the walks (their absolute deltas, then their
  trailing sign `bits` field), followed by all walks orientations.
- The `walks_lengths` field contains exactly `record_num` integers. The i-th integer L(i) is the length of the i-th walk of the block. The sum of all L(i) equals `uncompressed_walk_len` in a Walks block and `uncompressed_paths_len` in a Paths block.
- The `walks_segments` field contains a sequence of `uncompressed_walk_len` (Walks block) or `uncompressed_paths_len` (Paths block) integers. The first L(1) integers form the sequence of segment IDs of the first walk, then the subsequent L(2) integers form the sequence of the segment IDs of the second walk, etc.
- The `walks_orientations` field contains a sequence of `uncompressed_walk_len` (Walks block) or `uncompressed_paths_len` (Paths block) bits. The first L(1) bits form the sequence of segment orientations of the first walk, then the subsequent L(2) bits form the sequence of the segment orientations of the second walk. Orientation `+` or `>` is encoded as `0`, while `-` or `<` is encoded as 1.

### Encoding strategies

The strategy field is `compression_walks` in a Walks block and `compression_paths` in a Paths block.

- `walks_lengths` are encoded using the integer encoding strategy specified in the first byte of that
  field.
- `walks_segments` are encoded using the `uints-delta` type, which applies signed integer encoding (see [Signed Integers](encoding_algorithms.md#signed-integers)). The integer encoding strategy is specified in the second byte of that field and applies to the absolute values of the deltas. There is one delta stream over the **whole field**: the stream is not restarted at walk boundaries.
  For example, for the sequence of segment IDs [50, 48, 61] we compute deltas [50, -2, 13]. The sign bits are [0, 1, 0] and the absolute values [50, 2, 13] are encoded per the integer strategy.
- the `walks_orientations` field is always encoded as a bit sequence [Packed Bits](#packed-bits).

**Example:** Consider a walks block with 2 walks:

- Walk 1: `0+1-` (length 2, segments 0 and 1 with orientations + and -)
- Walk 2: `1+2+3-` (length 3, segments 1, 2 and 3 with orientations +, +, and -)

The concatenated segment ID sequence is [0, 1, 1, 2, 3] (5 elements = `uncompressed_walk_len`). This would be
encoded as:

- `walks_lengths`: [2, 3] (encoded per the integer strategy in the first byte of `compression_walks`)
- `walks_segments`: the deltas of [0, 1, 1, 2, 3] are [0, +1, 0, +1, +1], so the sign bits are [0, 0, 0, 0, 0]
  (packed into a trailing `bits` field) and the absolute values are [0, 1, 0, 1, 1], encoded per the integer
  strategy in the second byte of `compression_walks`. The single delta stream continues across the walk
  boundary (segment 1 of walk 2 is delta 0 against segment 1 of walk 1).
- `walks_orientations`: [0, 1, 0, 0, 1] (0=+, 1=- for each segment), packed as bits

## Walks and Paths: Type Note

Both the Walks and Paths blocks use the `walks` type to encode sequences of oriented segment IDs. The encoding is identical in both cases: a list of walks, where each walk is a sequence of segment IDs with orientations.

The key difference is in the surrounding metadata:

- **Walks block**: Each walk is associated with sample ID, haplotype, sequence ID, and positional metadata.
- **Paths block**: Each walk is associated with a path name and optional CIGAR strings.

The `compression_walks` (Walks block) and `compression_paths` (Paths block) fields both use 2-byte strategy codes from the [Encoding Method Reference](#encoding-method-reference).

## Packed Bits

A `bits` field represents a list of bits packed into `uint64` words in little-endian format.

**Packing strategy:**

- Bits are packed LSB-first within each `uint64` word
- Bit at index `i` is stored at position `i % 64` within word `i // 64`
- The number of `uint64` words is `ceil(n / 64)` where `n` is the number of bits
- Unused bits in the final word (if any) are set to 0 when writing and MUST be ignored when reading

**Determining the number of bits (n):** The value of `n` depends on the context:

- **Links block orientations** (`from_orientation`, `to_orientation`): `n = record_num` from the block header
- **Walks type orientations** (`walks_orientations`): `n` is the total number of segment occurrences in the
  containing block header, i.e. `uncompressed_walk_len` in a Walks block and `uncompressed_paths_len` in a
  Paths block
- **`uints-delta` sign bits**: `n` is the number of integers in the field, i.e. `record_num` for each of the
  Walks `start_positions` and `end_positions` sub-fields, and `uncompressed_walk_len` (Walks block) or
  `uncompressed_paths_len` (Paths block) for `walks_segments`

**Size calculation:** Number of uint64 words = `ceil(n / 64)`. Total bytes for a `bits` field = `8 * ceil(n / 64)`.
A `bits` field therefore always occupies a whole number of 8-byte words; it is never packed tightly against a
neighbouring field.

**Examples:**

- Orientations `[1, 0, 1, 1, 0, ...]` with `n = 64`: bit 0 = 1, bit 1 = 0, bit 2 = 1, bit 3 = 1, bit 4 = 0, so
  word 0 = `0x0D` (written out: `0b00000000_00000000_00000000_00001101`), stored little-endian as
  `0D 00 00 00 00 00 00 00`. 8 bytes.
- Orientations with `n = 155`: `8 * ceil(155 / 64)` = `8 * 3` = **24 bytes**, not 20. Bits 0..154 are stored and
  bits 155..191 of the last word are padding.
- `n = 0`: 0 bytes. A `bits` field with no bits still occupies no space.

## Conformance Requirements

**Minimum reader requirements:** The set of encodings that a version 1.0 reader MUST support is **not yet
defined**. Until it is, a compliant reader MUST at minimum support `none`, `varint`, `fixed16`, `fixed32`,
`fixed64`, `zstd` and `gzip`, and MUST treat every other encoding it does not implement as an unknown strategy
code (fatal error), which includes the reserved code `0x06`. The definitive minimum set will be fixed when
version 1.0 is released.

**Writer requirements:** A compliant BGFA writer:

- MUST produce valid BGFA files that can be read by any compliant reader
- MUST set reserved fields to 0
- MUST NOT write empty blocks (blocks with `record_num = 0`). If a block type has no records, omit the block entirely.
- MUST NOT write segment IDs that are not defined by some Segments block in the same file
- MUST NOT write a Walks `sequence_id` that is not defined by some Segments block in the same file. A
  writer converting a GFA file whose `W` record names a sequence that is not present as a segment name in
  the same GFA file MUST first emit that sequence as a segment record, or drop the walk

**Error handling:**

- A reader encountering an unknown `section_id` MUST treat it as a fatal error.
- A reader encountering an unknown strategy code MUST treat it as a fatal error.
- A reader encountering a `version` larger than the highest supported version MUST treat it as a fatal error.
- A reader encountering truncated or corrupted data MUST treat it as a fatal error.
- A reader resolving a segment ID, including a Walks `sequence_id`, to a segment name that no Segments block
  defines MUST treat it as a fatal error, and MUST NOT substitute a placeholder or a default name. This
  applies once the whole file has been read, since the defining block MAY appear later in the file; a reader
  that does not resolve IDs at all is not required to perform the check, as set out in
  [Segments Block](#segments-block).

## Known Limitations of Version 0

The following information present in GFA is **not representable** in BGFA version 0. Writers MUST drop it and
readers MUST NOT expect it:

- **Link overlap coordinates.** A GFA L record may carry `from_iss`, `from_ie`, `to_iss` and `to_ie`. BGFA
  stores only the two oriented segment IDs and the CIGAR string, so the overlap coordinates are lost.
- **Tags.** All optional GFA tags are dropped, including `LN`, `RC`, `FC`, `KC`, `SH`, `UR` and `UB`.
- **Segment sequences of `*`.** A segment with no sequence is stored as the empty string, which is
  indistinguishable from a segment whose sequence was intentionally written as a zero-length string.
- **Walk end positions.** The field exists but is always written as `0`, so it round-trips as "no end
  position". See the note in the [Walks Block](#walks-block).
- **Walk sequence names.** A Walks `sequence_id` is an internal segment ID, not a sequence name, and BGFA
  version 0 defines no Sequence block at all: section ID 1 is not defined and MUST be treated as a fatal
  error. A reference sequence therefore survives a round trip only if a converter also emits it as a segment
  record, and that record carries the reference's sequence as its segment sequence. A GFA `W` record whose
  `SeqID` is not a segment name in the same file does not round-trip, and the reference's own metadata
  (length, source URI, and any `SN` name distinct from the segment name) is not stored. See the
  `sequence_id` entry in the [Walks Block](#walks-block).
- **Paths with no segments.** A path must contain at least one segment occurrence, so the empty path (`P` line
  with no segments) has no representation.
- **Comment lines.** GFA `#` lines are not stored. A reader MUST NOT expect them.

## Appendix A: Example BGFA File

This appendix shows the complete byte-level encoding of a BGFA file built from the GFA file below, taken from
`pygfa/data/example_4.gfa`.

```
# test: read_gfa
# test: bgfa_roundtrip
# test: bgfa
# benchmark: bgfa_compression
# benchmark: single_param
H	VN:Z:1.0
S	sas	ACCTT
S	sbs	TCAAGGAC
S	scs	CTTGATT
L	sas	+	sbs	-	*
L	sbs	-	scs	+	*
P	p01	sas+,sbs-,scs+
W	NA12878	1	scs	1	7	scs-
W	NA12878	2	sas	1	5	sas+
```

The two walks are placed on the segments `scs` and `sas`, which are segment IDs `2` and `0`, so the
`sequence_ids` values written below are `2` and `0` and the names are recovered by looking them up in the
Segments block. Each `SeqEnd` is the last covered position of its own segment, so the source records are
coordinateally valid; BGFA writes `0` in `end_positions` whatever that column holds, which is what the A.6
round-trip shows. See the note in the [Walks Block](#walks-block).

All strategy codes in this example use `none` (`0x00`) for strings and `varint` (`0x01`) for integers, so
the file is uncompressed and can be verified by hand. Segment IDs are assigned in file order:
`sas` = 0, `sbs` = 1, `scs` = 2.

The superstring heuristic is not part of the format — any superstring is valid as long as the positions are
consistent. In this example no overlap was found, so the superstrings are plain concatenations.

### A.1 File header (17 bytes, offsets 0-16)

| Field          | Bytes                     | Value      |
| -------------- | ------------------------- | ---------- |
| `magic_number` | `42 47 46 41`             | "BGFA"     |
| `version`      | `00 00`                   | 0          |
| `header_len`   | `08 00`                   | 8          |
| `header_text`  | `56 4E 3A 5A 3A 31 2E 30` | "VN:Z:1.0" |
| terminator     | `00`                      | `\0`       |

`header_text` is the 8 bytes `56 4E 3A 5A 3A 31 2E 30`, matching `header_len = 8`; the trailing `00` in the
next row is the null terminator, which is not counted by `header_len`.

### A.2 Segments block (82 bytes, offsets 17-98)

Header (39 bytes):

| Field                            | Bytes                     | Value         |
| -------------------------------- | ------------------------- | ------------- |
| `section_id`                     | `02`                      | 2 = segments  |
| `record_num`                     | `03 00`                   | 3             |
| `compression_segment_names`      | `01 00`                   | varint + none |
| `compressed_segment_names_len`   | `10 00 00 00 00 00 00 00` | 16            |
| `uncompressed_segment_names_len` | `09 00 00 00 00 00 00 00` | 9             |
| `compression_segment_label`      | `01 00`                   | varint + none |
| `compressed_segment_label_len`   | `1B 00 00 00 00 00 00 00` | 27            |
| `uncompressed_segment_label_len` | `14 00 00 00 00 00 00 00` | 20            |

Payload (43 bytes), starting at offset 56:

| Offset | Bytes                                                         | Meaning                                   |
| ------ | ------------------------------------------------------------- | ----------------------------------------- |
| 56     | `00 03 06`                                                    | `segment_names` start positions [0, 3, 6] |
| 59     | `03 06 09`                                                    | `segment_names` end positions [3, 6, 9]   |
| 62     | `09`                                                          | `segment_names` blob length (9)           |
| 63     | `73 61 73 73 62 73 73 63 73`                                  | superstring `sassbsscs`                   |
| 72     | `00 05 0D`                                                    | `sequences` start positions [0, 5, 13]    |
| 75     | `05 0D 14`                                                    | `sequences` end positions [5, 13, 20]     |
| 78     | `14`                                                          | `sequences` blob length (20)              |
| 79     | `41 43 43 54 54 54 43 41 41 47 47 41 43 43 54 54 47 41 54 54` | superstring `ACCTTTCAAGGACCTTGATT`        |

16 = 6 bytes of positions + 1 byte of blob length + 9 bytes of superstring.
27 = 6 bytes of positions + 1 byte of blob length + 20 bytes of superstring.

### A.3 Links block (56 bytes, offsets 99-154)

Header (32 bytes):

| Field                           | Bytes                     | Value                                                  |
| ------------------------------- | ------------------------- | ------------------------------------------------------ |
| `section_id`                    | `03`                      | 3 = links                                              |
| `record_num`                    | `02 00`                   | 2                                                      |
| `compression_fromto`            | `01`                      | varint for both `uints` lists                          |
| `compressed_fromto_len`         | `14 00 00 00 00 00 00 00` | 20                                                     |
| `compression_links_cigars`      | `00 00 00 00`             | none decomposition (`DD = 0x00`, all reserved bytes 0) |
| `compressed_links_cigars_len`   | `04 00 00 00 00 00 00 00` | 4                                                      |
| `uncompressed_links_cigars_len` | `02 00 00 00 00 00 00 00` | 2                                                      |

Payload (24 bytes), starting at offset 131:

| Offset | Bytes                     | Meaning                                     |
| ------ | ------------------------- | ------------------------------------------- |
| 131    | `00 01`                   | `from_ids` [0, 1]                           |
| 133    | `01 02`                   | `to_ids` [1, 2]                             |
| 135    | `02 00 00 00 00 00 00 00` | `from_orientation` [+ -], LSB-first `0x02`  |
| 143    | `01 00 00 00 00 00 00 00` | `to_orientation` [- +], LSB-first `0x01`    |
| 151    | `2A 0A 2A 0A`             | CIGARs `*` and `*`, each terminated by `\n` |

The two `bits` fields occupy the last 16 bytes of the 20-byte region, so `from_ids` and `to_ids` occupy the
first 20 - 16 = 4 bytes. With `record_num = 2` each bit field is one word, `8 * ceil(2 / 64) = 8` bytes.

### A.4 Paths block (86 bytes, offsets 155-240)

Header (59 bytes):

| Field                           | Bytes                     | Value                                                  |
| ------------------------------- | ------------------------- | ------------------------------------------------------ |
| `section_id`                    | `04`                      | 4 = paths                                              |
| `record_num`                    | `01 00`                   | 1                                                      |
| `compression_path_names`        | `01 00`                   | varint + none                                          |
| `compressed_path_names_len`     | `06 00 00 00 00 00 00 00` | 6                                                      |
| `uncompressed_path_names_len`   | `03 00 00 00 00 00 00 00` | 3                                                      |
| `compression_paths`             | `01 01`                   | varint + varint                                        |
| `compressed_paths_len`          | `14 00 00 00 00 00 00 00` | 20                                                     |
| `uncompressed_paths_len`        | `03 00 00 00 00 00 00 00` | 3                                                      |
| `compression_paths_cigars`      | `00 00 00 00`             | none decomposition (`DD = 0x00`, all reserved bytes 0) |
| `compressed_paths_cigars_len`   | `01 00 00 00 00 00 00 00` | 1                                                      |
| `uncompressed_paths_cigars_len` | `00 00 00 00 00 00 00 00` | 0                                                      |

Payload (27 bytes), starting at offset 214:

| Offset | Bytes                     | Meaning                                                                              |
| ------ | ------------------------- | ------------------------------------------------------------------------------------ |
| 214    | `00`                      | `path_names` start position [0]                                                      |
| 215    | `03`                      | `path_names` end position [3]                                                        |
| 216    | `03`                      | `path_names` blob length (3)                                                         |
| 217    | `70 30 31`                | superstring `p01`                                                                    |
| 220    | `03`                      | `walks_lengths` [3]                                                                  |
| 221    | `00 01 01`                | `walks_segments` absolute deltas [0, 1, 1]                                           |
| 224    | `00 00 00 00 00 00 00 00` | `walks_segments` sign bits (3 bits, all 0)                                           |
| 232    | `02 00 00 00 00 00 00 00` | `walks_orientations` [+, -, +], LSB-first `0x02`                                     |
| 240    | `0A`                      | CIGARs: the path has no CIGAR, so the single empty entry is just the `\n` terminator |

6 = 2 bytes of positions + 1 byte of blob length + 3 bytes of superstring. 20 = 1 byte of `walks_lengths` +
3 bytes of absolute deltas + 8 bytes of sign bits + 8 bytes of the `uint64` word of `walks_orientations`
(`8 * ceil(3 / 64) = 8` each). The path has no CIGAR, so the CIGAR list holds one empty string, which the `none`
decomposition writes as a lone `\n`.

### A.5 Walks block (154 bytes, offsets 241-394)

Header (91 bytes):

| Field                         | Bytes                     | Value                          |
| ----------------------------- | ------------------------- | ------------------------------ |
| `section_id`                  | `05`                      | 5 = walks                      |
| `record_num`                  | `02 00`                   | 2                              |
| `compression_sample_ids`      | `01 00`                   | varint + none                  |
| `compression_haplotype`       | `01`                      | varint for `haplotype_indices` |
| `compression_sequence`        | `01`                      | varint for `sequence_ids`      |
| `compression_positions_start` | `01`                      | varint for the start positions |
| `compression_positions_end`   | `01`                      | varint for the end positions   |
| `compression_walks`           | `01 01`                   | varint + varint                |
| `compressed_sample_ids_len`   | `13 00 00 00 00 00 00 00` | 19                             |
| `uncompressed_sample_ids_len` | `0E 00 00 00 00 00 00 00` | 14                             |
| `compressed_haplotype_len`    | `02 00 00 00 00 00 00 00` | 2                              |
| `uncompressed_haplotype_len`  | `02 00 00 00 00 00 00 00` | 2                              |
| `compressed_sequence_len`     | `02 00 00 00 00 00 00 00` | 2                              |
| `uncompressed_sequence_len`   | `02 00 00 00 00 00 00 00` | 2                              |
| `compressed_positions_len`    | `14 00 00 00 00 00 00 00` | 20                             |
| `uncompressed_positions_len`  | `04 00 00 00 00 00 00 00` | 4                              |
| `compressed_walk_len`         | `14 00 00 00 00 00 00 00` | 20                             |
| `uncompressed_walk_len`       | `02 00 00 00 00 00 00 00` | 2                              |

The header is `1 + 2 + 2 + 4 + 2` bytes of section ID, record count and strategy codes, followed by ten
8-byte length fields: `11 + 80 = 91` bytes.

`compression_walks` is a 2-byte code whose second byte is validated against the integer code set rather
than the string code set, because the `walks` type holds integers; see
[Encoding strategies](#encoding-strategies).

Payload (63 bytes), starting at offset 332:

| Offset | Bytes                                       | Meaning                                                                            |
| ------ | ------------------------------------------- | ---------------------------------------------------------------------------------- |
| 332    | `00 07`                                     | `sample_ids` start position [0, 7]                                                 |
| 334    | `07 0E`                                     | `sample_ids` end position [7, 14]                                                  |
| 336    | `0E`                                        | `sample_ids` blob length (14)                                                      |
| 337    | `4E 41 31 32 38 37 38 4E 41 31 32 38 37 38` | superstring `NA12878NA12878`                                                       |
| 351    | `01 02`                                     | `haplotype_indices` [1, 2]                                                         |
| 353    | `02 00`                                     | `sequence_ids` [2, 0]                                                              |
| 355    | `01 00`                                     | `start_positions` absolute deltas [1, 0]                                           |
| 357    | `00 00`                                     | `end_positions` absolute deltas [0, 0]                                             |
| 359    | `00 00 00 00 00 00 00 00`                   | `start_positions` sign bits (2 bits, both 0)                                       |
| 367    | `00 00 00 00 00 00 00 00`                   | `end_positions` sign bits (2 bits, both 0)                                         |
| 375    | `01 01`                                     | `walks_lengths` [1, 1]                                                             |
| 377    | `02 02`                                     | `walks_segments` absolute deltas [2, 2]                                            |
| 379    | `02 00 00 00 00 00 00 00`                   | `walks_segments` sign bits [0, 1], LSB-first `0x02`                                |
| 387    | `01 00 00 00 00 00 00 00`                   | `walks_orientations` [-, +], LSB-first `0x01`                                      |

19 = 4 bytes of positions (2 starts, 2 ends) + 1 byte of blob length + 14 bytes of superstring.
20 = 2 bytes of start-position absolute values + 2 bytes of end-position absolute values + 8 bytes of
start-position sign bits + 8 bytes of end-position sign bits. Each `uints-delta` field is its absolute
values followed by its sign `bits` field, so `01 00` are the start-position magnitudes [1, 0] and the
following 8 bytes hold the two sign bits (both 0); the end positions follow the same shape with
magnitude `0`.
20 = 2 bytes of `walks_lengths` + 2 bytes of absolute deltas + 8 bytes of sign bits + 8 bytes of the
`uint64` word of `walks_orientations` (`8 * ceil(2 / 64) = 8` each).

The two walks have segment IDs [2, 0], so the single delta stream over the whole field is [2, -2]: the
sign bits are [0, 1] and the absolute values are [2, 2]. The stream is **not** restarted at the walk
boundary, which is why both records share one delta stream and one absolute-value list.

Four features of this block are worth checking against the rules above:

- `end_positions` holds `0` for both records because the field is unused, not because the walks are empty.
  The source GFA gives them `SeqEnd` values of 7 and 5, and BGFA discards them regardless; readers MUST
  decode and discard the field, and the bytes are still present and counted in
  `compressed_positions_len`. This is the round-trip limitation listed in
  [Known Limitations of Version 0](#known-limitations-of-version-0), demonstrated rather than avoided.
- `sequence_ids` holds the **segment IDs** `2` and `0`, which are `scs` and `sas`, not the strings `scs`
  and `sas`. The names are recovered from the Segments block in A.2.
- `haplotype_indices` is 1-based, so the two records carry `1` and `2` for the two haplotypes of sample
  `NA12878`.
- The single delta stream spans the walk boundary, so the change of sign between the two walks is absorbed
  inside one delta stream rather than starting a new one.

### A.6 Round-trip

Decoding the 395 bytes with a reader written from this specification and re-emitting GFA yields the records
below. They match the input GFA except in two documented ways: the `#` comment lines are not stored, and
both walk `SeqEnd` values are lost, `7` and `5` coming back as `0` because `end_positions` is unused (see
A.5 and [Known Limitations of Version 0](#known-limitations-of-version-0)). Every other column, both
`SeqID` values included, round-trips unchanged: each is recovered by resolving the stored segment ID
against the Segments block in A.2, so ID `2` returns `scs` and ID `0` returns `sas`.

```
H	VN:Z:1.0
S	sas	ACCTT
S	sbs	TCAAGGAC
S	scs	CTTGATT
L	sas	+	sbs	-	*
L	sbs	-	scs	+	*
P	p01	sas+,sbs-,scs+
W	NA12878	1	scs	1	0	scs-
W	NA12878	2	sas	1	0	sas+
```

Total size: 395 bytes (17 + 82 + 56 + 86 + 154).

Full hex dump of the file:

```
   0  42 47 46 41 00 00 08 00 56 4e 3a 5a 3a 31 2e 30  BGFA....VN:Z:1.0
  16  00 02 03 00 01 00 10 00 00 00 00 00 00 00 09 00  ................
  32  00 00 00 00 00 00 01 00 1b 00 00 00 00 00 00 00  ................
  48  14 00 00 00 00 00 00 00 00 03 06 03 06 09 09 73  ...............s
  64  61 73 73 62 73 73 63 73 00 05 0d 05 0d 14 14 41  assbsscs.......A
  80  43 43 54 54 54 43 41 41 47 47 41 43 43 54 54 47  CCTTTCAAGGACCTTG
  96  41 54 54 03 02 00 01 14 00 00 00 00 00 00 00 00  ATT.............
 112  00 00 00 04 00 00 00 00 00 00 00 02 00 00 00 00  ................
 128  00 00 00 00 01 01 02 02 00 00 00 00 00 00 00 01  ................
 144  00 00 00 00 00 00 00 2a 0a 2a 0a 04 01 00 01 00  .......*.*......
 160  06 00 00 00 00 00 00 00 03 00 00 00 00 00 00 00  ................
 176  01 01 14 00 00 00 00 00 00 00 03 00 00 00 00 00  ................
 192  00 00 00 00 00 00 01 00 00 00 00 00 00 00 00 00  ................
 208  00 00 00 00 00 00 00 03 03 70 30 31 03 00 01 01  .........p01....
 224  00 00 00 00 00 00 00 00 02 00 00 00 00 00 00 00  ................
 240  0a 05 02 00 01 00 01 01 01 01 01 01 13 00 00 00  ................
 256  00 00 00 00 0e 00 00 00 00 00 00 00 02 00 00 00  ................
 272  00 00 00 00 02 00 00 00 00 00 00 00 02 00 00 00  ................
 288  00 00 00 00 02 00 00 00 00 00 00 00 14 00 00 00  ................
 304  00 00 00 00 04 00 00 00 00 00 00 00 14 00 00 00  ................
 320  00 00 00 00 02 00 00 00 00 00 00 00 00 07 07 0e  ................
 336  0e 4e 41 31 32 38 37 38 4e 41 31 32 38 37 38 01  .NA12878NA12878.
 352  02 02 00 01 00 00 00 00 00 00 00 00 00 00 00 00  ................
 368  00 00 00 00 00 00 00 01 01 02 02 02 00 00 00 00  ................
 384  00 00 00 01 00 00 00 00 00 00 00                 ...........
```
