import sys
from pathlib import Path

# Add pipeline directory to path to allow imports
sys.path.insert(0, str(Path(__file__).parent / "pipeline"))

import embedding_retrieval

def test_normalization():
    print("Testing Query Normalization...")
    query = "RDP, SMB, and LSASS on VPN (AD)?"
    normalized = embedding_retrieval.normalize_query(query)
    expected = "remote desktop protocol server message block and local security authority subsystem service on virtual private network active directory"
    assert normalized == expected, f"Expected: {expected!r}\nGot: {normalized!r}"
    print("✓ Normalization passed.")

def test_synonym_expansion():
    print("Testing Synonym Expansion...")
    query = "powershell script"
    expanded = embedding_retrieval.get_embedding_query(query)
    assert "script execution" in expanded
    assert "shell" in expanded
    print("✓ Synonym expansion passed.")

def test_entity_extraction():
    print("Testing Entity Extraction...")
    text = "We found CVE-2023-38545 and MITRE T1059.001 with powershell"
    entities = embedding_retrieval._extract_entities(text)
    assert "cve-2023-38545" in entities, f"Missing CVE in {entities}"
    assert "t1059.001" in entities, f"Missing MITRE ID in {entities}"
    assert "powershell" in entities, f"Missing term in {entities}"
    print("✓ Entity extraction passed.")

def test_domain_classification():
    print("Testing Domain-Aware Classification & Confidence...")
    
    # 1. MITRE match -> confidence should be 1.0
    res_mitre = embedding_retrieval.classify_domains("MITRE T1003 credential access")
    assert "CREDENTIAL_ACCESS" in res_mitre["domains"]
    assert res_mitre["confidence"] == 1.0, f"Expected 1.0 confidence for MITRE ID, got {res_mitre['confidence']}"
    
    # 2. Keywords match -> confidence should be based on match count
    res_keyword = embedding_retrieval.classify_domains("User received phishing email attachment")
    assert "EMAIL_ATTACK" in res_keyword["domains"]
    assert res_keyword["confidence"] >= 0.60, f"Expected high confidence for multiple keywords, got {res_keyword['confidence']}"
    
    # 3. No domains
    res_none = embedding_retrieval.classify_domains("something completely generic")
    assert not res_none["domains"]
    assert res_none["confidence"] == 0.0
    
    print("✓ Domain classification passed.")

def test_phrase_match():
    print("Testing Exact Phrase Match...")
    query_tokens = ["credential", "dumping"]
    candidate_tokens = ["lsass", "credential", "dumping", "mimikatz"]
    assert embedding_retrieval.is_exact_phrase_match(query_tokens, candidate_tokens)
    
    non_matching = ["credential", "theft", "dumping"]
    assert not embedding_retrieval.is_exact_phrase_match(query_tokens, non_matching)
    print("✓ Phrase matching passed.")

def test_weighted_keyword_overlap():
    print("Testing Weighted Keyword Overlap...")
    query_tokens = {"gopher", "tolerance"}
    candidate_fields = {
        "title": {"gopher", "tolerance"},
        "category": {"signal_interpretation"}
    }
    score = embedding_retrieval.compute_weighted_keyword_overlap(query_tokens, candidate_fields)
    assert abs(score - 1.0) < 1e-6, f"Expected 1.0, got {score}"
    print("✓ Weighted keyword overlap passed.")

def test_category_alignment():
    print("Testing Category Alignment...")
    # category credential_theft matches CREDENTIAL_ACCESS keywords (credential)
    assert embedding_retrieval.check_category_alignment("credential_theft", {"CREDENTIAL_ACCESS"})
    # category bypass_technique does not match EMAIL_ATTACK keywords
    assert not embedding_retrieval.check_category_alignment("bypass_technique", {"EMAIL_ATTACK"})
    print("✓ Category alignment passed.")

def test_retrieval_api_and_debug():
    print("Testing Retrieve API & Debug Mode...")
    # Debug False
    results = embedding_retrieval.retrieve("gopher CRLF", k=3, debug=False)
    assert len(results) <= 3
    for r in results:
        assert "id" in r
        assert "similarity" in r
        assert "hybrid_score" in r
        assert "confidence" in r
        assert "debug" not in r  # Debug info should not be returned by default
        
    # Debug True
    results_debug = embedding_retrieval.retrieve("gopher CRLF", k=3, debug=True)
    for r in results_debug:
        assert "debug" in r
        dbg = r["debug"]
        for key in ["embedding", "keyword", "domain_bonus", "domain_penalty", 
                    "entity_bonus", "category_bonus", "phrase_bonus", "technique_bonus",
                    "matched_domains", "matched_entities"]:
            assert key in dbg, f"Missing debug key: {key}"
    print("✓ Retrieve API and Debug mode passed.")

def main():
    try:
        test_normalization()
        test_synonym_expansion()
        test_entity_extraction()
        test_domain_classification()
        test_phrase_match()
        test_weighted_keyword_overlap()
        test_category_alignment()
        test_retrieval_api_and_debug()
        print("\nAll unit tests passed successfully!")
    except AssertionError as e:
        print(f"\nAssertion Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
