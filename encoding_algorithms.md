# BGFA Encoding Algorithms

This document describes the encoding algorithms referenced by the [BGFA format](gfa_binary_format.md).
It covers integer encoding, string encoding, and specialized encodings used in block payloads.

## Table of Contents

- [String Encoding Overview](#string-encoding-overview)
  - [Superstring](#superstring)
  - [Payload Layout for `strings`](#payload-layout-for-strings)
- [Integer Encoding Algorithms](#integer-encoding-algorithms)
  - [Delta (0x03)](#delta-0x03)
  - [Elias Gamma (0x04)](#elias-gamma-0x04)
  - [Elias Omega (0x05)](#elias-omega-0x05)
  - [Golomb (0x06)](#golomb-0x06)
  - [Rice (0x07)](#rice-0x07)
  - [StreamVByte (0x08)](#streamvbyte-0x08)
  - [VByte (0x09)](#vbyte-0x09)
- [String Encoding Algorithms](#string-encoding-algorithms)
  - [Arithmetic Coding (0x06)](#arithmetic-coding-0x06)
  - [Huffman Coding (0x04, 0xF4)](#huffman-coding-0x04-0xf4)
  - [BWT + Huffman (0x07)](#bwt--huffman-0x07)
  - [2-bit DNA Encoding (0x05)](#2-bit-dna-encoding-0x05)
  - [Run-Length Encoding (0x08)](#run-length-encoding-0x08)
  - [Dictionary Encoding (0x0A)](#dictionary-encoding-0x0a)
  - [CIGAR-Specific Encoding (0x09)](#cigar-specific-encoding-0x09)
- [CIGAR 4-byte Strategy Code Details](#cigar-4-byte-strategy-code-details)
  - [numOperations + lengths + operations (0x01??????)](#numoperations--lengths--operations-0x01)
  - [string (0x02??????)](#string-0x02)
- [Walks and Paths 4-byte Strategy Code Details](#walks-and-paths-4-byte-strategy-code-details)
  - [orientation + strid (0x01??????)](#orientation--strid-0x01)
  - [orientation + numid (0x02??????)](#orientation--numid-0x02)

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
[start_0][start_1]...[start_n-1][end_0][end_1]...[end_n-1][blob]
```

All start positions are encoded first (as a contiguous list), followed by all end positions (as a contiguous list). Both lists use the same integer encoding strategy specified in the first byte of the compression code.

The `compressed_*_len` fields in block headers represent the total number of bytes for the encoded payload of that field, including both the integer metadata list and the compressed blob.

The `uncompressed_len` field is the sum of the lengths of the original strings (before any encoding).

## Integer Encoding Algorithms

### Varint (0x01)

Variable-length integer encoding optimized for small values.

**Format:**

- Each byte: 7 data bits + 1 continuation bit (1 = more bytes follow, 0 = last byte)
- Little-endian ordering (least significant group first)

### Fixed16 (0x02)

Each integer is encoded as a fixed 16-bit little-endian value.

### Delta (0x03)

The delta encoding stores differences between consecutive values. This is particularly effective for sorted or monotonically increasing sequences.

**Format:**

- First value stored as-is using the integer encoding method indicated by the strategy code
- Subsequent values stored as: value[i] - value[i-1]
- The decoder adds each delta to the previous reconstructed value

**Example:** Sequence [100, 105, 108, 110] encoded as delta:

- Stored: [100, 5, 3, 2]
- Decoded: [100, 100+5=105, 105+3=108, 108+2=110]

**Error handling:** A reader encountering a non-monotonic (decreasing) delta value during decoding MUST treat it as a fatal error.

### Elias Gamma (0x04)

Elias gamma encoding represents a number n using two parts:

1. Unary representation of floor(log2(n)) + 1
2. Binary representation of n - 2^floor(log2(n))

**Format:**

- For value n:
  - Write floor(log2(n)) + 1 in unary (that many 1 bits, followed by 0)
  - Write n - 2^floor(log2(n)) in binary (floor(log2(n)) bits)

**Example:** n = 5

- floor(log2(5)) + 1 = 3
- Unary: 1110
- n - 2^2 = 5 - 4 = 1 = 01 (2 bits)
- Complete: 111001

### Elias Omega (0x05)

Elias omega starts with 0 and builds up, using the previous code length.

**Format:**

- For n = 1: output "0"
- For n > 1:
  1. Write n in binary
  2. Remove leading 1
  3. Recursively encode length of remaining bits using omega
  4. Append original bits

### Golomb (0x06)

Golomb encoding uses a parameter b (default b=128).

**Format:**

- For value n:
  - quotient q = n // b, remainder r = n % b
  - Write q in unary (q ones, then zero)
  - Write r in binary using ceil(log2(b)) bits

**Default parameter:** b = 128

### Rice (0x07)

Rice coding is Golomb with b as a power of 2: b = 2^k.

**Format:**

- Parameter k (0-31) stored as the first byte of the integer payload (before the encoded values)
- For value n:
  - quotient q = n >> k
  - remainder r = n & (2^k - 1)
  - Write q in unary
  - Write r in binary using k bits

**Example:** For k=3 and sequence [5, 12, 7]:

- Parameter byte: 0x03
- Encoded values follow the parameter byte

### StreamVByte (0x08)

StreamVByte encodes multiple varints in parallel using SIMD-like packing.

**Format:**

- Control bytes indicate which varints use 1, 2, 3, or 4 bytes
- Data bytes contain the varints packed together

### VByte (0x09)

Variable Byte encoding uses 7 bits per byte for data, with high bit as continuation flag.

**Format:**

- Each byte: 7 data bits + 1 continuation bit (1 = more bytes follow, 0 = last byte)
- Little-endian ordering (least significant byte first)

### Fixed32 (0x0A)

Each integer is encoded as a fixed 32-bit little-endian value.

### Fixed64 (0x0B)

Each integer is encoded as a fixed 64-bit little-endian value.

## String Encoding Algorithms

The following algorithms operate on the superstring blob.

### None / Identity (0x00)

The superstring is stored as raw bytes with no transformation. The string metadata (start/end positions from the integer encoding) defines how to slice individual strings from the superstring.

### Zstd (0x01)

The superstring is compressed using [Zstandard](https://facebook.github.io/zstd/) compression.

### Gzip (0x02)

The superstring is compressed using [gzip](https://www.gnu.org/software/gzip/) compression.

### LZMA (0x03)

The superstring is compressed using [LZMA](https://www.7-zip.org/sdk.html) compression.

### Huffman Coding (0x04, 0xF4)

The Huffman encoding of a string consists of:

| Name              | Description                             | Type     |
| ----------------- | --------------------------------------- | -------- |
| `codebook_len`    | Length of the encoded codebook in bytes | `uint16` |
| `codebook`        | 16 little-endian uint16 bit-lengths     | `bytes`  |
| `huffman_encoded` | The encoded string                      | `bits`   |

**Codebook format:**
The codebook is exactly 32 bytes containing 16 little-endian uint16 values representing the bit-length for each nibble (0x0 through 0xF). Even entries with zero bit-length have a placeholder value of 0 in the codebook.

```python
codebook = struct.unpack('<16H', codebook_bytes)
# codebook[0] = bit-length for nibble 0x0
# codebook[1] = bit-length for nibble 0x1
# ...
# codebook[15] = bit-length for nibble 0xF
```

**Reconstruction:**
The decoder MUST reconstruct the Huffman codes from the 16 bit-lengths using canonical Huffman code assignment:

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

**Example:** Given bit-lengths: `{0x41: 2, 0x42: 3, 0x43: 3}` (symbols 'A', 'B', 'C'):

- Sorted by (bit-length, symbol): `[(0x41, 2), (0x42, 3), (0x43, 3)]`
- Code assignment:
  - 'A' (0x41): bit-length=2, code=0b00 (first, shortest)
  - 'B' (0x42): bit-length=3, code=(0b00+1)<<1 = 0b010
  - 'C' (0x43): bit-length=3, code=(0b010+1)<<0 = 0b011

**Encoding process:**

1. Convert each input byte to two nibbles (high nibble, low nibble)
2. Look up each nibble's code in the reconstructed codebook
3. Concatenate all codes into a bitstream
4. Pad to byte boundary with zeros

**Decoding:**
The byte-length of the `huffman_encoded` data is the total `compressed_len` of the field minus:

- bytes consumed by the string metadata
- 2-byte `codebook_len`
- 32 bytes for the codebook

The decoder MUST decode exactly `2 * L` symbols, where `L` is the number of characters in the string being reconstructed.

#### Nibble-Level Processing

1. **Symbol Extraction**: Each byte of the target string (the superstring) is treated as two 4-bit symbols:
   - Symbol A: High nibble (bits 4-7)
   - Symbol B: Low nibble (bits 0-3)

2. **Encoding Order**: For every byte, Symbol A is encoded first, followed immediately by Symbol B.

3. **Alphabet Size**: The codebook always contains 16 entries (representing nibbles 0x0 through 0xF). A bit-length of 0 indicates the nibble is not present.

### Arithmetic Coding (0x06)

**Format:**

- `uint32`: frequency table size (number of symbol-frequency pairs), little-endian
- `bytes`: frequency table (symbol:count pairs)
- `bytes`: arithmetic encoded data

The frequency table contains ONLY symbols with non-zero frequency. Each entry is a pair of:

- `symbol`: 1 byte (ASCII value)
- `frequency`: `uint32` little-endian (count of symbol occurrences)

The `frequency table size` field indicates the number of pairs in the table. Total frequency table size = `frequency_table_size * 5` bytes (1 byte symbol + 4 bytes frequency per entry).

### BWT + Huffman (0x07)

Burrows-Wheeler Transform + Huffman coding provides excellent compression for repetitive sequences like DNA. The pipeline is:

1. Apply Burrows-Wheeler Transform in fixed 64KB blocks
2. Apply Move-to-Front transform
3. Encode with Huffman coding

The block size is fixed at 65536 bytes (64KB).

**Format:**

- `uint32`: number of BWT blocks
- For each block:
  - `uint32`: primary index
  - `uint32`: block size
  - `bytes`: BWT-transformed data (MTF-encoded, then Huffman-encoded)

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

**Format:**

- 1 byte: flags
  - bit 0: `has_exceptions` (1 if exception table present, 0 otherwise)
  - bits 1-7: reserved (set to 0)
- `packed_bases`: 4 nucleotides per byte (2 bits each), padded with 0s if needed
- If the `has_exception` flag is set:
  - `varint`: exception count
  - `varint` list: exception positions (0-based indices in original sequence, absolute positions)
  - `bytes`: exception characters (one byte per exception, in ASCII)

**Exception Handling:**
Ambiguity codes (N, R, Y, K, M, S, W, B, D, H, V, -) and unknown characters are stored in the exception table with their original ASCII values, allowing perfect reconstruction while maintaining compression on standard ACGT sequences.

**Expected Compression:** 75% reduction on pure DNA/RNA sequences, slightly less with ambiguity codes.

**Primary Use Case:** Segment sequences, which are typically the largest data component in BGFA files.

### Run-Length Encoding (0x08)

Run-Length Encoding efficiently compresses sequences with repeated characters (homopolymers in DNA, repeated operations in other contexts). The implementation uses a hybrid mode that switches between raw and RLE encoding to prevent expansion on non-repetitive data.

**Format:**

- `varint`: run count (number of runs)
- For each run:
  - 1 byte: mode (0x00=raw, 0x01=RLE)
  - `varint`: run data length
  - run data:
    - If raw mode: raw bytes
    - If RLE mode: sequence of `[char: 1 byte][count: varint]` pairs

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

**Format (Concatenation mode):**

- `uint32`: dictionary size (number of unique strings), little-endian
- `uints` list: dictionary entry offsets (N+1 values, where N = dictionary size)
  - Offsets are cumulative from the start of the dictionary blob
  - The (N+1)-th offset equals the total blob length
  - Offsets are encoded using the integer encoding strategy specified in the first byte of the 2-byte compression code `0xHH0A`
- `bytes`: concatenated dictionary entries (each entry is a unique string, no terminators)
- `uints` list: indices into dictionary for each input string, encoded using the same integer strategy as offsets

**Maximum dictionary size:** 65536 entries (configurable)

**Expected Compression:** 60-90% reduction on highly repetitive data (e.g., sample IDs repeated across thousands of walks).

**Primary Use Cases:**

- Sample identifiers in walk blocks
- Segment names with common prefixes
- Path names with structural patterns
- Any string list with high repetition

### CIGAR-Specific Encoding (0x09)

CIGAR strings represent sequence alignments with alternating numbers and operation letters. This encoding exploits the structure of CIGAR strings to achieve better compression than general-purpose methods.

**CIGAR Operations:**

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

**Format:**

- `varint`: number of operations
- `packed_ops`: 2 operations per byte (4 bits each)
  - High nibble: operation n
  - Low nibble: operation n+1
  - If odd number of operations, low nibble of last byte = 0xF (padding marker)
- `varint` list: operation lengths

**Special case:** The CIGAR value `*` (indicating no alignment) is encoded as a single byte `0xFF`. This allows efficient representation of unaligned segments.

**Example:**
CIGAR string "10M2I5D" is encoded as:

- `num_ops`: 3 (varint)
- `packed_ops`: 0x01, 0x2F (operations M=0, I=1, D=2 with padding 0xF)
- `lengths`: 10, 2, 5 (varints)

**Expected Compression:** 40-60% reduction compared to ASCII CIGAR strings.

**Primary Use Cases:**

- Link overlaps (L lines in GFA)
- Path CIGAR strings (P lines in GFA)
- Any alignment representation using CIGAR format

## CIGAR 4-byte Strategy Code Details

For CIGAR strings, 4-byte strategy codes are used. The format and decomposition strategies are defined in the [Strategy Code Format Summary](gfa_binary_format.md#strategy-code-format-summary).

The following decomposition strategies are available:

| Format       | Bytes              | Strategy                             |
| ------------ | ------------------ | ------------------------------------ |
| `0x00??????` | `[00, ??, ??, ??]` | none (identity)                      |
| `0x01??????` | `[01, RR, II, SS]` | numOperations + lengths + operations |
| `0x02??????` | `[02, 00, II, SS]` | string (treat as plain string)       |

For identity (`0x00`), the CIGAR strings are stored as raw ASCII CIGAR strings separated by newlines (`0x0A`), with a final newline terminator. The `??` bytes are ignored on read and SHOULD be `0x00` when writing.

### numOperations + lengths + operations (0x01??????)

**Format:** `0x01RRIISS`
**Bytes:** `[01, RR, II, SS]`

Three components are encoded:

1. The list of the number of operations in each CIGAR string (`uints`) - encoded with strategy `II`
2. The list of lengths of the operations (`uints`) - encoded with strategy `RR`
3. The operations as a packed string - encoded with strategy `SS`

**Byte assignments:**

- First byte (`0x01`): Decomposition strategy (numOperations+lengths+operations)
- Second byte (`RR`): Integer encoding strategy for operation lengths (e.g., `0x01` for varint, `0x03` for LZMA)
- Third byte (`II`): Integer encoding strategy for operation counts (e.g., `0x01` for varint, `0x02` for fixed16)
- Fourth byte (`SS`): String encoding strategy for packed operations (e.g., `0x00` for none, `0x04` for Huffman)

**Example:** Strategy code `0x01020304` = Bytes `[0x01, 0x02, 0x03, 0x04]` means:

- First byte (`0x01`): Use numOperations+lengths+operations decomposition
- Second byte (`0x02`): Use fixed16 to encode the list of operation counts
- Third byte (`0x03`): Use LZMA to encode the operation lengths
- Fourth byte (`0x04`): Use Huffman to encode the packed operations string

### string (0x02??????)

**Format:** `0x0200IISS`
**Bytes:** `[02, 00, II, SS]`

The CIGAR strings are compressed as a single block, separated by newlines, using the method specified by `II` and `SS`.

**Byte assignments:**

- First byte (`0x02`): Decomposition strategy (string)
- Second byte (`0x00`): Reserved (MUST be `0x00`)
- Third byte (`II`): Integer encoding strategy (MUST be `0x00` for string decomposition)
- Fourth byte (`SS`): String encoding strategy (e.g., `0x03` for LZMA)

**Example:** Strategy code `0x02000003` = Bytes `[0x02, 0x00, 0x00, 0x03]` means:

- First byte (`0x02`): Use string decomposition
- Second byte (`0x00`): Reserved
- Third byte (`0x00`): No integer encoding (string mode)
- Fourth byte (`0x03`): Use LZMA to compress the newline-separated CIGAR strings

## Walks and Paths 4-byte Strategy Code Details

For walks and paths, 4-byte strategy codes are used. The format and decomposition strategies are defined in the [Strategy Code Format Summary](gfa_binary_format.md#strategy-code-format-summary).

The following decomposition strategies are available:

| Format       | Bytes              | Strategy            |
| ------------ | ------------------ | ------------------- |
| `0x00??????` | `[00, ??, ??, ??]` | none (identity)     |
| `0x01??????` | `[01, 00, HH, LL]` | orientation + strid |
| `0x02??????` | `[02, 00, II, 00]` | orientation + numid |

For identity (`0x00`), the walks data is stored in the native `walks` type format (see [Walks Type Format](gfa_binary_format.md#walks-type-format)): the lengths list follows the `II` strategy, the segments list follows the `SS` strategy, and orientations are raw bits. The `??` bytes are ignored on read and SHOULD be `0x00` when writing.

### orientation + strid (0x01??????)

**Format:** `0x0100HHLL`
**Bytes:** `[01, 00, HH, LL]`

Two components are encoded:

1. The list of orientations in binary form (0 corresponds to `>` or `+`, 1 corresponds to `<` or `-`) - encoded as `bits`
2. The list of segment IDs encoded as strings - encoded with 2-byte strategy `HHLL`

**Byte assignments:**

- First byte (`0x01`): Decomposition strategy (orientation + strid)
- Second byte (`0x00`): Reserved (MUST be `0x00`, ignored on read)
- Third byte (`HH`): Integer encoding strategy for string metadata
- Fourth byte (`LL`): String encoding strategy for segment IDs

**Example:** Strategy code `0x01000100` = Bytes `[0x01, 0x00, 0x01, 0x00]` means:

- First byte (`0x01`): Use orientation + strid decomposition
- Second byte (`0x00`): Reserved
- Third and fourth bytes (`0x01 0x00`): Use varint lengths + none for segment ID strings

### orientation + numid (0x02??????)

**Format:** `0x0200II00`
**Bytes:** `[02, 00, II, 00]`

Two components are encoded:

1. The list of orientations in binary form (0 corresponds to `>` or `+`, 1 corresponds to `<` or `-`) - encoded as `bits`
2. The list of segment IDs as integers - encoded with strategy `II`

**Byte assignments:**

- First byte (`0x02`): Decomposition strategy (orientation + numid)
- Second byte (`0x00`): Reserved (MUST be `0x00`, ignored on read)
- Third byte (`II`): Integer encoding strategy for segment IDs
- Fourth byte (`0x00`): Reserved (MUST be `0x00`)

**Example:** Strategy code `0x02000100` = Bytes `[0x02, 0x00, 0x01, 0x00]` means:

- First byte (`0x02`): Use orientation + numid decomposition
- Second byte (`0x00`): Reserved
- Third byte (`0x01`): Use varint for segment IDs
- Fourth byte (`0x00`): Reserved

**Layout:** `[orientation_bits][segment_ids_encoded]`
