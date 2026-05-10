# Binary GFA format

## Table of Contents

- [Binary GFA file: overall structure](#binary-gfa-file-overall-structure)
- [Conventions](#conventions)
  - [Type Definitions](#type-definitions)
  - [Strategy Code Format Summary](#strategy-code-format-summary)
    - [Byte-by-Byte Strategy Code Formats](#byte-by-byte-strategy-code-formats)
    - [Strategy Code Reference Table](#strategy-code-reference-table)
  - [Encoding Method Reference](#encoding-method-reference)
  - [Reader Requirements](#reader-requirements)
  - [Error Recovery Guidance](#error-recovery-guidance)
  - [Performance Considerations](#performance-considerations)
  - [Implementation Recommendations](#implementation-recommendations)
  - [Strategy Code Validation Examples](#strategy-code-validation-examples)
  - [Terminology](#terminology)
  - [How to Read a Block](#how-to-read-a-block)
- [File Header Section](#file-header-section)
- [Segments Block](#segments-block)
- [Links Block](#links-block)
- [Paths Block](#paths-block)
- [Walks Block](#walks-block)
- [Walks Type Format](#walks-type-format)
- [Walks and Paths: Type Note](#walks-and-paths-type-note)
- [Packed Bits](#packed-bits)
- [Conformance Requirements](#conformance-requirements)
- [Appendix A: Example BGFA Files](#appendix-a-example-bgfa-files)

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
| 1   | Reserved   | Formerly Segment Names; merged into Segments block    |
| 2   | Segments   | Segment names and sequences                           |
| 3   | Links      | Link connections and CIGAR alignments                 |
| 4   | Paths      | Paths with oriented segment IDs and CIGAR strings     |
| 5   | Walks      | Walks with sample/haplotype metadata and orientations |

Each block has a header and a payload.
The header contains all metadata, including the strategy used to compress data, the size of the compressed data, and
the size of the uncompressed data.
The payload contains the compressed data blobs.
For each header data we provide a type that allows us to determine its size. The only exception is the file header,
where the `header_len` field must also be read to determine the size of the file header.

### Terminology

- **Record:** A single entry within a block (e.g., one segment, one link, one walk).
- **Block:** A contiguous section of the file containing a header and a payload.
- **Section:** Synonym for block type, identified by `section_id`.
- **Payload:** The encoded data portion of a block, following the header.
- **Field:** A single information written in the file

### How to Read a Block

To read a block from a BGFA file, a reader follows these steps:

1. **Read the block header**: Parse the `section_id` (1 byte) to determine the block type, then parse the remaining header fields according to the block type's header layout.
2. **Determine payload size**: The total payload size is the sum of all `compressed_*_len` fields in the header. Each `compressed_*_len` includes both the integer metadata list and the compressed blob for that field.
3. **Parse each payload field**: For each field, use the strategy code to determine how to decode it. The strategy
   codes are different, depending on the type of data we want to store. For `strings` fields, read the metadata (integer positions list encoded per the first-byte strategy), then read the compressed blob (encoded per the second-byte strategy). For `uints` fields, the entire payload is the integer list encoded per the strategy code. For `uints-delta` fields, the entire payload is the signed integer encoded delta list (see [Signed Integers](encoding_algorithms.md#signed-integers)). For `bits` fields, read raw bits using the known bit count (see [Packed Bits](#packed-bits)).
4. **Reconstruct data**: Use the metadata and strategy codes to decode each field back to its original form.

For implementation details of each encoding method, see [encoding_algorithms.md](encoding_algorithms.md).

**Key principle:** Every `compressed_*_len` field in the header tells you exactly how many bytes to read for its corresponding payload field. The reader sums these to find the total payload boundary, then processes each field sequentially within the payload.

## File Header Section

| Field          | Description                                             | Type                      |
| -------------- | ------------------------------------------------------- | ------------------------- |
| `magic_number` | Magic number for bgfa files = "BGFA" (0x41464742)       | `uint32`                  |
| `version`      | Format version (progressive number, starts at 0)        | `uint16`                  |
| `header_len`   | length of the header string (excluding null terminator) | `uint16`                  |
| `header_text`  | GFA header text                                         | `bytes` + null terminator |

**Clarification:** The `header_text` field is stored as `header_len` bytes of ASCII text followed by a single null terminator byte (`\0`). The `header_len` field specifies the length of the text portion only. Total bytes consumed = 8 (`magic` + `version` + `header_len`) + `header_len` + 1 (null terminator).

**Note:** The magic number 0x41464742 corresponds to ASCII "BGFA" when read as little-endian bytes: 0x42='B', 0x47='G', 0x46='F', 0x41='A'.

**Version:** The version field is a progressive integer starting at 0. It has no semantic meaning (no major/minor interpretation).

## Segments Block

We associate an internal segment ID to each segment name, where the segment ID is an
incrementing integer starting at 0. Segment IDs are assigned in the order segment names appear in the file.

### Header

| Field                            | Description                                                 | Type       |
| -------------------------------- | ----------------------------------------------------------- | ---------- |
| `section_id`                     | Section type (2 = segments)                                 | `uint8`    |
| `record_num`                     | number of records in the block                              | `uint16`   |
| `compression_segment_names`      | Encoding strategy for the segment names (2 bytes)           | `bytes[2]` |
| `compressed_segment_names_len`   | length of compressed segment names field                    | `uint64`   |
| `uncompressed_segment_names_len` | sum of the lengths of the uncompressed segment names        | `uint64`   |
| `compression_segment_label`      | Encoding strategy for the segment sequences (2 bytes)       | `bytes[2]` |
| `compressed_segment_label_len`   | length of compressed segment_sequences field                | `uint64`   |
| `uncompressed_segment_label_len` | sum of the lengths of uncompressed segment_sequences fields | `uint64`   |

The length of the uncompressed segment names does not include any terminator character.

### Payload

| Field           | Description       | Type      |
| --------------- | ----------------- | --------- |
| `segment_names` | Segment names     | `strings` |
| `sequences`     | Segment sequences | `strings` |

**Layout:** The payload consists of encoded segment names followed by encoded sequences.
We have two distinct encoding strategies.

## Links Block

Each block consists of a header and a payload.

### Header

The following is the sequence of fields making up the header.

| Field                           | Description                                            | Type       |
| ------------------------------- | ------------------------------------------------------ | ---------- |
| `section_id`                    | Section type (3 = links)                               | `uint8`    |
| `record_num`                    | number of records in the block                         | `uint16`   |
| **From/To field**               |                                                        |            |
| `compression_fromto`            | Encoding strategy for the from/to fields               | `bytes[2]` |
| `compressed_fromto_len`         | length of compressed from/to payload (metadata + blob) | `uint64`   |
| **CIGAR field**                 |                                                        |            |
| `compression_links_cigars`      | Encoding strategy for the cigar strings (4 bytes)      | `bytes[4]` |
| `compressed_links_cigars_len`   | length of compressed cigars payload (metadata + blob)  | `uint64`   |
| `uncompressed_links_cigars_len` | sum of the lengths of uncompressed cigars              | `uint64`   |

### Payload

The following is the sequence of fields making up the payload layout.
Each field is padded so that it is aligned with a byte.
For example, if the list of `from_ids` requires 155 bits, it is padded with 5 additional zero bits, so that the overall
length is 20 bytes.

| Field                 | Description                                       | Type                         |
| --------------------- | ------------------------------------------------- | ---------------------------- |
| `from_ids`            | Tail segment IDs (1-based; 0 = no connection)     | `uints`                      |
| `to_ids`              | Head segment IDs (1-based; 0 = no connection)     | `uints`                      |
| `from_orientation`    | Orientations of all from segments. 0 is +, 1 is - | `bits` (length = record_num) |
| `to_orientation`      | Orientations of all to segments. 0 is +, 1 is -   | `bits` (length = record_num) |
| `links_cigar_strings` | CIGAR strings                                     | `cigar strings`              |

**Segment ID encoding:** Segment IDs in the links payload are stored as 1-based indices into the segment list (value = internal_segment_id + 1, where internal IDs start at 0). The value 0 is reserved to indicate "no connection". The reader converts back to 0-based by subtracting 1.

**Orientation mapping:** The i-th bit in `from_orientation` corresponds to the i-th segment ID in `from_ids`. Similarly, the i-th bit in `to_orientation` corresponds to the i-th segment ID in `to_ids`.
Therefore there are exactly `record_num` segment IDs in both the `from_ids` and in the `to_ids` lists and there are exactly
`record_num` bits in both the `from_orientation` and in the `to_orientations` lists.

Orientation bits are stored with a least significant bit (LSB-first) strategy within each `uint64` word. See the "Bits" section for details.

## Paths Block

Each block consists of a header and a payload.

### Header

The following is the sequence of fields making up the header.

| Field                          | Description                                                      | Type       |
| ------------------------------ | ---------------------------------------------------------------- | ---------- |
| `section_id`                   | Section type (4 = paths)                                         | `uint8`    |
| `record_num`                   | number of records in the block                                   | `uint16`   |
| `compression_path_names`       | Encoding strategy for the path names (2 bytes)                   | `bytes[2]` |
| `compressed_path_names_len`    | length of compressed path names                                  | `uint64`   |
| `uncompressed_path_names_len`  | length of uncompressedpath names                                 | `uint64`   |
| `compression_paths`            | Encoding strategy for the paths as list of segment IDs (4 bytes) | `bytes[2]` |
| `compressed_paths_len`         | length of compressed paths                                       | `uint64`   |
| `uncompressed_paths_len`       | sum of the lengths of uncompressed paths (as segment ID strings) | `uint64`   |
| `compression_paths_cigars`     | Encoding strategy for the cigar strings (4 bytes)                | `bytes[4]` |
| `compressed_paths_len_cigar`   | length of compressed cigars                                      | `uint64`   |
| `uncompressed_paths_len_cigar` | sum of the lengths of uncompressed cigars strings                | `uint64`   |

### Payload

The following is the sequence of fields making up the payload layout.

| Field                 | Description                                            | Type            |
| --------------------- | ------------------------------------------------------ | --------------- |
| `path_names`          | Path names                                             | `strings`       |
| `paths`               | Paths, each path is a sequence of oriented segment IDs | `walks`         |
| `paths_cigar_strings` | The list of CIGAR strings                              | `cigar strings` |

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
| `compression_hep`             | Encoding strategy for the haplotype indices (2 bytes)                | `bytes[2]` |
| `compression_sequence`        | Encoding strategy for the sequence IDs                               | `byte`     |
| `compression_positions_start` | Encoding strategy for the start positions                            | `byte`     |
| `compression_positions_end`   | Encoding strategy for the end positions                              | `byte`     |
| `compression_walks`           | Encoding strategy for the walks (4 bytes)                            | `bytes[2]` |
| **Samples field**             |                                                                      |            |
| `compressed_sample_ids_len`   | length of compressed sample IDs payload (metadata + blob)            | `uint64`   |
| `uncompressed_sample_ids_len` | sum of the lengths of uncompressed sample IDs                        | `uint64`   |
| **Haplotype indices field**   |                                                                      |            |
| `compressed_hep_len`          | length of compressed haplotype indices payload (metadata + blob)     | `uint64`   |
| `uncompressed_hep_len`        | sum of the lengths of uncompressed haplotype indices                 | `uint64`   |
| **Sequence IDs field**        |                                                                      |            |
| `compressed_sequence_len`     | length of compressed sequence IDs payload (metadata + blob)          | `uint64`   |
| `uncompressed_sequence_len`   | sum of the lengths of uncompressed sequence IDs                      | `uint64`   |
| **Positions field**           |                                                                      |            |
| `compressed_positions_len`    | length of compressed positions payload (metadata + blob)             | `uint64`   |
| `uncompressed_positions_len`  | sum of the lengths of uncompressed positions                         | `uint64`   |
| **Walks field**               |                                                                      |            |
| `compressed_walk_len`         | length of compressed walks payload (metadata + blob)                 | `uint64`   |
| `uncompressed_walk_len`       | sum of the lengths of uncompressed walks (total segment occurrences) | `uint64`   |

### Payload

The following is the sequence of fields making up the payload layout.

| Field               | Description                                            | Type          |
| ------------------- | ------------------------------------------------------ | ------------- |
| `sample_ids`        | Sample IDs                                             | `strings`     |
| `haplotype_indices` | Haplotype indices                                      | `uints`       |
| `sequence_ids`      | Sequence IDs                                           | `strings`     |
| `start_positions`   | Start positions                                        | `uints-delta` |
| `end_positions`     | End positions                                          | `uints-delta` |
| `walks`             | Walks, each walk is a sequence of oriented segment IDs | `walks`       |

Since there are `record_num` records in the block, the block contains `record_num` sample IDs, followed by `record_num`
haplotype indices, followed by `record_num` sequence IDs, followed by `record_num` start positions, followed by
`record_num` end positions, followed by `record_num` walks.

## Conventions

**Block ordering constraints:**

- Blocks of the same type are not required to be contiguous
- Different section types can appear in any order relative to each other.

**Endianness:** All multi-byte integer fields (`uint16`, `uint32`, `uint64`) are encoded in little-endian format. Strategy codes and other byte sequences have no endianness considerations as they are simple sequences of bytes.

**Alignment:** All fields begin at the next byte boundary after the previous field. No inter-field padding is applied. Fields are packed contiguously without gaps.

All bytes data and all data that are encoded with a variable number of bits are packed into bytes. Any remaining bits in
the final byte of the bitstream are set to 0 (when writing) and MUST be ignored (when reading).

**C strings:** The reference to C strings (ASCII terminated by `\0`) is for context only.
Input strings to the `strings` type do NOT include null terminators. Strings are stored as raw ASCII bytes without termination.

### Type Definitions

- `uints`: A list of unsigned integers encoded according to the specified integer encoding strategy (see [Encoding Method Reference](#encoding-method-reference)).
- `uints-delta`: A list of unsigned integers encoded as delta differences. The first value is stored as-is; each subsequent value is the difference with the previous value. The resulting signed integers are encoded according to the signed integer encoding strategy (see [Signed Integers](encoding_algorithms.md#signed-integers)).
- `strings`: A list of strings encoded according to the string encoding strategy. See [String Encoding Overview](encoding_algorithms.md#string-encoding-overview) for the encoding approach.
- `cigar strings`: A list of CIGAR strings encoded according to the cigar encoding strategy (see [CIGAR-Specific Encoding](encoding_algorithms.md#cigar-specific-encoding-0x09)).
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

- `MM`: Integer encoding method (0x00-0x0B)
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
  - `0x0104` = Bytes `[01, 04]` (Varing metadata + LZMA blob)

**2-byte Strategy Codes (Walks/Paths):**

```
Format: 0xDD00IISS
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
- `RR`: Reserved (must be 0x00)
- `II`: Integer encoding method
- `SS`: String encoding method
- Used for: CIGAR strings
- Example:
  - `0x01000100` = Bytes `[01, 00, 01, 00]` (Identity decomposition, Varint integers, None for strings)

#### Strategy Code Reference Table

| Code Type    | Format       | Bytes              | First | Second | Third | Fourth |
| ------------ | ------------ | ------------------ | ----- | ------ | ----- | ------ |
| Integer-only | `0xMM`       | `[MM]`             | `MM`  | -      | -     | -      |
| Strings      | `0xHHLL`     | `[HH, LL]`         | `HH`  | `LL`   | -     | -      |
| CIGAR        | `0xDDRRIISS` | `[DD, RR, II, SS]` | `DD`  | `RR`   | `II`  | `SS`   |
| Walks/Paths  | `0xHHLL`     | `[HH, LL]`         | `HH`  | `LL`   | -     | -      |

### Encoding Method Reference

The following tables map strategy code byte values to encoding methods. Implementation details for each method are in [encoding_algorithms.md](encoding_algorithms.md).

#### Integer Encoding Methods (for `uints` fields and first byte of 2-byte codes)

| Code   | Strategy        |
| ------ | --------------- |
| `0x00` | none (identity) |
| `0x01` | varint          |
| `0x02` | fixed16         |
| `0x04` | elias gamma     |
| `0x05` | elias omega     |
| `0x06` | golomb          |
| `0x07` | rice            |
| `0x08` | streamvbyte     |
| `0x09` | vbyte           |
| `0x0A` | fixed32         |
| `0x0B` | fixed64         |

#### String Encoding Methods (for second byte of 2-byte codes)

| Code   | Strategy        |
| ------ | --------------- |
| `0x00` | none (identity) |
| `0x01` | zstd            |
| `0x02` | gzip            |
| `0x03` | lzma            |
| `0x04` | Huffman         |
| `0x05` | 2-bit           |
| `0x06` | Arithmetic      |
| `0x07` | bzip2           |
| `0x08` | RLE             |
| `0x0A` | Dictionary      |
| `0x0C` | LZ4             |
| `0x0D` | Brotli          |
| `0x0E` | PPM             |

#### CIGAR Decomposition Strategies

| Format       | Bytes              | Strategy                             |
| ------------ | ------------------ | ------------------------------------ |
| `0x00??????` | `[00, ??, ??, ??]` | none (identity)                      |
| `0x01??????` | `[01, RR, II, SS]` | numOperations + lengths + operations |
| `0x02??????` | `[02, 00, II, SS]` | string (treat as plain string)       |

See [CIGAR 4-byte Strategy Code Details](encoding_algorithms.md#cigar-4-byte-strategy-code-details) for wire formats.

### Reader Requirements

- Readers MUST interpret strategy codes as simple byte sequences
- Readers MUST validate that reserved bytes in strategy codes are `0x00`
- Readers MUST validate that strategy code byte patterns match the defined formats
- Readers MUST skip unknown section IDs without error
- Readers MUST treat unknown or invalid strategy codes as fatal errors

### Error Recovery Guidance

When encountering malformed data, readers should:

1. **Invalid strategy codes**: Treat as fatal errors (cannot recover)
2. **Corrupted payloads**: Skip the entire block if payload size can be determined from header
3. **Truncated files**: Report error with bytes read vs expected
4. **Unknown section IDs**: Skip the block using header size information
5. **Checksum failures**: Treat as fatal errors if checksums are implemented

### Performance Considerations

Different encoding strategies offer tradeoffs between compression ratio and speed:

- **Fastest decompression**: Identity (`0x00??`), 2-bit DNA (`0x??05`)
- **Best compression**: BWT+Huffman (`0x??07`), Dictionary (`0x??0A`)
- **Balanced approach**: Huffman (`0x??04`), Zstd (`0x??01`)
- **Specialized**: CIGAR-specific (`0x??09`), Delta (`0x03??`) for sorted data

### Implementation Recommendations

1. **Memory-mapped I/O**: Useful for random access to large BGFA files
2. **Streaming processing**: Process blocks sequentially for memory efficiency
3. **Parallel decompression**: Different blocks can be decompressed in parallel
4. **Caching**: Cache frequently accessed strategy code validations

### Strategy Code Validation Examples

```python
# Valid 2-byte strategy code
def is_valid_2byte_strategy(code_bytes):
    if len(code_bytes) != 2:
        return False
    first_byte, second_byte = code_bytes
    # Check that bytes are within valid ranges
    return (0x00 <= first_byte <= 0x0B) and (0x00 <= second_byte <= 0x0E)

# Valid 4-byte CIGAR strategy code
def is_valid_4byte_cigar_strategy(code_bytes):
    if len(code_bytes) != 4:
        return False
    dd, rr, ii, ss = code_bytes
    # Check decomposition strategy
    if dd not in [0x00, 0x01, 0x02]:
        return False
    # Check reserved byte
    if dd != 0x00 and rr != 0x00:  # For non-identity, RR must be 0x00
        return False
    # Check integer encoding strategies
    if ii not in [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0B]:
        return False
    # Check string encoding strategies
    if ss not in [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x0A, 0x0C, 0x0D, 0x0E]:
        return False
    return True
```

## Walks Type Format

The `walks` type encodes a list of walks, where each walk is a sequence of oriented segment IDs. This type is used in the Paths and Walks blocks.
Since we know that there are `record_num` walks in the block, we do not have to store that information again.
The `walks` layout is made by the following sequence of fields.

| Field                | Description                                                                             | Type          |
| -------------------- | --------------------------------------------------------------------------------------- | ------------- |
| `walks_lengths`      | The lengths of the walks                                                                | `uints`       |
| `walks_segments`     | The segment IDs of the walks, delta-encoded (see [Type Definitions](#type-definitions)) | `uints-delta` |
| `walks_orientations` | The orientations of the walks                                                           | `bits`        |
|                      |                                                                                         |               |

- All lengths of the walks are followed by all segment IDs of the walks, followed by all walks orientations.
- The `walks_lengths` field contains exactly `record_num` integers. The i-th integer L(i) is the length of the i-th walk of the block. The sum of all L(i) equals `uncompressed_walk_len` from the containing block header.
- The `walks_segments` field contains a sequence of `uncompressed_walk_len` integers. The first L(1) integers form the sequence of segment IDs of the first walk, then the subsequent L(2) integers form the sequence of the segment IDs of the second walk, etc.
- The `walks_orientations` field contains a sequence of `uncompressed_walk_len` bits. The first L(1) bits form the sequence of segment orientations of the first walk, then the subsequent L(2) bits form the sequence of the segment orientations of the second walk. Orientation `+` or `>` is encoded as `0`, while `-` or `<` is encoded as 1.

### Encoding strategies

- `walks_lengths` are encoded using the integer encoding strategy specified in the first byte of the `compression_walks`
  field in the containing block header.
- `walks_segments` are encoded using the `uints-delta` type, which applies signed integer encoding (see [Signed Integers](encoding_algorithms.md#signed-integers)). The integer encoding strategy is specified in the second byte of the `compression_walks` field in the containing block header and applies to the absolute values of the deltas. The values encoded are the difference between the current segment ID and the previous segment ID. For the first segment ID, we store the actual ID instead of the difference with the previous ID.
  For example, for the sequence of segment IDs [50, 48, 61] we compute deltas [50, -2, 13]. The sign bits are [0, 1, 0] and the absolute values [50, 2, 13] are encoded per the integer strategy.
- the `walks_orientations` field is always encoded as a bit sequence [Packed Bits](#packed-bits).

**Example:** Consider a walks block with 2 walks:

- Walk 1: "0+1-" (length 2, segments 0 and 1 with orientations + and -)
- Walk 2: "1+2+3-" (length 3, segments 1, 2 and 3 with orientation +, +, and -)

This would be encoded as:

- `walks_lengths`: [2, 3] (encoded per the integer strategy in bytes 3-4)
- `walks_segments`: [0, 1, 0, 1, 1] (delta of the segment IDs for both walks concatenated)
- `walks_orientations`: [0, 1, 0, 0, 1] (0=+, 1=- for each segment, packed as bits)

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
- **Walks type orientations** (`walks_orientations`): `n = uncompressed_walk_len` from the containing block header
- **Huffman encoded data**: `n` is determined by decoding exactly the required number of symbols (e.g., `2 * L` nibbles for a string of length `L`)

**Size calculation:** Number of uint64 words = `ceil(n / 64)`. Total bytes for bits field = `8 * ceil(n / 64)`.

**Example:** For orientations `[1, 0, 1, 1, 0, ...]` (64 bits):

- Word 0 = `0b...01101` (bit 0 = 1, bit 1 = 0, bit 2 = 1, bit 3 = 1, bit 4 = 0, ...)

## Conformance Requirements

**Minimum reader requirements:** A compliant BGFA reader MUST support all encodings:

**Writer requirements:** A compliant BGFA writer:

- MUST produce valid BGFA files that can be read by any compliant reader
- MUST set reserved fields to 0
- MUST NOT write empty blocks (blocks with `record_num = 0`). If a block type has no records, omit the block entirely.

**Error handling:**

- A reader encountering an unknown `section_id` MUST treat it as a fatal error.
- A reader encountering an unknown strategy code MUST treat it as a fatal error.
- A reader encountering truncated or corrupted data MUST treat it as a fatal error.

## Appendix A: Example BGFA Files

_To be provided._
