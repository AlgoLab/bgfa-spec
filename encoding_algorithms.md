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
  - [none (0x00??????)](#none-0x00)
  - [numOperations + lengths + operations (0x01??????)](#numoperations--lengths--operations-0x01)
  - [string (0x02??????)](#string-0x02)
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

1. **Metadata**: A list of numbers, encoded according to the first-byte strategy (varint, fixed16, etc).
   This list contains first all start positions, then all end positions of the strings.

   The first-byte strategy determines how this list of numbers is encoded.
   Start and end positions are encoded as two separate contiguous lists: first all start positions, then all end positions. Both lists use the same integer encoding strategy.

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
of bytes remaining in the owning `compressed_*_len` field.

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

**Layout of a `uints-delta` field.** In byte order, a `uints-delta` field is exactly:

```
[method preamble, if any][absolute value 0] ... [absolute value n-1][sign bits]
```

The sign `bits` field comes last, in the trailing `bits`-fields group of the owning `compressed_*_len`
field, per rule 3. The "method preamble" is present only for
[Rice (`0x07`)](#rice-0x07), whose one-byte `k` parameter therefore precedes the first absolute value.
There is no preamble for any other method.

Note that there is **one delta stream per field** and it is never restarted part-way: see the `uints-delta`
definition in [Type Definitions](gfa_binary_format.md#type-definitions).

**Validation.** A reader MUST reject the field as a fatal error if the sign `bits` field does not decode to
exactly one sign bit per integer, or if the absolute values do not terminate exactly at the start of the
trailing sign `bits` field — that is, at `compressed_*_len` minus `8 * ceil(n / 64)` bytes. Any bytes
between the last absolute value and the sign `bits` field are a fatal error, so a non-canonical encoding
that pads the absolute list is rejected. Negative absolute values are impossible by construction, but a
decoder MUST still reject an absolute value that cannot be represented in the width implied by the field's
integer strategy, rather than silently wrapping it.

**Reconstruction.** The decoded values are the running sum of the signed deltas. The first value is the
first delta itself; every later value is the previous value plus its delta. A reader MUST reject the
field as a fatal error if the running sum leaves the range the field allows — for the
`walks_segments` field that is `0 .. 2^64 - 1`, since segment IDs are unsigned — and MUST NOT wrap.

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

**Zero cannot be represented.** Gamma has no codeword for `n = 0`, because `L` would be 0 and the unary
part `0` would not be a legal code. A writer MUST NOT select `0x04` for a field whose values can be 0 —
in particular for any field holding segment IDs, which start at 0. A reader MUST reject a field as a
fatal error if the unary prefix decodes to `L = 0`, or if any other part of the value cannot be decoded.

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
for a field whose values can be 0, and a reader can never legitimately decode a `0` with this method.

### Golomb (0x06)

Golomb encoding uses a parameter `b`, which is **fixed at 128** and is per field: every field encoded with
`0x06` uses `b = 128`, and `b` is **not transmitted**.

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

- The parameter `k` is **per field** and MUST be stored explicitly as a single raw byte (not a varint),
  before any encoded value. It is not part of the strategy code. `k` MUST satisfy `1 <= k <= 31`; an
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
- Encoded values follow the parameter byte

### StreamVByte (0x08)

StreamVByte encodes integers in groups of four, with one control byte per group. It is self-delimiting
only in the sense of [Blob Framing](#blob-framing): a reader decodes exactly the number of integers the
containing block header implies and MUST stop there.

**Format:**

- The integers are encoded in groups of exactly 4. Every group, including a final incomplete one, is
  preceded by exactly one control byte.
- Control byte bits `2*i` and `2*i + 1` select the width of the `i`-th integer of the group:

  | bit `2*i` | bit `2*i + 1` | width of integer `i` |
  | -------- | ------------- | ------------------- |
  | 0        | 0             | 1 byte              |
  | 1        | 0             | 2 bytes             |
  | 0        | 1             | 4 bytes             |
  | 1        | 1             | 4 bytes             |

  There is no 3-byte width: two control bits cannot express one, and a writer MUST NOT produce one.
- Each integer is stored little-endian in its width, with the bytes above the value set to 0.
- A writer MUST use the smallest width that can represent the value: below 256 always 1 byte, below
  65536 always 2 bytes, otherwise 4 bytes. A reader MUST reject as a fatal error a value that does not fit
  the width its control byte selects, rather than truncating it.
- If the final group holds `m < 4` integers, the control bits `2*m` .. `7` describe integers that are not
  present. A writer MUST set them to 0; a reader MUST ignore them.
- A reader MUST reject as a fatal error a field that does not end exactly after the declared number of
  integers has been decoded, i.e. one that leaves a partial group.

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
- For `fixed16`, `fixed32` and `fixed64`, a value that does not fit in the width MUST be rejected as a fatal
  error; it MUST NOT be silently truncated to the low bits.
- A reader MUST NOT allocate a buffer whose size is derived from an unvalidated header or payload field. Every
  derived size MUST be validated first, as described in
  [Limits and Validation](gfa_binary_format.md#limits-and-validation).
- Arithmetic on sizes derived from the header (products, sums, `ceil(n / 4)`, `8 * ceil(n / 64)`,
  `16 * ceil(n / 64)`, dictionary `N + 1`) MUST be performed with overflow checking, and a reader MUST
  reject the field rather than wrap around.

## String Encoding Algorithms

The following algorithms operate on the superstring blob.

### None / Identity (0x00)

The method data is the superstring itself, stored as raw bytes with no transformation. Its length is exactly
the blob length of [Blob Framing](#blob-framing). The string metadata (start/end positions from the integer
encoding) defines how to slice individual strings from the superstring.

### Zstd (0x01)

The superstring is compressed using [Zstandard](https://facebook.github.io/zstd/) compression.

The method data is the compressed stream, whose byte length is exactly the blob length of
[Blob Framing](#blob-framing).

### Gzip (0x02)

The superstring is compressed using [gzip](https://www.gnu.org/software/gzip/) compression.

The method data is the compressed stream, whose byte length is exactly the blob length of
[Blob Framing](#blob-framing).

### LZMA (0x03)

The superstring is compressed using [LZMA](https://www.7-zip.org/sdk.html) compression.

The method data is the compressed stream, whose byte length is exactly the blob length of
[Blob Framing](#blob-framing).

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
  [Packed Operations String](#packed-operations-string), so `L` is that buffer's length in bytes.

In both cases `0x04` splits each byte of the buffer into a high and a low nibble in that order, per
[Nibble-Level Processing](#nibble-level-processing); the CIGAR buffer is nibble-*packed* data, but it is
still a byte buffer for the purposes of this method.

**Deriving the bitstream length.** After decoding the `symbol_count` varint, the bitstream occupies the rest
of the method data, i.e. `blob length - 2 - codebook_len - (bytes of the symbol_count varint)` bytes, where
`blob length` is the method-data byte count read by [Blob Framing](#blob-framing). A reader
MUST reject the field as a fatal error if `blob length` is smaller than that sum, or if the number of symbols
implied by `symbol_count` cannot fit in the available bitstream.

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

1. Convert each input byte to two nibbles (high nibble, low nibble)
2. Look up each nibble's code in the reconstructed codebook
3. Concatenate all codes into a bitstream
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

### Reserved: Arithmetic Coding (`0x06`)

Code `0x06` is **reserved and MUST NOT be used** in BGFA version 0. An earlier draft assigned it to a
byte-oriented arithmetic coder, but the required byte-exact details (register initialisation, the
renormalisation trigger, carry propagation into the pending count, and the final flush) were never pinned
down, and arithmetic coders are bit-incompatible at that level. Two conforming implementations would have
produced different files.

A reader MUST treat `0x06` as an unknown strategy code and report a fatal error. It may be assigned in a
future version, at which point this section must be replaced by a full specification.

### Bzip2 (0x07)

The method data is a single bzip2 stream whose byte length is exactly the blob length of
[Blob Framing](#blob-framing).

### BWT + Huffman (0x09)

Burrows-Wheeler Transform + Huffman coding provides excellent compression for repetitive sequences like DNA.
The pipeline is:

1. Apply Burrows-Wheeler Transform in fixed 64KB blocks
2. Apply Move-to-Front transform
3. Encode each MTF byte stream with nibble-level Huffman (`0x04`, see
   [Huffman Coding](#huffman-coding-0x04-0xf4))

The block size is fixed at 65536 bytes (64KB). Only the last block may be shorter.

**Format** — the method data is:

- `uint32`: number of BWT blocks, little-endian
- For each block, in order:
  - `uint32`: primary index (the row index of the original block in the sorted rotation matrix)
  - `uint32`: block size in bytes (1..65536)
  - `uint16`: `codebook_len` (MUST be 32)
  - `bytes`: the 32-byte nibble Huffman codebook
  - `bytes`: Huffman-encoded MTF stream, occupying the remainder of the method data for this block

**Framing.** The outer `blob length` varint of [Blob Framing](#blob-framing) applies here as it does to
every method: it is a byte count of the whole method data, and the decoder bounds its reads with it.

Unlike `0x04`/`0xF4`, this method needs no internal `symbol_count` field: each block header carries its own
`block size`, which already gives the decoded item count, since each block decodes to exactly `block size`
MTF bytes, i.e. `2 * block size` nibbles. A decoder decodes exactly that many symbols using the codebook
stored at the start of the block, then advances to the next byte boundary; that is what makes each block
self-delimiting.

**Validation.** A reader MUST reject the field as a fatal error if the block count is 0, if a block size is 0
or above 65536, if a primary index is not below that block's size, if a block overruns the method data, or
if the block count is so large that the per-block minimum of 42 bytes
(`4 + 4 + 2 + 32`) would overrun the method data.
All of these checks MUST be performed before allocating, because the block count is attacker-controlled.

Blocks are concatenated in order and the result is the superstring.

### 2-bit DNA Encoding (0x05)

2-bit DNA encoding provides optimal compression for DNA/RNA sequences by encoding each nucleotide in 2 bits instead of 8 bits (75% size reduction). This is the most impactful encoding for pangenome data where sequences typically comprise 70-80% of file content.

**Nucleotide Mapping:**

- A (or a) = 00
- C (or c) = 01
- G (or g) = 10
- T (or t) = 11
- U (or u) = 11 (RNA uracil treated as thymine)

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
Ambiguity codes (N, R, Y, K, M, S, W, B, D, H, V, -) and unknown characters are stored in the exception table
with their original ASCII values, allowing perfect reconstruction while maintaining compression on standard
ACGT sequences.

An exception position unambiguously identifies a **character** of the decoded sequence, not a byte or a
nibble of the packed stream, so no additional high/low-nibble selector is needed: the decoder expands
`packed_bases` into the nucleotide sequence and then overwrites position `p` of that sequence with the
corresponding exception character.

**Case is not preserved.** All ten codes above map to the uppercase output `A`, `C`, `G`, `T`, so a writer
that encodes `acgt` produces a buffer that decodes to `ACGT`. A writer that must round-trip case MUST place
every lowercase character in the exception table with its original ASCII value, since the table stores
arbitrary characters; lowercasing is then an ordinary exception case. Nothing forbids a writer from doing
this, and a reader MUST NOT assume the table only ever holds ambiguity codes.

**Empty sequences:** a nucleotide sequence of length 0 is encoded as `nucleotide_count = 0`, a flags byte
of `0x00`, no `packed_bases` bytes, and no exception table, i.e. 2 bytes of method data.

**Expected Compression:** 75% reduction on pure DNA/RNA sequences, slightly less with ambiguity codes.

**Primary Use Case:** Segment sequences, which are typically the largest data component in BGFA files.

### Run-Length Encoding (0x08)

Run-Length Encoding efficiently compresses sequences with repeated characters (homopolymers in DNA, repeated operations in other contexts). The implementation uses a hybrid mode that switches between raw and RLE encoding to prevent expansion on non-repetitive data.

**Format** — the method data is:

- `varint`: run count `R` (number of runs)
- For each of the `R` runs:
  - 1 byte: mode (0x00=raw, 0x01=RLE)
  - `varint`: run data length
  - run data:
    - If raw mode: raw bytes
    - If RLE mode: sequence of `[char: 1 byte][count: varint]` pairs

**Framing.** RLE is self-delimiting through the leading run count. The outer blob length of
[Blob Framing](#blob-framing) is a byte count covering the whole of the method data described above, and is
what a decoder uses to bound its reads; the run count is what tells it when to stop.

**Validation.** A reader MUST reject the field as a fatal error if the run count, or the sum of the run data
lengths, exceeds the remaining method data, and MUST bound `R` and every run length by the method data length
**before** allocating. Run counts of zero are permitted and produce no output. In RLE mode a run's
`[char][count]` pairs MUST consume the run data exactly: a reader MUST reject a field as a fatal error if
the pairs do not end precisely on the run data boundary. A `count` of 0 is invalid and MUST be rejected,
since it would encode a run of no characters. The `char` of an RLE pair is one raw byte and is not subject
to any alphabet restriction.

**Algorithm:**

- Minimum run length: 3 characters (shorter runs use raw encoding)
- Automatically switches between raw and RLE modes within a string to prevent expansion on non-repetitive data
- Run counts encoded as varint for efficiency

**Mode selection:** A run of 3 or more identical consecutive characters uses RLE mode. Shorter sequences use raw mode.

**Expected Compression:** 30-50% reduction on sequences with homopolymers or repetitive patterns.

**Primary Use Cases:**

- DNA sequences with homopolymer runs (AAAAAAA, GGGGGG, TTTTTT)
- Can be combined with 2-bit DNA encoding for additional compression
- General string data with repeated characters

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
- `bytes`: concatenated dictionary entries (each entry is a unique string, no terminators), of exactly that
  many bytes
- `uints` list: one dictionary index per string, in the original order of the strings, encoded using the same
  integer strategy as the offsets. The number of indices equals the number of strings in the field

**Validation.** A reader MUST reject the field as a fatal error if `N` is 0, if any offset is greater than the
next, if the last offset does not equal the dictionary blob length, if the dictionary blob length exceeds the
remaining bytes, or if a dictionary index is not below `N`. All of these checks MUST be performed **before**
allocating the dictionary or the index array, because `N` and the offsets are attacker-controlled.

**Empty strings:** a string that is empty is a valid dictionary entry with `offsets[i] == offsets[i+1]`, so
empty segment sequences (GFA `*`) are representable.

**Maximum dictionary size:** 65535 entries (`N` is a `uint16`)

**Expected Compression:** 60-90% reduction on highly repetitive data (e.g., sample IDs repeated across thousands of walks).

**Primary Use Cases:**

- Sample identifiers in walk blocks
- Segment names with common prefixes
- Path names with structural patterns
- Any string list with high repetition

## CIGAR 4-byte Strategy Code Details

For CIGAR strings, 4-byte strategy codes are used. The format and decomposition strategies are defined in the [Strategy Code Format Summary](gfa_binary_format.md#strategy-code-format-summary).

The following decomposition strategies are available:

| Format       | Bytes              | Strategy                             |
| ------------ | ------------------ | ------------------------------------ |
| `0x00??????` | `[00, 00, 00, SS]` | none (identity); `RR`, `II` and `SS` reserved |
| `0x01??????` | `[01, RR, II, SS]` | numOperations + lengths + operations |
| `0x02??????` | `[02, 00, 00, SS]` | string (treat as plain string)       |

A `cigar strings` field always contains exactly `record_num` entries, one per record of the containing block.
Entries are the GFA CIGAR strings; a path may carry several CIGARs separated by `,` within a single entry,
and `*` denotes "no alignment".

### none (0x00??????)

**Bytes:** `[00, 00, 00, SS]`

The `record_num` CIGAR entries are written as raw ASCII, each followed by a line feed (`0x0A`). The payload is
therefore `record_num` terminated entries; a decoder MUST split on `0x0A` and drop the final terminator, which
yields exactly `record_num` entries. Because the terminator guarantees the last entry is present, an entry may
be the empty string, which is how "no CIGAR" is represented. The entry text is not compressed; `SS` is
reserved and MUST be `0x00`; a reader MUST reject any other value as an invalid strategy code.

An entry MUST NOT contain a `0x0A` byte, since `0x0A` is the entry separator. A reader MUST treat an entry
count other than `record_num` after splitting as a fatal error.

### numOperations + lengths + operations (0x01??????)

**Format:** `0x01RRIISS`
**Bytes:** `[01, RR, II, SS]`

Four components are encoded, in this order:

1. `varint`: the number of CIGAR entries, which is `record_num`
2. The list of the number of operations in each CIGAR entry (`uints`, `record_num` values), encoded with `II`
3. The list of lengths of all operations of all entries, concatenated in entry order (`uints`), encoded with
   `RR`. The total number of lengths is the sum of the operation counts in component 2
4. The operations as a single packed string, encoded with `SS`. See
   [Packed Operations String](#packed-operations-string)

Component 1 makes the payload self-delimiting: a decoder knows how many operation counts and how many lengths
follow.

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

### string (0x02??????)

**Bytes:** `[02, 00, 00, SS]`

The `record_num` CIGAR entries are written as raw ASCII, each followed by `\n` (`0x0A`), exactly as in the
`none` decomposition, and the resulting buffer is compressed as a single block with the string method `SS`.

**Byte assignments:**

- First byte (`0x02`): Decomposition strategy (string)
- Second byte (`RR`): Reserved (MUST be `0x00`)
- Third byte (`II`): Reserved (MUST be `0x00`)
- Fourth byte (`SS`): String encoding strategy for the whole buffer

`SS` MUST be one of the byte-string methods defined for an arbitrary buffer: `0x00`, `0x01`, `0x02`, `0x03`,
`0x04` or `0xF4`. A writer MUST NOT use `0x05`, `0x06`, `0x07`, `0x08`, `0x09` or `0x0A` here, and a reader
MUST treat those as a fatal error.

The compressed buffer is a single byte-string blob: the `blob length: varint` of
[Blob Framing](#blob-framing) precedes it and is a byte count of the compressed stream.

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

Codes `0x9` to `0xE` are unassigned, and `0xF` is the padding marker. A reader MUST reject a packed
operations buffer in which any code other than `0xF` is outside `0x0`..`0x8`, as a fatal error; `0xF` is
permitted only as the low nibble of the final byte, and its appearance anywhere else is a fatal error.

**Layout:** the operations of all entries are concatenated in entry order, two codes per byte:

- High nibble: the first operation of the pair
- Low nibble: the second operation of the pair
- If the total number of operations is odd, the low nibble of the last byte is `0xF`

The buffer is then encoded with the string method `SS`. Only the **byte-string** methods are defined for this
buffer in BGFA version 0: `0x00` (none), `0x01` (zstd), `0x02` (gzip), `0x03` (lzma), `0x04` (nibble-level
Huffman) and `0xF4` (byte-level Huffman). Each of them applies to an arbitrary byte buffer, so the packed
operations are encoded like any other string. The DNA-specific, column-oriented methods (`0x05` 2-bit,
`0x06` reserved, `0x08` RLE, `0x09` BWT+Huffman) and `0x07` bzip2 are **not** defined for this buffer: a
writer MUST NOT use them here, and a reader MUST treat one of them as a fatal error. Dictionary `0x0A` is
likewise not defined for this buffer, because it is defined only for the `strings` superstring layout; it MUST
NOT be used here.

**Example:** the entry `10M2I5D` has 3 operations `M`, `I`, `D`, i.e. codes `0x0`, `0x1`, `0x2`:

- packed operations: high nibble `0x0` and low nibble `0x1` gives `0x01`; the next byte has high nibble `0x2`
  and low nibble `0xF` (padding) giving `0x2F`
- with `RR = II = 0x01` (varint) and `SS = 0x00` (none), and assuming a single entry in the block, the whole
  payload is: `01` (one CIGAR entry) `03` (3 operations in this entry) `0A 02 05` (lengths 10, 2, 5) `01 2F`
  (packed operations)
