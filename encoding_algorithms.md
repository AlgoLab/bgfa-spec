# BGFA Encoding Algorithms

This document describes the encoding algorithms referenced by the [BGFA format](gfa_binary_format.md).
It covers integer encoding, string encoding, and specialized encodings used in block payloads.

**Normative keywords.** `MUST`, `MUST NOT`, `SHOULD` and `MAY` are to be interpreted as in RFC 2119.
Every statement about what a writer or a reader does is normative; prose that is only explanatory is
marked as such. "Fatal error" always means the same thing: the reader MUST reject the field or the whole
file and MUST NOT continue, as detailed in [Reader Requirements](gfa_binary_format.md#reader-requirements).

## Table of Contents

- [String Encoding Overview](#string-encoding-overview)
  - [Superstring](#superstring)
  - [Payload Layout for `strings`](#payload-layout-for-strings)
  - [Blob Framing](#blob-framing)
- [Integer Encoding Algorithms](#integer-encoding-algorithms)
  - [Signed Integers](#signed-integers)
  - [Integer Method: None (0x00)](#integer-method-none-0x00)
  - [Varint (0x01)](#varint-0x01)
  - [Fixed16 (0x02)](#fixed16-0x02)
  - [Elias Gamma (0x04)](#elias-gamma-0x04)
  - [Elias Omega (0x05)](#elias-omega-0x05)
  - [Golomb (0x06)](#golomb-0x06)
  - [Rice (0x07)](#rice-0x07)
  - [StreamVByte (0x08)](#streamvbyte-0x08)
  - [VByte (0x09)](#vbyte-0x09)
  - [Fixed32 (0x0A)](#fixed32-0x0a)
  - [Fixed64 (0x0B)](#fixed64-0x0b)
  - [Integer Validation Rules](#integer-validation-rules)
- [String Encoding Algorithms](#string-encoding-algorithms)
  - [None / Identity (0x00)](#none--identity-0x00)
  - [Zstd (0x01)](#zstd-0x01)
  - [Gzip (0x02)](#gzip-0x02)
  - [LZMA (0x03)](#lzma-0x03)
  - [Huffman Coding (0x04, 0xF4)](#huffman-coding-0x04-0xf4)
    - [Nibble-Level Processing](#nibble-level-processing)
  - [2-bit DNA Encoding (0x05)](#2-bit-dna-encoding-0x05)
  - [Reserved: Arithmetic Coding (`0x06`)](#reserved-arithmetic-coding-0x06)
  - [Bzip2 (0x07)](#bzip2-0x07)
  - [Run-Length Encoding (0x08)](#run-length-encoding-0x08)
  - [BWT + Huffman (0x09)](#bwt--huffman-0x09)
  - [Dictionary Encoding (0x0A)](#dictionary-encoding-0x0a)
- [CIGAR 4-byte Strategy Code Details](#cigar-4-byte-strategy-code-details)
  - [none (0x00000000)](#none-0x00000000)
  - [numOperations + lengths + operations (0x01??????)](#numoperations--lengths--operations-0x01)
  - [string (0x020000??)](#string-0x020000)
  - [Packed Operations String](#packed-operations-string)

## String Encoding Overview

### Superstring

A set of strings is embedded within a single "superstring" constructed by a heuristic that tries to
minimize the overall length (e.g., by overlapping common suffixes/prefixes). The metadata stores the start and end position of each string within the superstring. To recover string _i_, the decoder reads bytes from `start[i]` to `end[i]` (exclusive, following Python slice conventions).

**Note: Strings are never concatenated directly; all string sets are encoded via this superstring approach.**

The superstring is then encoded using the string encoding strategy.

When encoding a list of strings (the `strings` type), the encoding strategy is specified by a 2-byte code (see [Strategy Code Format Summary](gfa_binary_format.md#strategy-code-format-summary) in the main spec):

- First byte: integer encoding strategy for the position metadata
- Second byte: string encoding strategy for the superstring blob

The start and end positions are 0-based, the final position is excluded from the substring, following Python slice conventions.

Decoding a set of strings does not need to know the heuristic used to compute the superstring.

### Payload Layout for `strings`

The payload of the encoded `strings` consists of:

1. **Metadata**: the start positions and the end positions of the strings, encoded according to the
   first-byte strategy (varint, fixed16, etc). The number of strings `n` is the number implied by the
   containing block header, which is `record_num` for every `strings` field in BGFA.

   Start and end positions are encoded as two separate integer lists, each an independent unit in the sense
   of [Conventions](gfa_binary_format.md#conventions): first the `n` start positions, then the `n` end
   positions. Both lists use the same integer encoding strategy. Because the first start position is
   usually 0, a writer MUST NOT choose Elias gamma (`0x04`) or omega (`0x05`) when either list holds a 0.

2. **Blob**: The superstring is encoded according to the second-byte strategy.

Layout:

```
[start_0][start_1]...[start_n-1][end_0][end_1]...[end_n-1][blob length][blob]
```

All start positions are encoded first (as a contiguous list), followed by all end positions (as a contiguous list). Both lists use the same integer encoding strategy specified in the first byte of the compression code.

The `compressed_*_len` fields in block headers represent the total number of bytes for the encoded payload of that field, including both the integer metadata list and the compressed blob.

The `uncompressed_len` field is the sum of the lengths of the original strings (before any encoding). Note
that it is **not** the length of the superstring, which may be shorter because of overlaps.

### Blob Framing

Every `strings` field ends with a blob, which holds the compressed form of the superstring. A decoder cannot
use the block's `compressed_*_len` field to find the end of the blob, because the superstring positions are
decoded *before* the blob and some methods (Huffman, 2-bit DNA) cannot be decoded "until the bytes run out".
Two rules therefore make every blob self-delimiting.

**Rule 1 — the outer blob length is a byte count.** The first thing in a blob is a `varint` holding the
**number of bytes of method-specific data that follow it**.

> The blob length is **always** expressed as a number of **bytes**, for **every** method, without exception.

It is *not* a decoded length, *not* a symbol count, and *not* a nucleotide count. After reading it, a decoder
consumes exactly that many bytes of method-specific data, whatever the method.

```
[start_0] ... [start_n-1] [end_0] ... [end_n-1] [blob length: varint] [method data]
```

The `blob length` bytes themselves are not counted in the blob length.

**Rule 2 — method data is self-delimiting.** Method-specific data starts at its first byte and its
description takes a decoder exactly to its last byte, without needing the blob length as a stopping
condition. Methods whose decoded size cannot be recovered from their own framing (Huffman, 2-bit DNA)
therefore carry an explicit **decoded item count** inside their method data, defined in their own section.
That count is an internal property of those two methods; it is not the outer blob length, and the two MUST
NOT be confused.

**Validation.** A reader MUST reject a field as a fatal error if the `blob length` is larger than the number
of bytes remaining in the owning `compressed_*_len` field, or if decoding the method data does not consume
exactly `blob length` bytes. For a `strings` field, the blob is the last part of the field, so the blob
MUST also end exactly at the end of the owning `compressed_*_len` field (rule 7 of the size rules in
[Payload Byte Layouts](gfa_binary_format.md#payload-byte-layouts)).

**Note on redundancy.** For the container methods (`none`, zstd, gzip, lzma, bzip2) the blob length is
redundant, because the decoder could equally stop when the superstring is complete. It is nonetheless
mandatory, so that there is exactly one framing rule for every method and one place where a decoder bounds
its reads. This costs 1 byte per `strings` field.

**Exception — Dictionary.** The Dictionary method (`0x0A`) *replaces* this layout entirely: a `strings`
field with `LL = 0x0A` has no start/end positions and no outer blob length. See
[Dictionary Encoding](#dictionary-encoding-0x0a).

## Integer Encoding Algorithms

### Signed Integers

A list of signed integers is encoded by two parts:

- the signs of all integers
- the absolute values of all integers (unsigned ints). The encoding strategy applies to this part only.

The signs are considered a sequence of bits, where + is encoded as 0 and - is encoded with 1.
The i-th bit in the sign `bits` field corresponds to the sign of the i-th integer in the list.
Zero values are treated as positive (sign bit 0).

The sign bits form a `bits` field of exactly as many bits as there are integers in the field, packed per
[Packed Bits](gfa_binary_format.md#packed-bits). Its size is therefore `8 * ceil(n / 64)` bytes, where `n`
is the number of integers implied by the containing block header, and it is placed in the trailing
`bits`-fields group of its owning `compressed_*_len` field (rule 3 of the size rules in
[Payload Byte Layouts](gfa_binary_format.md#payload-byte-layouts)). The absolute values follow as one
integer list encoded with the field's integer strategy.

**Layout of a `uints-delta` field.** Conceptually, a `uints-delta` field is, per field:

```
[method preamble, if any][absolute value 0] ... [absolute value n-1][sign bits]
```

In byte order this is not contiguous: the absolute values sit inline at the field's position, while the
sign `bits` field is deferred to the trailing `bits`-fields group of the owning `compressed_*_len` field,
per rule 3. When a region holds several `uints-delta` fields (the Walks `start_positions` and
`end_positions`), the byte order is: each field's preamble and absolute values in block field order, then
the whole trailing `bits`-fields group in block field order. The "method preamble" is present only for
[Rice (`0x07`)](#rice-0x07), whose one-byte `k` parameter therefore precedes the first absolute value.
There is no preamble for any other method.

Note that there is **one delta stream per field** and it is never restarted part-way: see the `uints-delta`
definition in [Type Definitions](gfa_binary_format.md#type-definitions).

**Validation.** A reader MUST reject the field as a fatal error if the sign `bits` field does not decode to
exactly one sign bit per integer, or if the owning region's inline absolute values — the absolute values of
**all** the owning region's `uints-delta` fields, decoded together in block field order — do not terminate exactly
at the start of the owning region's trailing `bits`-fields group, that is, at `compressed_*_len` minus the total
byte size of **all** `bits` fields in that group, each `8 * ceil(n_i / 64)` bytes for its own `n_i` (rule 3
of the size rules in [Payload Byte Layouts](gfa_binary_format.md#payload-byte-layouts)). A decoder locates
the group from the end of the region and requires the combined inline integer stream to end at the group's
first byte; the group may hold more `bits` fields after this field's sign bits (for example,
`end_positions` signs or `walks_orientations`). In a region with several `uints-delta` fields, each field's
absolute values end where the next field's absolute values begin, and only the last field's absolute values
are adjacent to the group. Any bytes between the last absolute value and the group are a fatal error, so a
non-canonical encoding that pads the absolute list is rejected. Negative absolute values are impossible by
construction, but a decoder MUST still reject an absolute value of `2^64` or more (see the integer range in
[Conventions](gfa_binary_format.md#conventions)), rather than silently wrapping it.

**Reconstruction.** The decoded values are the running sum of the signed deltas. The first value is the
first delta itself; every later value is the previous value plus its delta. A reader MUST reject the
field as a fatal error if the running sum leaves the range `0 .. 2^64 - 1`, and MUST NOT wrap. This range
applies to every `uints-delta` field: `walks_segments`, `start_positions` and `end_positions` all hold
unsigned values.

The encodings of unsigned ints are the following.

### Integer Method: None (0x00)

**Code `0x00` is reserved in an integer position and MUST NOT be used there.** It is a valid *string*
method (see [None / Identity (0x00)](#none--identity-0x00)) and it is the byte a strategy code carries in
the string position of a `strings` field, but an integer list of a known count has no element width, so
`0x00` has no meaning for it.

A writer MUST NOT emit `0x00` in an integer position of a strategy code, and a reader MUST reject it as
an unknown strategy code. The integer codes are therefore exactly:

```
0x01 0x02 0x04 0x05 0x06 0x07 0x08 0x09 0x0A 0x0B
```

This is the set that `INTEGER_CODES` enumerates in
[Strategy Code Validation Examples](gfa_binary_format.md#strategy-code-validation-examples).

### Varint (0x01)

Variable-length integer encoding optimized for small values.

**Format:**

- Each byte: 7 data bits + 1 continuation bit (1 = more bytes follow, 0 = last byte)
- Little-endian ordering (least significant group first)
- **Canonical form.** A writer MUST use the shortest encoding: the last byte of a multi-byte varint is never
  `0x00`. A reader MUST reject as a fatal error a varint longer than 10 bytes, a varint whose value is
  `2^64` or more, and a multi-byte varint whose last byte is `0x00`.

These rules apply to every varint in BGFA, including the blob lengths, counts and positions that are
always stored as varint regardless of the field's strategy.

### Fixed16 (0x02)

Each integer is encoded as a fixed 16-bit little-endian value.

### Elias Gamma (0x04)

Elias gamma encodes a number `n >= 1` as a unary bit width followed by the low bits of `n`.

**Format:**

- Let `L = floor(log2(n)) + 1`, the number of bits in the binary form of `n`.
- Write `L` in unary: `L` one bits followed by a single zero bit. This is the terminator the decoder
  needs, so gamma is self-delimiting.
- Write `n - 2^(L-1)` in binary, in exactly `L - 1` bits, MSB-first (see
  [Conventions](gfa_binary_format.md#conventions)). For `L = 1` this part is empty.

**Example:** n = 5

- `L = 3`
- Unary: `111` + `0` = `1110`
- `n - 2^2 = 5 - 4 = 1`, written in `L - 1 = 2` bits: `01`
- Complete: `111001`

**This is not textbook Elias gamma.** Textbook gamma writes `L - 1` zeros followed by the `L` bits of `n`, so
`n = 1` is the single bit `1`. BGFA writes `L` in unary with ones and a terminating zero, then the `L - 1`
low bits, so `n = 1` is `10` and every codeword is one bit longer than textbook gamma. An implementation MUST
follow the definition above; a generic gamma library will not produce compatible output.

**Zero cannot be represented.** Gamma has no codeword for `n = 0`, because `L` would be 0 and the unary
part `0` would not be a legal code. A writer MUST NOT select `0x04` for an integer list that contains a 0 —
in particular segment IDs and their deltas, which can be 0. A reader MUST reject a field as a
fatal error if the unary prefix decodes to `L = 0` or to `L > 64`, or if any other part of the value cannot
be decoded.

### Elias Omega (0x05)

Elias omega encodes a positive integer by recursing on its bit width. The recursion terminates in a
single `0` bit, so an omega codeword is self-delimiting and is written MSB-first (see
[Conventions](gfa_binary_format.md#conventions)).

**Encoding.** Start with `code = "0"`. While `n > 1`, prepend the full binary representation of `n` to
`code`, then replace `n` with `bit_width(n) - 1`, i.e. `floor(log2(n))`. When `n` reaches 1 the loop
stops and `code` is complete.

Equivalently, written outermost first: `n` in binary, then `floor(log2(n))` in binary, then
`floor(log2(floor(log2(n))))` in binary, and so on down to `1`, followed by one terminating `0` bit.
**The leading `1` of each binary form is written**; nothing is stripped.

**Decoding.** Set `current = 1`, then repeat:

1. Read one bit. If it is `0`, stop: the decoded value is `current`.
2. Otherwise set `next = 1`, read exactly `current` more bits and append each to `next` MSB-first
   (`next = next << 1 | bit`), then set `current = next` and go back to step 1.

**Example:** n = 5

- `binary(5) = 101`; the new `n` is `bit_width(5) - 1 = 3 - 1 = 2`
- `binary(2) = 10`; the new `n` is `bit_width(2) - 1 = 2 - 1 = 1`, which stops the loop
- the loop produced `10` then `101`; the terminating `0` is appended
- complete: `101010` (6 bits)

**Example:** n = 1 emits the single bit `0`. A decoder must therefore be able to recognise a lone `0` as a
complete value.

**Zero cannot be represented.** As with gamma, `n = 0` has no codeword. A writer MUST NOT select `0x05`
for an integer list that contains a 0, and a reader can never legitimately decode a `0` with this method.
A reader MUST reject as a fatal error a codeword whose recursion would produce a value of `2^64` or more,
i.e. a step 2 entered with `current >= 64`, which would build a value of more than 64 bits.

### Golomb (0x06)

Golomb encoding uses a parameter `b`, which is **fixed at 128** for the whole format: every list encoded
with `0x06` uses `b = 128`, and `b` is **not transmitted**.

**Format:**

- For value n:
  - quotient q = n // b, remainder r = n % b
  - Write q in unary (q ones, then zero)
  - Write r in binary using `ceil(log2(b))` = 7 bits

The unary prefix and the 7-bit remainder are written MSB-first (see
[Conventions](gfa_binary_format.md#conventions)).

Because `b = 128 = 2^7`, Golomb as defined here is bit-identical to [Rice](#rice-0x07) with `k = 7`.
The two codes differ only in that Rice stores `k` and Golomb does not.

### Rice (0x07)

Rice coding is Golomb with `b` as a power of 2: `b = 2^k`.

**Format:**

- The parameter `k` is **per integer list** (see [Conventions](gfa_binary_format.md#conventions)) and MUST
  be stored explicitly as a single raw byte (not a varint), before the first encoded value of that list. It
  is not part of the strategy code. `k` MUST satisfy `1 <= k <= 31`; an
  out-of-range `k` MUST be treated as a fatal error.
- In a `uints-delta` field this byte precedes the first absolute value: see the layout in
  [Signed Integers](#signed-integers).
- For value n:
  - quotient q = n >> k
  - remainder r = n & (2^k - 1)
  - Write q in unary (q ones, then zero)
  - Write r in binary using k bits

The unary prefix and the k-bit remainder are written MSB-first.

**Example:** For k=3 and sequence [5, 12, 7]:

- Parameter byte: `0x03`
- 5: `q = 0`, `r = 5` → `0` `101`
- 12: `q = 1`, `r = 4` → `10` `100`
- 7: `q = 0`, `r = 7` → `0` `111`
- Bit stream: `0101 10100 0111` (13 bits), padded with three zero bits: `01011010 00111000`
- Complete list: `03 5A 38` (3 bytes)

### StreamVByte (0x08)

StreamVByte encodes integers in groups of four, with one control byte per group. A reader decodes exactly
the number of integers the containing block header implies and MUST stop there.

**This is not the layout of the reference StreamVByte library.** That library stores all control bytes
first and all data bytes after them, and supports a 3-byte width. BGFA interleaves each control byte with
its group's data and uses the widths 1, 2 and 4 only, as defined below.

**Format:**

- The integers are encoded in groups of 4; only the final group may hold fewer. Every group is preceded by
  exactly one control byte, immediately followed by the data bytes of that group's integers, in order.
- Control byte bits `2*i` and `2*i + 1` select the width of the `i`-th integer of the group:

  | bit `2*i` | bit `2*i + 1` | width of integer `i` |
  | -------- | ------------- | ------------------- |
  | 0        | 0             | 1 byte              |
  | 1        | 0             | 2 bytes             |
  | 0        | 1             | 4 bytes             |
  | 1        | 1             | invalid             |

  A writer MUST NOT emit the combination `1 1`, and a reader MUST treat it as a fatal error.
- Each integer is stored little-endian in its width.
- A writer MUST use the smallest width that can represent the value: below 256 always 1 byte, below
  65536 always 2 bytes, otherwise 4 bytes. A reader MUST reject as a fatal error a value stored in a width
  larger than the smallest one that can represent it.
- **Values of `2^32` or more cannot be represented.** A writer MUST NOT select `0x08` for an integer list that
  contains such a value.
- If the final group holds `m < 4` integers, the control bits `2*m` .. `7` describe integers that are not
  present. A writer MUST set them to 0; a reader MUST ignore them.

**Example:** with `compression = 0x08`, the integers [1, 300, 2, 3] form one complete group:

- Control byte: integer 0 (value 1) needs 1 byte, so bits 0-1 are `00`; integer 1 (value 300) needs 2
  bytes, so bit 2 is 1 and bit 3 is 0; integers 2 and 3 need 1 byte each, so bits 4-7 are `0000`. The
  control byte is `0b00000100` = `0x04`.
- Data: `01` (1), `2C 01` (300, little-endian), `02` (2), `03` (3) = 6 bytes.
- Total: 1 control byte + 6 data bytes = 7 bytes.

### VByte (0x09)

Variable Byte encoding uses 7 bits per byte for data, with the high bit as the continuation flag.

**Format:**

- Each byte: 7 data bits + 1 continuation bit (1 = more bytes follow, 0 = last byte)
- Little-endian ordering (least significant group first), identical to [Varint](#varint-0x01). `VByte` and
  `varint` are the same encoding on the wire; they exist as separate codes so that a field can declare
  which one it uses.

### Fixed32 (0x0A)

Each integer is encoded as a fixed 32-bit little-endian value.

### Fixed64 (0x0B)

Each integer is encoded as a fixed 64-bit little-endian value.

### Integer Validation Rules

These rules apply to every `uints` and `uints-delta` field, in addition to the per-method requirements of each
integer method. They exist because the counts and lengths that bound a field come from the block header and
are therefore attacker-controlled.

- A reader MUST decode exactly the number of integers implied by the containing block header, and MUST stop at
  that count rather than at the end of the owning `compressed_*_len` field.
- A reader MUST reject the field as a fatal error if decoding that many integers would read past the end of the
  owning `compressed_*_len` field, or past the end of the file.
- For `fixed16`, `fixed32` and `fixed64`, a writer MUST NOT select a width that cannot hold every value of the
  list; it MUST NOT silently truncate a value to the low bits.
- A reader MUST NOT allocate a buffer whose size is derived from an unvalidated header or payload field. Every
  derived size MUST be validated first, as described in
  [Limits and Validation](gfa_binary_format.md#limits-and-validation).
- Arithmetic on sizes derived from the header (products, sums, `ceil(n / 4)`, `8 * ceil(n / 64)`,
  `16 * ceil(n / 64)`, dictionary `N + 1`) MUST be performed with overflow checking, and a reader MUST
  reject the field rather than wrap around.
- For a `walks`-type field, the decoded `walks_lengths` list MUST contain exactly `record_num` integers,
  each L(i) MUST be at least 1, and the sum of all L(i) MUST equal `uncompressed_walk_len` in a Walks block
  and `uncompressed_paths_len` in a Paths block. A reader MUST reject the block as a fatal error on any
  violation: these counts come from the header and are attacker-controlled, and a mismatch would silently
  mis-assign segment occurrences to walks. The `at least 1` bound is a source-format constraint, not an
  encoding artifact: the GFA 1.2 W-line grammar defines a walk as one or more oriented segments
  (`(<orientation> <segId>)+`), so an empty walk cannot be represented, and `uncompressed_walk_len` is
  therefore always at least `record_num`.

## String Encoding Algorithms

The following algorithms encode a byte buffer: the superstring of a `strings` field, or the buffer of a
CIGAR decomposition (see [CIGAR 4-byte Strategy Code Details](#cigar-4-byte-strategy-code-details)). In this
section "the superstring" means whichever buffer is being encoded. Every method applies to an arbitrary
byte buffer; the methods that are tuned for DNA (2-bit, RLE, BWT+Huffman) remain lossless on any input.

### None / Identity (0x00)

The method data is the superstring itself, stored as raw bytes with no transformation. Its length is exactly
the blob length of [Blob Framing](#blob-framing). The string metadata (start/end positions from the integer
encoding) defines how to slice individual strings from the superstring.

### Zstd (0x01)

The method data is exactly one [Zstandard](https://facebook.github.io/zstd/) frame (RFC 8878) holding the
superstring, whose byte length is exactly the blob length of [Blob Framing](#blob-framing). The frame MUST
NOT require an external dictionary (its `Dictionary_ID` is absent or 0). Skippable frames are not allowed.

### Gzip (0x02)

The method data is exactly one gzip member (RFC 1952, compression method 8, deflate) holding the
superstring, whose byte length is exactly the blob length of [Blob Framing](#blob-framing). A raw deflate
stream or a zlib (RFC 1950) stream is not valid here.

### LZMA (0x03)

The method data is exactly one [`.xz`](https://tukaani.org/xz/xz-file-format.txt) stream (LZMA2 filter)
holding the superstring, whose byte length is exactly the blob length of [Blob Framing](#blob-framing). This
is the default output of the `xz` tool and of Python's `lzma.compress`. The legacy `.lzma` (LZMA_Alone)
format and raw LZMA streams are not valid here.

**Decompressed size.** For every container method (`0x01`, `0x02`, `0x03`, `0x07`) the decompressed size is
not known before decompression. A reader MUST bound it by the decoded-size cap of
[Limits and Validation](gfa_binary_format.md#limits-and-validation) and stop as soon as the cap is exceeded.

### Huffman Coding (0x04, 0xF4)

The two Huffman codes share one wire format and differ only in alphabet size:

| Code  | Alphabet        | Codebook size              | Payload unit  |
| ----- | --------------- | -------------------------- | ------------- |
| `0x04`| 16 nibbles 0x0-0xF | 32 bytes (16 × `uint16`)   | one nibble    |
| `0xF4`| 256 bytes 0x00-0xFF | 512 bytes (256 × `uint16`) | one byte      |

The Huffman encoding of a string consists of:

| Name               | Description                                            | Type     |
| ------------------ | ------------------------------------------------------ | -------- |
| `codebook_len`     | Length of the encoded codebook in bytes                | `uint16` |
| `codebook`         | Bit-lengths, one little-endian `uint16` per alphabet symbol | `bytes`  |
| `symbol_count`     | Number of symbols to decode (see below)                | `varint` |
| `huffman_bitstream`| The encoded symbols, MSB-first, padded with zeros to a byte boundary | `bytes` |

**Framing.** The blob is:

```
[blob length: varint][codebook_len: uint16][codebook][symbol_count: varint][huffman_bitstream]
```

The **codebook MUST be stored at the beginning of the blob**, before any encoded data, so that a decoder has
the full code table before it reads a single symbol. The encoder MUST choose the codebook from the data being
encoded and MUST store it; a reader MUST NOT assume a fixed codebook.

**`symbol_count`** is the **decoded** item count, and is the reason this method needs an internal count: the
outer blob length of [Blob Framing](#blob-framing) is a byte count, so it cannot tell a decoder how many
symbols to produce.

`symbol_count` is twice the length `L` of the **byte buffer being encoded** for `0x04` (one nibble per
half-byte, so `2 * L` nibbles) and exactly `L` for `0xF4` (one symbol per byte). "The byte buffer" is
whatever this method was asked to encode:

- for a `strings` field, it is the superstring, so `L` is the superstring length in bytes;
- for a CIGAR `numOperations` decomposition, it is the packed operations buffer described in
  [Packed Operations String](#packed-operations-string), so `L` is that buffer's length in bytes;
- for a CIGAR `string` decomposition, it is the newline-terminated CIGAR buffer.

In every case `0x04` splits each byte of the buffer into a high and a low nibble in that order, per
[Nibble-Level Processing](#nibble-level-processing); the CIGAR buffer is nibble-*packed* data, but it is
still a byte buffer for the purposes of this method. For `0x04` a reader MUST treat an odd `symbol_count` as
a fatal error.

**Deriving the bitstream length.** After decoding the `symbol_count` varint, the bitstream occupies the rest
of the method data, i.e. `blob length - 2 - codebook_len - (bytes of the symbol_count varint)` bytes, where
`blob length` is the method-data byte count read by [Blob Framing](#blob-framing). A reader
MUST reject the field as a fatal error if `blob length` is smaller than that sum, if the bitstream ends before
`symbol_count` symbols have been decoded, or if the bitstream is longer than `ceil(B / 8)` bytes, where `B`
is the number of bits consumed by the `symbol_count` symbols.

**Codebook format:**
The codebook is exactly 32 bytes for `0x04` (16 little-endian uint16 values, one bit-length per nibble
0x0 through 0xF) and exactly 512 bytes for `0xF4` (256 little-endian uint16 values, one bit-length per byte
0x00 through 0xFF). `codebook_len` MUST equal 32 for `0x04` and 512 for `0xF4`; any other value is a fatal
error. A bit-length of 0 means the symbol is absent from the alphabet and MUST NOT appear in the encoded data;
such an entry is stored as 0.

```python
codebook = struct.unpack('<16H', codebook_bytes)   # 0x04
# codebook[0] = bit-length for nibble 0x0
# codebook[1] = bit-length for nibble 0x1
# ...
# codebook[15] = bit-length for nibble 0xF
```

**Validation.** A codebook is valid if and only if both of the following hold:

1. Every non-zero bit-length is in `1..16`.
2. Kraft's equality holds, which MUST be checked with exact integer arithmetic, not floating point:
   `sum(2^(16 - len) for len in codebook if len > 0) == 65536`. The equivalent floating-point form
   `sum(2**-len ...) == 1` is not exact and MUST NOT be used to decide.

A reader MUST reject a codebook that fails either check as a fatal error.

**The 16-bit code-length limit is a real constraint, not a formality.** A `uint16` entry can hold any
length up to 65535, but this specification caps codes at 16 bits, so a codebook that needs longer codes is
not representable. This is not a theoretical concern for `0xF4`, whose 256-symbol alphabet can easily
produce codes longer than 16 bits on skewed data. A writer MUST compute its codebook first and, if any code
would exceed 16 bits, MUST NOT use `0x04` or `0xF4` for that buffer — it MUST pick another method.

**At least two distinct symbols are needed.** A codebook with a single non-zero length, or with none, can
never satisfy Kraft's equality. A writer MUST therefore NOT use `0x04` or `0xF4` for a buffer that holds
fewer than two distinct symbols (for `0x04`, distinct nibbles), which includes the empty buffer; it MUST
pick another method.

**Reconstruction:**
The decoder MUST reconstruct the Huffman codes from the bit-lengths using canonical Huffman code assignment:

1. Collect all (symbol, bit-length) pairs where bit-length > 0
2. Sort primarily by bit-length (ascending) and secondarily by symbol value (ascending)
3. Assign codes sequentially using the following algorithm:

   ```python
   code = 0
   prev_len = 0
   huffman_codes = {}

   for symbol, bit_len in sorted_pairs:
       code = (code + 1) << (bit_len - prev_len) if prev_len > 0 else 0
       huffman_codes[symbol] = (code, bit_len)
       prev_len = bit_len
   ```

4. Zero bit-length symbols are not in the alphabet and will not appear in the encoded data

**Example:** Given bit-lengths: `{0x41: 1, 0x42: 2, 0x43: 2}` (symbols 'A', 'B', 'C'; a `0xF4`
codebook, since the symbols exceed the `0x04` nibble range):

- Sorted by (bit-length, symbol): `[(0x41, 1), (0x42, 2), (0x43, 2)]`
- Code assignment:
  - 'A' (0x41): bit-length=1, code=0b0 (first, shortest)
  - 'B' (0x42): bit-length=2, code=(0b0+1)<<1 = 0b10
  - 'C' (0x43): bit-length=2, code=(0b10+1)<<0 = 0b11
- Kraft's equality holds: `2^15 + 2^14 + 2^14 = 65536`, so a conforming reader accepts this codebook.

**Encoding process:**

1. Turn the input into symbols: for `0x04` each byte becomes two nibbles (high nibble, low nibble); for
   `0xF4` each byte is one symbol
2. Look up each symbol's code in the reconstructed codebook
3. Concatenate all codes, MSB-first, into a bitstream
4. Pad to byte boundary with zeros

**Decoding:** the decoder reads `symbol_count` and then decodes exactly that many symbols — `2 * L` nibbles
for `0x04`, `L` bytes for `0xF4`. Trailing zero bits in the last byte of the bitstream are padding and MUST
be ignored. Because `symbol_count` is stored explicitly, a decoder never has to infer the decoded length from
the string metadata, and the decoded superstring length is independent of how many overlaps the superstring
heuristic found.

**Bit order:** the Huffman bit stream is packed MSB-first (see
[Conventions](gfa_binary_format.md#conventions)), independently of the LSB-first `bits` type.

#### Nibble-Level Processing

1. **Symbol Extraction**: Each byte of the target string (the superstring) is treated as two 4-bit symbols:
   - Symbol A: High nibble (bits 4-7)
   - Symbol B: Low nibble (bits 0-3)

2. **Encoding Order**: For every byte, Symbol A is encoded first, followed immediately by Symbol B.

3. **Alphabet Size**: The codebook always contains 16 entries (representing nibbles 0x0 through 0xF). A bit-length of 0 indicates the nibble is not present.

### 2-bit DNA Encoding (0x05)

2-bit DNA encoding provides optimal compression for DNA/RNA sequences by encoding each nucleotide in 2 bits instead of 8 bits (75% size reduction). This is the most impactful encoding for pangenome data where sequences typically comprise 70-80% of file content.

**Nucleotide Mapping:**

- A = 00
- C = 01
- G = 10
- T = 11

Only the four uppercase bytes `A`, `C`, `G` and `T` are stored in `packed_bases`. Every other byte —
lowercase letters, `U`, ambiguity codes, or anything else — MUST be stored in the exception table, so the
method is lossless on any byte buffer.

**Bit packing:** Nucleotides are packed MSB-first. The first nucleotide is stored in bits 7-6 of the first byte, the second in bits 5-4, the third in bits 3-2, the fourth in bits 1-0. Subsequent nucleotides continue in subsequent bytes.

**Example:** Sequence "ACGT" (4 nucleotides):

- A=00, C=01, G=10, T=11
- Packed: `0b00011011` = 0x1B (1 byte)

**Example:** Sequence "ACGTA" (5 nucleotides):

- A=00, C=01, G=10, T=11, A=00
- Packed: `0b00011011` `0b00000000` = 0x1B 0x00 (2 bytes, last 6 bits are padding)

**Note:** Unused bits in the final byte MUST be set to 0 when writing and MUST be ignored when reading.

**Format** — the method data is:

- `varint`: `nucleotide_count`, the number of nucleotides in the decoded sequence, which is the length of the
  superstring being encoded, **not** the sum of the lengths of the individual segment sequences. This is an
  internal **decoded item count**, not the outer blob length: the blob length of
  [Blob Framing](#blob-framing) is a byte count and MUST NOT be used here.
- 1 byte: flags
  - bit 0: `has_exceptions` (1 if exception table present, 0 otherwise)
  - bits 1-7: reserved (MUST be 0 when writing; a reader MUST reject a non-zero value as a fatal error)
- `packed_bases`: exactly `nucleotide_count` nucleotides, 4 per byte (2 bits each), occupying exactly
  `ceil(nucleotide_count / 4)` bytes, with the unused bits of the final byte set to 0. **Every position of
  the decoded sequence gets a nucleotide from `packed_bases`, including the exception positions:** a writer
  MUST write a placeholder (any of the four codes, conventionally `A`) in the packed slot of every position
  that also appears in the exception table, and MUST then overwrite it via the table. A writer MUST NOT skip
  the packed slot of an exception position, because the decoder maps `packed_bases` positionally onto the
  decoded sequence and would shift every later nucleotide.
- If the `has_exceptions` flag is set:
  - `varint`: exception count `E`
  - `varint` list: exactly `E` positions, as 0-based indices into the **decoded nucleotide sequence**, in
    strictly increasing order
  - `bytes`: exactly `E` exception characters (one byte per exception, in ASCII)

**Validation.** A reader MUST reject the field as a fatal error unless all of the following hold:
`ceil(nucleotide_count / 4)` bytes of `packed_bases` are present in the remaining method data; every exception
position is strictly less than `nucleotide_count`; the positions are strictly increasing; and `E` positions
followed by `E` characters are present in the remaining bytes. These checks MUST be performed **before**
allocating the decoded sequence, because `nucleotide_count` is attacker-controlled.

**`nucleotide_count` and the decoded length are the same number.** `nucleotide_count` is both the number of
nucleotides in the decoded sequence and the number packed into `packed_bases`; exceptions overwrite
positions of that same sequence rather than adding to it. So the decoder always ends up with exactly
`nucleotide_count` characters, whether there are exceptions or not.

**Exception Handling:**
Every byte of the superstring other than `A`, `C`, `G` and `T` is stored in the exception table with its
original value, which makes reconstruction exact. A writer MUST NOT store `A`, `C`, `G` or `T` as an
exception character, and a reader MUST treat one as a fatal error, so that the encoding of a given buffer
is unique.

An exception position unambiguously identifies a **character** of the decoded sequence, not a byte or a
nibble of the packed stream, so no additional high/low-nibble selector is needed: the decoder expands
`packed_bases` into the nucleotide sequence and then overwrites position `p` of that sequence with the
corresponding exception character.

**Case is preserved.** Lowercase `acgt` and RNA `U`/`u` are exceptions like any other byte, so `acgt` decodes
to `acgt`. This keeps soft-masked sequences intact, at the cost of compression on them; a writer that
expects many such bytes SHOULD pick another method.

**Empty sequences:** a nucleotide sequence of length 0 is encoded as `nucleotide_count = 0`, a flags byte
of `0x00`, no `packed_bases` bytes, and no exception table, i.e. 2 bytes of method data.

**Expected Compression (informative):** 75% reduction on pure DNA/RNA sequences, slightly less with ambiguity codes.

**Primary Use Case:** Segment sequences, which are typically the largest data component in BGFA files.

### Reserved: Arithmetic Coding (`0x06`)

Code `0x06` is **reserved and MUST NOT be used** in BGFA version 0. An earlier draft assigned it to a
byte-oriented arithmetic coder, but the required byte-exact details (register initialisation, the
renormalisation trigger, carry propagation into the pending count, and the final flush) were never pinned
down, and arithmetic coders are bit-incompatible at that level. Two conforming implementations would have
produced different files.

A reader MUST treat `0x06` as an unknown strategy code and report a fatal error. It may be assigned in a
future version, at which point this section must be replaced by a full specification.

### Bzip2 (0x07)

The method data is exactly one bzip2 stream holding the superstring, whose byte length is exactly the blob
length of [Blob Framing](#blob-framing).

### Run-Length Encoding (0x08)

Run-Length Encoding efficiently compresses sequences with repeated characters (homopolymers in DNA, repeated operations in other contexts). The method data is a sequence of chunks, each stored either raw or run-length encoded.

**Format** — the method data is:

- `varint`: chunk count `R`
- For each of the `R` chunks:
  - 1 byte: mode (`0x00` = raw, `0x01` = RLE); any other value is a fatal error
  - `varint`: chunk data length, in bytes
  - chunk data, of exactly that many bytes:
    - raw mode: the bytes themselves, copied to the output
    - RLE mode: a sequence of `[char: 1 byte][repeat: varint]` pairs; each pair outputs `char` repeated
      `repeat` times

The decoded superstring is the concatenation of the outputs of all chunks, in order.

**Framing.** RLE is self-delimiting through the leading chunk count. The outer blob length of
[Blob Framing](#blob-framing) is a byte count covering the whole of the method data described above, and is
what a decoder uses to bound its reads; the chunk count is what tells it when to stop.

**Validation.** A reader MUST reject the field as a fatal error if a chunk data length exceeds the
remaining method data, and MUST bound `R` and every chunk data length by the method data length
**before** allocating. `R = 0` is valid and encodes the empty superstring, and a chunk data length of 0 is
valid and outputs nothing. In RLE mode a chunk's pairs MUST consume the chunk data exactly: a reader
MUST reject a field as a fatal error if the pairs do not end precisely on the chunk data boundary. A
`repeat` of 0 is invalid and MUST be rejected, since it would encode no characters. The `char` of an RLE
pair is one raw byte and is not subject to any alphabet restriction. The decoded size is bounded by the
decoded-size cap of [Limits and Validation](gfa_binary_format.md#limits-and-validation), which a reader
MUST check before expanding a pair.

**Writer guidance (informative).** Any chunking that decodes to the superstring is valid, and a reader
MUST accept it. The reference writer puts runs of 3 or more identical consecutive bytes in RLE chunks and
everything else in raw chunks, which avoids expansion on non-repetitive data.

**Expected Compression (informative):** 30-50% reduction on sequences with homopolymers or repetitive
patterns.

**Primary Use Cases:**

- DNA sequences with homopolymer runs (AAAAAAA, GGGGGG, TTTTTT)
- General string data with repeated characters

### BWT + Huffman (0x09)

Burrows-Wheeler Transform + Huffman coding is intended for repetitive sequences like DNA, but it is lossless
on any byte buffer. The superstring is cut into consecutive blocks of 65536 bytes (64KB); only the last
block may be shorter. Each block is encoded independently by this pipeline:

1. **BWT.** Consider the `n` cyclic rotations of the block, where rotation `j` starts at byte `j`. Sort
   them lexicographically, comparing bytes as unsigned values. The BWT output is the last column of the
   sorted rotation matrix: `n` bytes, the `r`-th being the last byte of the `r`-th sorted rotation. The
   **primary index** is the row of the sorted matrix that holds rotation 0 (the block itself). When the
   block is periodic, several rows hold rotation-equal strings; any of those rows is a valid primary index,
   since they all invert to the same block.
2. **MTF.** Apply the Move-to-Front transform to the BWT output. The MTF list is initialised to the 256 byte
   values in increasing order (`0x00, 0x01, ..., 0xFF`) **at the start of every block**. For each input byte
   `c`, output the current index of `c` in the list, then move `c` to the front of the list.
3. **Huffman.** Encode the MTF output, a buffer of exactly `n` bytes, with nibble-level Huffman: the result
   is exactly the method data of [Huffman Coding](#huffman-coding-0x04-0xf4) with code `0x04`, i.e.
   `[codebook_len][codebook][symbol_count][huffman_bitstream]`, with `symbol_count = 2 * n`.

**Format** — the method data is:

- `uint32`: number of BWT blocks, little-endian
- For each block, in order:
  - `uint32`: primary index, little-endian
  - `uint32`: block size `n` in bytes (1..65536), little-endian
  - the `0x04` Huffman method data of the MTF output, as in step 3. Its bitstream ends at the first byte
    boundary after the `symbol_count`-th symbol, and the next block starts at that byte.

**Framing.** The outer `blob length` varint of [Blob Framing](#blob-framing) applies here as it does to
every method: it is a byte count of the whole method data, and the decoder bounds its reads with it. Each
block is self-delimiting through its own `symbol_count`.

**Decoding.** For each block, decode the Huffman data into `n` MTF bytes, invert MTF starting from the
initial list above, then invert the BWT using the primary index. Blocks are concatenated in order and the
result is the superstring.

**Validation.** A reader MUST reject the field as a fatal error if the block count is 0, if a block size is 0
or above 65536, if a block other than the last has a size other than 65536, if a primary index is not below
that block's size, if `symbol_count` is not `2 * n`, if the Huffman data fails any check of
[Huffman Coding](#huffman-coding-0x04-0xf4), if a block overruns the method data, or if the block count is
so large that the per-block minimum of 43 bytes (`4 + 4 + 2 + 32 + 1`) would overrun the method data.
All of these checks MUST be performed before allocating, because the block count is attacker-controlled.

**Empty and uniform buffers.** A block always holds at least one byte, so the empty buffer cannot be encoded
with `0x09`. The Huffman stage needs at least two distinct nibbles in each block's MTF output. A writer MUST
NOT use `0x09` for a buffer that violates either condition; it MUST pick another method.

### Dictionary Encoding (0x0A)

Dictionary encoding is optimized for repetitive string data by replacing repeated strings with short references to a dictionary.

Dictionary encoding **replaces** the superstring layout of the `strings` type: when the second byte of the
compression code is `0x0A`, the payload of a `strings` field is the dictionary layout below, and **no
superstring, and no start/end positions, are written**. The first byte of the compression code selects the
integer encoding used for the integer lists of this layout.

**Format (Concatenation mode):**

- `uint16`: dictionary size `N` (number of unique strings), little-endian
- `uints` list: dictionary entry offsets (`N + 1` values)
  - Offsets are cumulative from the start of the dictionary blob, so entry `i` is the bytes
    `[offsets[i], offsets[i+1])`
  - `offsets[N]` equals the total length of the dictionary blob
  - Offsets are encoded using the integer encoding strategy given by the first byte of the 2-byte compression
    code `0xHH0A`
- `varint`: dictionary blob length — the number of bytes of the concatenated dictionary blob. As everywhere
  else in BGFA, this is a **byte count**. It is stored after the offsets, because the offsets are variable
  length, so it is the only way for a decoder to find where the entries begin
- `bytes`: concatenated dictionary entries, stored raw (uncompressed) with no terminators, of exactly that
  many bytes. A writer MUST NOT store the same string as two entries
- `uints` list: one dictionary index per string, in the original order of the strings, encoded using the same
  integer strategy as the offsets. The number of indices equals the number of strings in the field

**Validation.** A reader MUST reject the field as a fatal error if `N` is 0, if `offsets[0]` is not 0, if any
offset is greater than the next, if the last offset does not equal the dictionary blob length, if the
dictionary blob length exceeds the remaining bytes, if a dictionary index is not below `N`, or if the index
list does not end exactly at the end of the field. A reader is not required to check that the entries are
distinct. All of these checks MUST be performed **before**
allocating the dictionary or the index array, because `N` and the offsets are attacker-controlled.

**Empty strings:** a string that is empty is a valid dictionary entry with `offsets[i] == offsets[i+1]`, so
empty segment sequences (GFA `*`) are representable. Because `offsets[0]` is 0 and indices start at 0, Elias
gamma (`0x04`) and omega (`0x05`) can never encode the offsets list, and a writer MUST NOT select them here.

**Outside a `strings` field.** When Dictionary is used as the `SS` method of a CIGAR code, the buffer is
treated as a list of exactly one string: `N = 1`, offsets `[0, L]` where `L` is the buffer length, and a
single index `0`. The integer lists are encoded with `varint` (`0x01`), since a CIGAR code has no integer
byte for them.

**Maximum dictionary size:** 65535 entries (`N` is a `uint16`)

**Expected Compression (informative):** 60-90% reduction on highly repetitive data (e.g., sample IDs repeated across thousands of walks).

**Primary Use Cases:**

- Sample identifiers in walk blocks
- Segment names with common prefixes
- Path names with structural patterns
- Any string list with high repetition

## CIGAR 4-byte Strategy Code Details

For CIGAR strings, 4-byte strategy codes are used. The format and decomposition strategies are defined in the [Strategy Code Format Summary](gfa_binary_format.md#strategy-code-format-summary).

The following decomposition strategies are available:

| Format       | Bytes              | Strategy                                      |
| ------------ | ------------------ | --------------------------------------------- |
| `0x00000000` | `[00, 00, 00, 00]` | none (identity); `RR`, `II` and `SS` reserved |
| `0x01??????` | `[01, RR, II, SS]` | numOperations + lengths + operations          |
| `0x020000??` | `[02, 00, 00, SS]` | string (treat as plain string)                |

A `cigar strings` field always contains exactly `record_num` entries, one per record of the containing block.
Entries are the GFA CIGAR strings; a path may carry several CIGARs separated by `,` within a single entry. A
GFA `*` is stored as the empty entry (see
[CIGAR Decomposition Strategies](gfa_binary_format.md#cigar-decomposition-strategies)), so an entry is never
`*`. The `uncompressed_*_cigars_len` field of the block is the sum of the byte lengths of the entries, without
any terminator, whatever the decomposition.

`SS` is any string method of [String Encoding Algorithms](#string-encoding-algorithms), validated against
`STRING_CODES` (see
[Strategy Code Validation Examples](gfa_binary_format.md#strategy-code-validation-examples)). The buffer it
encodes — the packed operations for `0x01`, the newline-terminated entries for `0x02` — is treated like a
superstring, and the method data is exactly as defined for that method.

### none (0x00000000)

**Bytes:** `[00, 00, 00, 00]`

The `record_num` CIGAR entries are written as raw ASCII, each followed by a line feed (`0x0A`). The payload is
therefore `record_num` terminated entries; a decoder MUST split on `0x0A` and drop the final terminator, which
yields exactly `record_num` entries. Because the terminator guarantees the last entry is present, an entry may
be the empty string, which is how a missing CIGAR (GFA `*`) is represented. The entry text is not compressed;
`SS` is reserved and MUST be `0x00`; a reader MUST reject any other value as an invalid strategy code.

An entry MUST NOT contain a `0x0A` byte, since `0x0A` is the entry separator. A reader MUST treat an entry
count other than `record_num` after splitting, or a payload whose last byte is not `0x0A`, as a fatal error.

### numOperations + lengths + operations (0x01??????)

**Format:** `0x01RRIISS`
**Bytes:** `[01, RR, II, SS]`

**Applicability.** This decomposition can only represent entries that are empty or that are a single CIGAR
string matching `([1-9][0-9]*[MIDNSHP=X])+`. If any entry of the field is something else — in particular an
entry holding several `,`-separated CIGARs, an operation length of 0, or a length with leading zeros — the
CIGARs MUST be treated as strings: a writer MUST NOT use `DD = 0x01` for that field and MUST use `DD = 0x00`
or `DD = 0x02` instead.

Four components are encoded, in this order:

1. `varint`: the number of CIGAR entries, which MUST equal `record_num`; any other value is a fatal error
2. The list of the number of operations in each CIGAR entry (`uints`, `record_num` values), encoded with `II`.
   An empty entry has 0 operations
3. The list of lengths of all operations of all entries, concatenated in entry order (`uints`), encoded with
   `RR`. The total number of lengths is the sum of the operation counts in component 2, and every length
   MUST be at least 1
4. The operations as a single packed buffer, encoded with `SS`. See
   [Packed Operations String](#packed-operations-string)

Component 1 makes components 2 and 3 self-delimiting: a decoder knows how many operation counts and how many
lengths follow. Component 4 has **no** blob length: its method data occupies the rest of the owning
`compressed_*_cigars_len` field, exactly. With `SS = 0x00` its length MUST be `ceil(T / 2)` bytes, where `T`
is the total number of operations.

A decoder rebuilds each entry by writing, for each of its operations, the length in decimal (no leading
zeros) followed by the operation letter.

**Byte assignments:**

- First byte (`0x01`): Decomposition strategy (numOperations + lengths + operations)
- Second byte (`RR`): Integer encoding strategy for the operation **lengths**, e.g. `0x01` varint, `0x02`
  fixed16
- Third byte (`II`): Integer encoding strategy for the operation **counts**, e.g. `0x01` varint, `0x02`
  fixed16
- Fourth byte (`SS`): String encoding strategy for the packed operations, e.g. `0x00` none, `0x04` Huffman

**Example:** Strategy code `0x01010204` = Bytes `[0x01, 0x01, 0x02, 0x04]` means:

- First byte (`0x01`): use the numOperations + lengths + operations decomposition
- Second byte (`0x01`): encode the operation lengths with varint
- Third byte (`0x02`): encode the operation counts with fixed16
- Fourth byte (`0x04`): encode the packed operations with Huffman

### string (0x020000??)

**Bytes:** `[02, 00, 00, SS]`

The `record_num` CIGAR entries are written as raw ASCII, each followed by `\n` (`0x0A`), exactly as in the
`none` decomposition, and the resulting buffer is compressed as a single block with the string method `SS`.
After decoding, the buffer is split exactly as in the `none` decomposition, with the same checks.

**Byte assignments:**

- First byte (`0x02`): Decomposition strategy (string)
- Second byte (`RR`): Reserved (MUST be `0x00`)
- Third byte (`II`): Reserved (MUST be `0x00`)
- Fourth byte (`SS`): String encoding strategy for the whole buffer

The payload is `[blob length: varint][method data]`, framed as in [Blob Framing](#blob-framing): the blob
length is a byte count of the method data, and the method data MUST end exactly at the end of the owning
`compressed_*_cigars_len` field.

**Example:** Strategy code `0x02000003` = Bytes `[0x02, 0x00, 0x00, 0x03]` means:

- First byte (`0x02`): use the string decomposition
- Second byte (`0x00`): reserved
- Third byte (`0x00`): reserved
- Fourth byte (`0x03`): compress the newline-terminated CIGAR buffer with LZMA

### Packed Operations String

The `SS` component of the `numOperations` decomposition stores operation codes as nibbles. CIGAR operations
are mapped as follows:

```
M = 0x0 (match/mismatch)
I = 0x1 (insertion)
D = 0x2 (deletion)
N = 0x3 (skipped region)
S = 0x4 (soft clipping)
H = 0x5 (hard clipping)
P = 0x6 (padding)
= = 0x7 (sequence match)
X = 0x8 (sequence mismatch)
```

Codes `0x9` to `0xE` are unassigned, and `0xF` is the padding marker.

**Layout:** the operations of all entries are concatenated in entry order, two codes per byte:

- High nibble: the first operation of the pair
- Low nibble: the second operation of the pair
- If the total number of operations `T` is odd, the low nibble of the last byte is `0xF`

The decoded buffer MUST be exactly `ceil(T / 2)` bytes long. A reader MUST reject as a fatal error a buffer
of any other length, a code in `0x9`..`0xE`, a `0xF` anywhere except the low nibble of the last byte when `T`
is odd, and a low nibble of the last byte other than `0xF` when `T` is odd. When `T = 0` the buffer is empty.

The buffer is then encoded with the string method `SS`, like any other byte buffer.

**Example:** the entry `10M2I5D` has 3 operations `M`, `I`, `D`, i.e. codes `0x0`, `0x1`, `0x2`:

- packed operations: high nibble `0x0` and low nibble `0x1` gives `0x01`; the next byte has high nibble `0x2`
  and low nibble `0xF` (padding) giving `0x2F`
- with `RR = II = 0x01` (varint) and `SS = 0x00` (none), and assuming a single entry in the block, the whole
  payload is: `01` (one CIGAR entry) `03` (3 operations in this entry) `0A 02 05` (lengths 10, 2, 5) `01 2F`
  (packed operations, with no blob length: they run to the end of the field)
