"""Consistency tests for the BGFA specification documents.

These tests pin the review-fix outcomes: they fail if a stale claim
reappears or if a hand-verifiable arithmetic example drifts. They are
change-detectors for the spec prose, not behavior tests: in a
specification repository the prose is the artifact under test.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent
ENCODING = (ROOT / "encoding_algorithms.md").read_text()
BINARY = (ROOT / "gfa_binary_format.md").read_text()
# Whitespace-normalized variants: literal assertions match regardless of
# markdown line wrapping.
NORM_ENCODING = " ".join(ENCODING.split())
NORM_BINARY = " ".join(BINARY.split())


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
    rule2 = BINARY.split("**Self-delimiting integer fields.**")[1].split("3. **`bits`")[0]
    rule2_norm = " ".join(rule2.split())
    method_list = rule2_norm.split("encoded with", 1)[1].split("MUST be decoded", 1)[0]
    assert "`none`" not in method_list
    for method in ("varint", "Elias gamma", "Elias omega", "Golomb", "Rice",
                   "StreamVByte", "VByte"):
        assert f"`{method}`" in method_list
    assert "`0x00` is excluded from integer positions" in rule2_norm


def test_rule1_positions_count_is_per_subfield():
    rule1 = BINARY.split("**Fixed-size integer fields.**")[1].split("2. **Self-delimiting")[0]
    rule1_norm = " ".join(rule1.split())
    assert "`2 * record_num`" not in rule1_norm
    assert "`record_num` for **each** of the Walks `start_positions` and `end_positions`" in rule1_norm
    assert "`compression_positions_start`" in rule1_norm
    assert "`compression_positions_end`" in rule1_norm
    assert "this fixed-width size applies to the absolute values of the deltas" in rule1_norm


def test_sign_bits_are_packed_bits_fields():
    rule1 = BINARY.split("**Fixed-size integer fields.**")[1].split("2. **Self-delimiting")[0]
    rule1_norm = " ".join(rule1.split())
    assert "the sign bits are a separate `bits` field covered by rule 3" in rule1_norm
    assert "run-length-encoded bitstream" not in rule1_norm
    assert "not a packed `bits` field" not in rule1_norm
    assert "Run-Length Bits" not in NORM_ENCODING
    assert "This is the encoding used for the sign bits" not in NORM_ENCODING
    packed = NORM_BINARY.split("**Determining the number of bits (n):**")[1].split("**Size calculation:**")[0]
    assert "`uints-delta` sign bits" in packed


def test_worked_examples_use_packed_sign_bits():
    assert "2 bytes of sign bits" not in NORM_BINARY
    assert "3 bytes of sign bits" not in NORM_BINARY
    assert "8 bytes of sign bits" in NORM_BINARY
    assert "run-length bits" not in NORM_BINARY
    assert "372 bytes" not in NORM_BINARY
    assert "395 bytes" in NORM_BINARY


def test_rule3_bits_fields_come_last():
    rule3 = BINARY.split("**`bits` fields.**")[1].split("4. **Blobs.**")[0]
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
    layout = NORM_BINARY.split("**Layout:** each payload field occupies")[1].split("See [Payload Byte Layouts]")[0]
    assert "`sequence_ids` → `compressed_sequence_len`" in layout
    assert "`haplotype_indices` → `compressed_haplotype_len`" in layout
    assert "`start_positions` then `end_positions` → `compressed_positions_len`" in layout


def test_end_positions_decision_recorded_as_kept():
    assert "reserved for future use and stays in the wire format, including in version 1.0" in NORM_BINARY
    assert "dead weight" not in NORM_BINARY
    assert "reconsidered" not in NORM_BINARY
    assert "accepted trade-off" in NORM_BINARY


def test_rule3_bits_fields_are_ordered_by_block_field_order():
    rule3 = BINARY.split("**`bits` fields.**")[1].split("4. **Blobs.**")[0]
    rule3_norm = " ".join(rule3.split())
    assert "in **block field order**" in rule3_norm
    assert "rank at that field's own position" in rule3_norm
    assert '"first" means first in that order' in rule3_norm