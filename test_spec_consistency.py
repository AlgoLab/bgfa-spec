"""Consistency tests for the BGFA specification documents.

These tests pin the review-fix outcomes: they fail if a stale claim
reappears or if a hand-verifiable arithmetic example drifts. They are
change-detectors for the spec prose, not behavior tests: in a
specification repository the prose is the artifact under test.

All guards are bare ``assert`` statements, so ``python -O`` silently
disables this suite; run it without optimization.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
ENCODING = (ROOT / "encoding_algorithms.md").read_text()
BINARY = (ROOT / "gfa_binary_format.md").read_text()
# Whitespace-normalized variants: literal assertions match regardless of
# markdown line wrapping.
NORM_ENCODING = " ".join(ENCODING.split())
NORM_BINARY = " ".join(BINARY.split())


def section(text, start, end):
    """Return the text between two anchors, failing clearly if either is missing."""
    assert start in text, f"missing section anchor: {start!r}"
    assert end in text, f"missing section anchor: {end!r}"
    rest = text.split(start, 1)[1]
    assert end in rest, f"section end anchor {end!r} does not follow start anchor {start!r}"
    return rest.split(end, 1)[0]


def test_dictionary_max_size_is_65535():
    assert "Maximum dictionary size:** 65535 entries" in NORM_ENCODING
    assert "65536 entries" not in NORM_ENCODING


def test_huffman_example_codebook_passes_kraft():
    # Kraft's equality in the spec's exact-integer form: sum(2^(16-len)) == 65536
    codebook = {0x41: 1, 0x42: 2, 0x43: 2}
    assert sum(2 ** (16 - length) for length in codebook.values()) == 65536
    assert "{0x41: 1, 0x42: 2, 0x43: 2}" in NORM_ENCODING
    assert "{0x41: 2, 0x42: 3, 0x43: 3}" not in NORM_ENCODING


def test_huffman_example_codes_match_canonical_assignment():
    # Canonical Huffman assignment from the spec's pseudocode:
    # code = (code + 1) << (bit_len - prev_len) if prev_len > 0 else 0
    pairs = sorted([(0x41, 1), (0x42, 2), (0x43, 2)], key=lambda p: (p[1], p[0]))
    codes = {}
    code, prev_len = 0, 0
    for symbol, bit_len in pairs:
        code = (code + 1) << (bit_len - prev_len) if prev_len > 0 else 0
        codes[symbol] = (code, bit_len)
        prev_len = bit_len
    assert codes == {0x41: (0b0, 1), 0x42: (0b10, 2), 0x43: (0b11, 2)}
    assert "code=0b0 (first, shortest)" in NORM_ENCODING
    assert "code=(0b0+1)<<1 = 0b10" in NORM_ENCODING
    assert "code=(0b10+1)<<0 = 0b11" in NORM_ENCODING


def test_cigar_none_ss_is_reserved_not_ignored():
    assert "`RR`, `II` and `SS` reserved" in NORM_ENCODING
    assert "ignored on read" not in NORM_ENCODING
    assert "`SS` is reserved and MUST be `0x00`" in NORM_ENCODING


def test_rule2_self_delimiting_list_excludes_none():
    rule2 = section(BINARY, "**Self-delimiting integer fields.**", "3. **`bits`")
    rule2_norm = " ".join(rule2.split())
    method_list = rule2_norm.split("encoded with", 1)[1].split("MUST be decoded", 1)[0]
    assert "`none`" not in method_list
    for method in ("varint", "Elias gamma", "Elias omega", "Golomb", "Rice",
                   "StreamVByte", "VByte"):
        assert f"`{method}`" in method_list
    assert "`0x00` is excluded from integer positions" in rule2_norm


def test_rule1_positions_count_is_per_subfield():
    rule1 = section(BINARY, "**Fixed-size integer fields.**", "2. **Self-delimiting")
    rule1_norm = " ".join(rule1.split())
    assert "`2 * record_num`" not in rule1_norm
    assert "`record_num` for **each** of the Walks `start_positions` and `end_positions`" in rule1_norm
    assert "`compression_positions_start`" in rule1_norm
    assert "`compression_positions_end`" in rule1_norm
    assert "this fixed-width size applies to the absolute values of the deltas" in rule1_norm


def test_sign_bits_are_packed_bits_fields():
    rule1 = section(BINARY, "**Fixed-size integer fields.**", "2. **Self-delimiting")
    rule1_norm = " ".join(rule1.split())
    assert "the sign bits are a separate `bits` field covered by rule 3" in rule1_norm
    assert "run-length-encoded bitstream" not in rule1_norm
    assert "not a packed `bits` field" not in rule1_norm
    assert "Run-Length Bits" not in NORM_ENCODING
    assert "This is the encoding used for the sign bits" not in NORM_ENCODING
    packed = section(NORM_BINARY, "**Determining the number of bits (n):**", "**Size calculation:**")
    assert "`uints-delta` sign bits" in packed


def test_worked_examples_use_packed_sign_bits():
    assert "2 bytes of sign bits" not in NORM_BINARY
    assert "3 bytes of sign bits" not in NORM_BINARY
    assert "| 222 | `00 00 00 00 00 00 00 00` | `walks_segments` sign bits (3 bits, all 0) |" in NORM_BINARY
    assert "| 377 | `02 00 00 00 00 00 00 00` | `walks_segments` sign bits [0, 1], LSB-first `0x02` |" in NORM_BINARY
    assert "run-length bits" not in NORM_BINARY
    assert "372 bytes" not in NORM_BINARY
    assert "393 bytes" in NORM_BINARY


def test_rule3_bits_fields_come_last():
    rule3 = section(BINARY, "**`bits` fields.**", "4. **Blobs.**")
    rule3_norm = " ".join(rule3.split())
    assert "always the **last** part" not in rule3_norm
    assert "never followed by a non-`bits` field" in rule3_norm
    assert "`16 * ceil(record_num / 64)` for the Links block" in rule3_norm


def test_hep_renamed_to_haplotype():
    assert not re.search(r"_hep(_|\b)", BINARY)
    assert "`compression_haplotype`" in NORM_BINARY
    assert "`compressed_haplotype_len`" in NORM_BINARY
    assert "`uncompressed_haplotype_len`" in NORM_BINARY


def test_walks_type_format_covers_paths():
    assert "`uncompressed_walk_len` in a Walks block and `uncompressed_paths_len` in a Paths block" in NORM_BINARY
    assert "`compression_walks` in a Walks block and `compression_paths` in a Paths block" in NORM_BINARY


def test_walks_block_layout_maps_payload_to_owner():
    layout = section(NORM_BINARY, "**Layout:** each payload field occupies", "See [Payload Byte Layouts]")
    assert "`sequence_ids` → `compressed_sequence_len`" in layout
    assert "`haplotype_indices` → `compressed_haplotype_len`" in layout
    assert "`start_positions` then `end_positions` → `compressed_positions_len`" in layout


def test_walk_positions_are_zero_based_and_missing_only_as_a_pair():
    assert "reserved for future use" not in NORM_BINARY
    assert "1-based" not in NORM_BINARY
    assert "the 0-based start coordinate of the walk" in NORM_BINARY
    assert "the 0-based end coordinate of the walk" in NORM_BINARY
    assert "`start_position = 0` and `end_position = 0` together mean that both coordinates are missing" in NORM_BINARY
    assert "Exactly one missing coordinate cannot be represented" in NORM_BINARY
    assert "| 355 | `07 02` | `end_positions` absolute deltas [7, 2] |" in NORM_BINARY
    assert "W\tNA12878\t1\tscs\t1\t7\tscs-" in BINARY.split("### A.6 Round-trip")[1]


def test_end_positions_are_excluded_everywhere():
    conv = section(NORM_BINARY, "**Positions, indices and intervals.**", "**Integer lists.**")
    assert "**end position is excluded**" in conv
    assert "exactly like a Python slice `s[start:end]`" in conv
    assert "string `i` is `superstring[start[i]:end[i]]`" in NORM_ENCODING
    assert "entry `i` is `blob[offsets[i]:offsets[i+1]]`" in NORM_ENCODING
    assert "the walk covers `sequence[start_position:end_position]`" in NORM_BINARY
    # Appendix byte ranges use the half-open notation, never inclusive a-b ranges.
    assert not re.search(r"offsets \d+-\d+\)", BINARY)
    # The superstring example in the spec obeys the slice rule.
    sup, starts, ends = "ACGTTA", [0, 2, 4], [3, 5, 6]
    assert [sup[s:e] for s, e in zip(starts, ends)] == ["ACG", "GTT", "TA"]
    assert "`start = [0, 2, 4]` and `end = [3, 5, 6]`" in NORM_ENCODING


def test_spec_defines_version_1():
    assert "**BGFA version 1**" in NORM_BINARY
    assert "version 0" not in NORM_BINARY.replace("Version `0`", "")
    assert "Version 0" not in NORM_BINARY
    assert "version 0" not in NORM_ENCODING
    assert _dump_bytes()[4:6] == b"\x01\x00"


def test_mandatory_non_empty_names():
    assert "It is **mandatory and MUST NOT be empty**" in NORM_BINARY
    assert "MAY be the empty string, meaning \"not set\"" not in NORM_BINARY
    assert "a reader MUST treat an empty segment name" in NORM_BINARY
    assert "MUST NOT write an empty segment name or an empty `sample_id`" in NORM_BINARY


def test_unchecked_relations_are_explicit():
    assert "a reader MUST NOT reject a walk because `end_position` exceeds the length" in NORM_BINARY
    assert "a reader MUST NOT reject an entry because it does not hold one CIGAR per pair" in NORM_BINARY


def test_haplotype_index_is_zero_based():
    assert "a **0-based** index of the haplotype" in NORM_BINARY
    assert "`0` is not a valid haplotype index" not in NORM_BINARY


def test_star_cigar_is_stored_as_empty_string():
    assert "MUST translate a `*` CIGAR field into the empty string" in NORM_BINARY
    a3 = section(BINARY, "### A.3 Links block", "### A.4 Paths block")
    assert "2A 0A" not in a3
    assert "| 151 | `0A 0A` |" in " ".join(a3.split())


def test_cigar_ss_has_no_explicit_exclusions():
    assert "CIGAR_STRING_CODES" not in BINARY
    assert "column-oriented" not in NORM_ENCODING
    assert "the CIGARs MUST be treated as strings" in NORM_ENCODING


def test_only_gfa_1_2_is_referenced():
    for text in (NORM_BINARY, NORM_ENCODING):
        assert "GFA 1.1" not in text
        assert "GFA 1.0" not in text
    assert "from_iss" not in NORM_BINARY


def test_rule3_bits_fields_are_ordered_by_block_field_order():
    rule3 = section(BINARY, "**`bits` fields.**", "4. **Blobs.**")
    rule3_norm = " ".join(rule3.split())
    assert "in **block field order**" in rule3_norm
    assert "rank at that field's own position" in rule3_norm
    assert '"first" means first in that order' in rule3_norm
    assert "the order in that type's layout section" in rule3_norm


def test_walks_byte_order_places_sign_bits_before_orientations():
    assert (
        "all segment IDs of the walks (their absolute deltas, then their trailing sign `bits` field), "
        "followed by all walks orientations" in NORM_BINARY
    )


def test_uints_delta_validation_requires_exact_termination():
    assert "the owning region's inline absolute values" in NORM_ENCODING
    assert "the absolute values of **all** the owning region's `uints-delta` fields" in NORM_ENCODING
    assert "each field's absolute values end where the next field's absolute values begin" in NORM_ENCODING
    assert "minus the total byte size of **all** `bits` fields in that group" in NORM_ENCODING
    assert "do not terminate exactly at the start of the owning region's trailing `bits`-fields group" in NORM_ENCODING
    assert "run past the end of the owning" not in NORM_ENCODING


def test_payload_tables_note_uints_delta_is_split():
    assert "A `uints-delta` field is not contiguous" in NORM_BINARY
    assert "deferred to the trailing `bits`-fields group" in NORM_BINARY


def _dump_bytes():
    """Parse the appendix's full hex dump into bytes (fixed-column slicing)."""
    dump = BINARY.split("Full hex dump of the file:")[1].split("```")[1]
    data = bytearray()
    for line in dump.splitlines():
        if not line.strip():
            continue
        # Fixed columns: 4-char offset, 2-space separator, then 16 hex bytes
        # at 3 chars each. Slicing by column keeps the ASCII column (which may
        # contain a space byte) out of the parse, and tolerates a short final
        # line.
        data.extend(int(b, 16) for b in line[6:54].split())
    return data


def test_worked_example_hex_dump_is_consistent():
    data = _dump_bytes()
    assert len(data) == 393
    assert data[:4] == b"BGFA"
    # The three region length fields that grew with packed sign bits:
    # compressed_paths_len (A.4), compressed_positions_len and
    # compressed_walk_len (A.5).
    twenty = (20).to_bytes(8, "little")
    assert data[176:184] == twenty
    assert data[298:306] == twenty
    assert data[314:322] == twenty


def test_payload_table_rows_match_hex_dump():
    # Every payload-table row in the appendix must agree with the hex dump,
    # giving the tables an independent ground truth: the arithmetic model
    # test only cross-checks tables against each other.
    data = _dump_bytes()
    for a, b in [("### A.2 Segments block", "### A.3 Links block"),
                 ("### A.3 Links block", "### A.4 Paths block"),
                 ("### A.4 Paths block", "### A.5 Walks block"),
                 ("### A.5 Walks block", "### A.6 Round-trip")]:
        for row in _table_rows(section(BINARY, a, b), "Payload ("):
            parsed = _parse_payload_row(row)
            if parsed is None:
                continue
            offset, expected = parsed
            assert data[offset:offset + len(expected)] == expected, (
                f"payload row {row!r} does not match the hex dump"
            )


def test_parse_payload_row_rejects_malformed_rows():
    # Synthetic rows lock in the guard raises: a typo in the appendix must
    # fail loudly, never pass silently.
    with pytest.raises(AssertionError, match="expected 3 cells"):
        _parse_payload_row(["56", "`00 03`"])
    with pytest.raises(AssertionError, match="not a decimal offset"):
        _parse_payload_row(["1,024", "`00 03`", "meaning"])
    with pytest.raises(AssertionError, match="byte cell '' is empty"):
        _parse_payload_row(["56", "", "meaning"])
    with pytest.raises(AssertionError, match="byte cell '``' is empty"):
        _parse_payload_row(["56", "``", "meaning"])
    with pytest.raises(AssertionError, match="not a hex byte"):
        _parse_payload_row(["56", "`00 …`", "meaning"])
    # Header and separator rows of any width are skipped, not validated.
    assert _parse_payload_row(["Offset", "Bytes", "Meaning"]) is None
    assert _parse_payload_row(["OFFSET", "Bytes", "Meaning"]) is None
    assert _parse_payload_row(["------", "-----", "-----"]) is None
    assert _parse_payload_row(["-", "-", "-"]) is None
    # A well-formed row parses to (offset, bytes).
    assert _parse_payload_row(["56", "`00 03 06`", "meaning"]) == (56, b"\x00\x03\x06")


def test_signed_integers_terminology_and_prose_order():
    assert "sign bitstream" not in NORM_ENCODING
    assert "The i-th bit in the sign `bits` field corresponds to the sign" in NORM_ENCODING
    assert (
        "so the absolute values are [0, 1, 0, 1, 1], encoded per the integer strategy in the second byte "
        "of `compression_walks`, followed by the sign bits [0, 0, 0, 0, 0] packed into a trailing `bits` "
        "field" in NORM_BINARY
    )


def test_walks_sequence_ids_is_single_byte_uints():
    a5 = section(BINARY, "### A.5 Walks block", "### A.6 Round-trip")
    rows = _table_rows(a5, "Header (")
    seq = next(r for r in rows if r[0].strip("`") == "compression_sequence")
    assert len(seq[1].strip("`").split()) == 1
    assert "| `sequence_ids` | Walk sequence IDs | `uints` | `compressed_sequence_len` |" in NORM_BINARY


def test_uints_delta_code_width_is_single_byte():
    assert "A standalone `uints-delta` field" in NORM_BINARY
    assert "carries a **single** integer byte" in NORM_BINARY
    assert "`walks`/`uints-delta` fields (first byte integer, second byte integer)" not in NORM_BINARY
    assert "| `compression_positions_start` | `01` | varint for the start positions |" in NORM_BINARY
    assert "| `compression_positions_end` | `01` | varint for the end positions |" in NORM_BINARY


def test_compression_sequence_definition_type_is_byte():
    assert "| `compression_sequence` | Integer encoding strategy for the walk sequence IDs | `byte` |" in NORM_BINARY
    assert "| `compression_sequence` | Integer encoding strategy for the walk sequence IDs | `bytes[2]` |" not in NORM_BINARY


def test_no_residual_contiguity_claims():
    assert "the sign `bits` field is deferred to the owning region's trailing `bits`-fields group" in NORM_BINARY
    assert "Conceptually, a `uints-delta` field is" in NORM_ENCODING
    assert "In byte order this is not contiguous" in NORM_ENCODING
    assert "the payload is the absolute values of the deltas followed by the sign `bits` field" not in NORM_BINARY
    assert "the following 8 bytes hold the two sign bits" not in NORM_BINARY
    assert "the start-position magnitudes [1, 0] at 353" in NORM_BINARY
    assert "the end-position magnitudes [7, 2] at 355" in NORM_BINARY


def test_walks_lengths_sum_is_validated():
    assert "each L(i) MUST be at least 1" in NORM_ENCODING
    assert "the sum of all L(i) MUST equal `uncompressed_walk_len`" in NORM_ENCODING
    assert "A reader MUST validate the count, the sum, and that every L(i) is at least 1" in NORM_BINARY
    assert "a walk as one or more oriented segments" in NORM_ENCODING
    assert "a walk as one or more oriented segments" in NORM_BINARY
    assert "an empty walk cannot be represented" in NORM_ENCODING
    assert "an empty walk cannot be represented" in NORM_BINARY


def test_implementation_defined_caps_acknowledged():
    assert "divergence at the boundary is explicitly permitted" in NORM_BINARY


def _bits_bytes(n):
    return 8 * ((n + 63) // 64)


def _table_rows(text, heading):
    """Parse the markdown table that follows a heading line."""
    rows = []
    for line in text.split(heading, 1)[1].splitlines():
        if line.lstrip().startswith("|"):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif rows:
            break
    return rows


def _parse_payload_row(row):
    """Parse one payload-table row into (offset, bytes), or None for a
    header/separator row. Guards fail loudly on malformed rows so a typo in
    the appendix cannot pass silently: the row is the artifact under test."""
    assert len(row) == 3, f"payload row {row!r}: expected 3 cells, found {len(row)}"
    offset_cell, bytes_cell, meaning = row
    if re.fullmatch(r"Offset", offset_cell, re.I) or re.fullmatch(r"[-:]+", offset_cell):
        return None
    assert offset_cell.isdigit(), (
        f"payload row {row!r}: offset cell {offset_cell!r} is not a decimal offset"
    )
    tokens = bytes_cell.strip("`").split()
    assert tokens, f"payload row {row!r}: byte cell {bytes_cell!r} is empty"
    for token in tokens:
        assert re.fullmatch(r"[0-9a-fA-F]{2}", token), (
            f"payload row at offset {offset_cell} ({meaning}): byte cell {token!r} is not a hex byte"
        )
    return int(offset_cell), bytes(int(token, 16) for token in tokens)


def _header_value(text, field):
    for row in _table_rows(text, "Header ("):
        if row[0].strip("`") == field:
            return int(row[2])
    raise AssertionError(f"header field {field!r} not found")


def _payload_offset(text, meaning_substring):
    matches = [row for row in _table_rows(text, "Payload (")
               if meaning_substring in row[2].replace("`", "")]
    assert len(matches) == 1, (
        f"payload rows matching {meaning_substring!r}: expected exactly 1, found {len(matches)}"
    )
    return int(matches[0][0])


def test_appendix_arithmetic_model():
    a4 = section(BINARY, "### A.4 Paths block", "### A.5 Walks block")
    a5 = section(BINARY, "### A.5 Walks block", "### A.6 Round-trip")

    # Each region: (section, first field, compressed length header field,
    # bits fields in block field order as (meaning substring, n header field)).
    regions = [
        (a4, "walks_lengths", "compressed_paths_len",
         [("walks_segments sign bits", "uncompressed_paths_len"),
          ("walks_orientations", "uncompressed_paths_len")]),
        (a5, "start_positions absolute deltas", "compressed_positions_len",
         [("start_positions sign bits", "record_num"),
          ("end_positions sign bits", "record_num")]),
        (a5, "walks_lengths", "compressed_walk_len",
         [("walks_segments sign bits", "uncompressed_walk_len"),
          ("walks_orientations", "uncompressed_walk_len")]),
    ]
    for text, first_field, len_field, bits_fields in regions:
        start = _payload_offset(text, first_field)
        end = start + _header_value(text, len_field)
        sizes = [_bits_bytes(_header_value(text, n_field)) for _, n_field in bits_fields]
        running = end - sum(sizes)
        for (meaning, _), size in zip(bits_fields, sizes):
            assert _payload_offset(text, meaning) == running, (
                f"{meaning}: model says offset {running}, table says "
                f"{_payload_offset(text, meaning)}"
            )
            running += size
        assert _payload_offset(text, bits_fields[-1][0]) + sizes[-1] == end

    # A.5 header arithmetic: 1 (section_id) + 2 (record_num) + strategy code
    # bytes + 10 * 8 length bytes = 91.
    code_rows = [r for r in _table_rows(a5, "Header (") if r[0].startswith("`compression_")]
    code_bytes = sum(len(r[1].strip("`").split()) for r in code_rows)
    assert 1 + 2 + code_bytes + 10 * 8 == 91
    assert "11 + 80 = 91" in NORM_BINARY

    # Region boundaries and total size, as stated in the appendix headings.
    assert "A.3 Links block (54 bytes, offsets [99, 153))" in NORM_BINARY
    assert "A.4 Paths block (86 bytes, offsets [153, 239))" in NORM_BINARY
    assert "A.5 Walks block (154 bytes, offsets [239, 393))" in NORM_BINARY
    assert "393 bytes (17 + 82 + 54 + 86 + 154)" in NORM_BINARY

    # The appendix's own size decompositions agree with the model.
    assert (
        "20 = 1 byte of `walks_lengths` + 3 bytes of absolute deltas + 8 bytes of sign bits + 8 bytes "
        "of the `uint64` word of `walks_orientations`" in NORM_BINARY
    )
    assert (
        "20 = 2 bytes of `walks_lengths` + 2 bytes of absolute deltas + 8 bytes of sign bits + 8 bytes "
        "of the `uint64` word of `walks_orientations`" in NORM_BINARY
    )


def _pack_lsb_first(bits):
    """Pack a bit list LSB-first, zero-padding the final byte."""
    return sum(bit << i for i, bit in enumerate(bits))


def _pack_lsb_bytes(bits):
    """Pack a bit list LSB-first into whole bytes, zero-padding the last."""
    return bytes(_pack_lsb_first(bits[i:i + 8]) for i in range(0, len(bits), 8))


def _gamma_codeword(n):
    """Textbook Elias gamma: L - 1 zeros, then the L bits of n."""
    binary = bin(n)[2:]
    return [0] * (len(binary) - 1) + [int(bit) for bit in binary]


def _rice_bits(values, k):
    """Rice codewords for a list, concatenated in order."""
    bits = []
    for value in values:
        quotient, remainder = value >> k, value & ((1 << k) - 1)
        bits += [1] * quotient + [0]
        bits += [int(bit) for bit in bin(remainder)[2:].zfill(k)]
    return bits


def test_lsb_first_examples_are_arithmetically_correct():
    # BGFA has a single bit order: every bit stream is packed LSB-first. The
    # byte strings are recomputed here, so a wrong example cannot pass.
    bits = [1, 0, 1, 1, 0]
    assert _pack_lsb_first(bits) == 0b00001101 == 0x0D
    assert "`0b00001101` = `0D`" in NORM_BINARY
    # Elias gamma is textbook gamma: n = 5 is the 5-bit codeword 00101.
    assert _gamma_codeword(5) == [0, 0, 1, 0, 1]
    assert _pack_lsb_first(_gamma_codeword(5)) == 0b00010100 == 0x14
    assert "`0b00010100` = `0x14`" in NORM_ENCODING
    # n = 1 is the single bit 1, and the list [1, 5] packs to 0x29.
    assert _gamma_codeword(1) == [1]
    assert _pack_lsb_first(_gamma_codeword(1)) == 0b00000001 == 0x01
    assert "`0b00000001` = `0x01`" in NORM_ENCODING
    assert _pack_lsb_first(_gamma_codeword(1) + _gamma_codeword(5)) == 0b00101001 == 0x29
    assert "`0b00101001` = `0x29`" in NORM_ENCODING
    # Elias omega n = 5 is the 6-bit codeword 101010.
    omega = [1, 0, 1, 0, 1, 0]
    assert _pack_lsb_first(omega) == 0b00010101 == 0x15
    assert "`0b00010101` = `0x15`" in NORM_ENCODING
    # Rice k = 3, [5, 12, 7]: the 13-bit stream 0101101000111.
    rice = _rice_bits([5, 12, 7], 3)
    assert "".join(map(str, rice)) == "0101101000111"
    assert _pack_lsb_bytes(rice) == bytes([0x5A, 0x1C])
    assert "Complete list: `03 5A 1C`" in NORM_ENCODING
    # 2-bit DNA: "ACGT" and "ACGTA".
    acgt = [0, 0, 0, 1, 1, 0, 1, 1]
    assert _pack_lsb_bytes(acgt) == bytes([0xD8])
    assert "Packed: `0b11011000` = 0xD8 (1 byte)" in NORM_ENCODING
    assert _pack_lsb_bytes(acgt + [0, 0]) == bytes([0xD8, 0x00])
    assert "Packed: `0b11011000` `0b00000000` = 0xD8 0x00" in NORM_ENCODING


def test_single_bit_order_is_stated_and_no_msb_first_claim_survives():
    # Change detector: the two-order model must not creep back in.
    assert "There is exactly one bit order in BGFA" in NORM_BINARY
    assert "exactly two bit orders" not in NORM_BINARY
    assert "MSB-first" not in NORM_BINARY
    assert "MSB-first" not in NORM_ENCODING
    # Elias gamma is textbook gamma, and the divergence note is gone.
    assert "**textbook Elias gamma**" in NORM_ENCODING
    assert "not textbook Elias gamma" not in NORM_ENCODING
    assert "one bit longer than textbook gamma" not in NORM_ENCODING
    # The nibble-packed CIGAR operations buffer is explicitly out of scope.
    assert "Nibble order, not bit order" in NORM_ENCODING


def test_byte_order_examples_are_arithmetically_correct():
    # Every format that states a byte order must also show one. The byte
    # strings are recomputed here, so a wrong example cannot pass.
    value = 300
    assert value.to_bytes(2, "little").hex(" ").upper() == "2C 01"
    assert value.to_bytes(4, "little").hex(" ").upper() == "2C 01 00 00"
    assert value.to_bytes(8, "little").hex(" ").upper() == "2C 01 00 00 00 00 00 00"
    # varint: least significant 7-bit group first, continuation bit set on all
    # but the last byte.
    groups, n = [], value
    while True:
        groups.append(n & 0x7F)
        n >>= 7
        if not n:
            break
    varint = bytes(g | (0x80 if i < len(groups) - 1 else 0) for i, g in enumerate(groups))
    assert varint.hex(" ").upper() == "AC 02"
    assert "stored as `AC 02`" in NORM_ENCODING
    assert "stored least significant byte first as `2C 01`" in NORM_ENCODING
    assert "stored least significant byte first as `2C 01 00 00`" in NORM_ENCODING
    assert "stored least significant byte first as `2C 01 00 00 00 00 00 00`" in NORM_ENCODING
    # BWT + Huffman: uint32 block count, primary index and block size.
    assert (65536).to_bytes(4, "little").hex(" ").upper() == "00 00 01 00"
    assert "`00 00 01 00` (block size 65536)" in NORM_ENCODING
    # Dictionary: uint16 dictionary size N.
    assert (3).to_bytes(2, "little").hex(" ").upper() == "03 00"
    assert "a dictionary of 3 entries starts with `03 00`" in NORM_ENCODING
