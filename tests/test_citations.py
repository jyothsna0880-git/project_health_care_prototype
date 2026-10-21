from core.citations import ids_in_text, normalize_id, verify
from core.schemas import Reference


def ref(ref_id: str) -> Reference:
    return Reference(id=ref_id, title="t", url="u", source="s")


def test_normalize_id_variants():
    assert normalize_id("pmid 12345678") == "PMID:12345678"
    assert normalize_id("12345678") == "PMID:12345678"
    assert normalize_id("nct01234567") == "NCT01234567"
    assert normalize_id("FDA: osimertinib mesylate") == "FDA:OSIMERTINIB MESYLATE"


def test_verify_splits_known_and_unknown_and_dedupes():
    sources = {"PMID:12345678": ref("PMID:12345678"), "NCT01234567": ref("NCT01234567")}
    verified, unverified = verify(["PMID 12345678", "12345678", "NCT01234567", "PMID:99999999", "NCT00000000"], sources)
    assert verified == ["PMID:12345678", "NCT01234567"]
    assert unverified == ["PMID:99999999", "NCT00000000"]


def test_ids_in_text_finds_all_id_types():
    text = "Osimertinib is first-line [FDA:OSIMERTINIB MESYLATE] [PMID:12345678]; see NCT01234567."
    assert ids_in_text(text) == ["NCT01234567", "PMID:12345678", "FDA:OSIMERTINIB MESYLATE"]
    assert ids_in_text("No citation here.") == []
