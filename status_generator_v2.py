import json
import re
from typing import List, Dict, Any

# Paths
REQ_PATH = "new/company_requirements.jsonl"
MATCHES_PATH = "new/requirement_vendor_matches.jsonl"
OUTPUT_PATH = "new/requirement_vendor_judgments.jsonl"

# Configurations
HIGH_SCORE_THRESHOLD = 0.70
MEDIUM_SCORE_THRESHOLD = 0.60
LOW_SCORE_THRESHOLD = 0.50

# Heuristic Patterns
NEGATIVE_PATTERNS = [
    r"\bnot supported\b",
    r"\bdoes not support\b",
    r"\bunsupported\b",
    r"\bnot available\b",
    r"\bnot included\b",
    r"\bno support\b",
    r"\bcannot\b",
    r"\bnot fully native\b",
    r"\blimited or unavailable\b",
    r"\bexceed[s]?\b.*\brequirement",
    r"\b45[–-]60 days\b",
    r"\bnot available by default\b"
]
PARTIAL_PATTERNS = [
    r"\benterprise\b",
    r"\benterprise plan\b",
    r"\bpremium\b",
    r"\bhigher[- ]tier\b",
    r"\bon request\b",
    r"\boptional\b",
    r"\bconfigurable\b",
    r"\bcan integrate\b",
    r"\bmay support\b",
    r"\bcustom integration\b",
    r"\bthird[- ]party\b",
    r"\bvia api\b",
    r"\bwith additional setup\b",
    r"\bdepending on deployment\b",
    r"\bdepending on system configuration\b",
    r"\bdepending on service agreements\b",
    r"\bmay vary\b",
    r"\blimited\b",
    r"\btypically\b"
]
EXPLICIT_PATTERNS = [
    r"\bsupports\b",
    r"\bincludes\b",
    r"\bprovides\b",
    r"\benables\b",
    r"\bis supported\b",
    r"\bis available\b",
    r"\bcompatible with\b",
    r"\bintegrates with\b",
    r"\bmaintains\b",
    r"\ballows\b",
    r"\boffers\b"
]

# Read/Write JSON file
def load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

def write_jsonl(rows: List[Dict[str, Any]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# Builder/Format functions
def build_requirement_lookup(requirements: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {req["requirement_id"]: req for req in requirements}

def normalize_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text

def contains_pattern(text: str, patterns: List[str]) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def extract_keywords(text: str) -> List[str]:
    text = normalize_text(text)
    stopwords = {
        "the", "a", "an", "and", "or", "of", "to", "for", "with", "in", "on", "by",
        "must", "should", "shall", "be", "is", "are", "it", "this", "that", "as",
        "within", "under", "across", "using", "use", "include", "includes", "provide",
        "provides", "support", "supports", "system", "vendor", "such", "based",
        "available", "through", "across", "where", "applicable"
    }

    words = re.findall(r"[a-zA-Z0-9_+-]+", text)
    keywords = [w for w in words if len(w) > 2 and w not in stopwords]
    return list(dict.fromkeys(keywords))


def keyword_overlap_score(requirement_text: str, claims: List[str]) -> float:
    req_keywords = set(extract_keywords(requirement_text))
    if not req_keywords:
        return 0.0
    combined_claims = " ".join(claims)
    claim_keywords = set(extract_keywords(combined_claims))
    overlap = req_keywords.intersection(claim_keywords)
    return len(overlap) / max(len(req_keywords), 1)


def score_to_confidence(top_score: float, weak_match_warning: bool, judgment: str) -> str:
    if weak_match_warning:
        return "low"
    if judgment == "unknown":
        return "low"
    if top_score >= HIGH_SCORE_THRESHOLD:
        return "high"
    if top_score >= MEDIUM_SCORE_THRESHOLD:
        return "medium"
    return "low"


# Mapping support for each claims
def analyze_support(matched_claims: List[str]) -> Dict[str, Any]:
    explicit_count = 0
    partial_count = 0
    negative_count = 0

    for claim in matched_claims:
        claim_norm = normalize_text(claim)
        if contains_pattern(claim_norm, NEGATIVE_PATTERNS):
            negative_count += 1
        if contains_pattern(claim_norm, PARTIAL_PATTERNS):
            partial_count += 1
        if contains_pattern(claim_norm, EXPLICIT_PATTERNS):
            explicit_count += 1

    if negative_count > 0 and explicit_count == 0:
        support_level = "negative_or_missing"
    elif explicit_count > 0 and partial_count == 0:
        support_level = "explicit"
    elif explicit_count > 0 and partial_count > 0:
        support_level = "explicit_but_conditioned"
    elif partial_count > 0:
        support_level = "partial_or_inferred"
    else:
        support_level = "weak_or_unclear"
    return {
        "support_level": support_level,
        "explicit_count": explicit_count,
        "partial_count": partial_count,
        "negative_count": negative_count
    }


# Rules for special cases
def apply_requirement_specific_rules(requirement_text: str,matched_claims: List[str]) -> Dict[str, Any]:
    req = normalize_text(requirement_text)
    combined = normalize_text(" ".join(matched_claims))
    result = {
        "forced_judgment": None,
        "forced_reasoning": None,
        "forced_gap": None
    }

    # Cases for account deletion in 30 days
    if "30 days" in req and ("45-60 days" in combined or "45–60 days" in combined):
        result["forced_judgment"] = "does_not_meet"
        result["forced_reasoning"] = (
            "The vendor documentation states a 45–60 day deletion timeline, which conflicts with the required 30-day limit."
        )
        result["forced_gap"] = "Deletion timeline exceeds the required 30-day limit"
        return result

    # Markdown files support
    if "markdown" in req and "markdown" not in combined:
        if any(term in combined for term in ["pdf", "word", "text", "basic text"]):
            result["forced_judgment"] = "unknown"
            result["forced_reasoning"] = (
                "The matched evidence mentions some supported document formats, but it does not explicitly confirm Markdown support."
            )
            result["forced_gap"] = "Markdown support is not explicitly confirmed"
            return result

    # Okta requirement
    if "okta" in req:
        if "okta" not in combined and "sso" in combined:
            result["forced_judgment"] = "partially_meets"
            result["forced_reasoning"] = (
                "The vendor documentation indicates SSO-related support, but it does not clearly confirm native or explicit Okta support."
            )
            result["forced_gap"] = "Okta-specific support is not explicitly confirmed"
            return result

    # Cost cap requirement
    if "$18,000" in requirement_text or "18000" in requirement_text:
        if not any(sym in combined for sym in ["$", "18,000", "18000"]):
            result["forced_judgment"] = "unknown"
            result["forced_reasoning"] = (
                "The matched evidence discusses pricing or plans, but it does not provide enough concrete pricing information to verify the year-1 cost cap."
            )
            result["forced_gap"] = "Insufficient pricing detail to verify year-1 cost compliance"
            return result

    # Response time under 2 seconds
    if "under 2 seconds" in req:
        if "2 seconds" not in combined and "acceptable" in combined:
            result["forced_judgment"] = "unknown"
            result["forced_reasoning"] = (
                "The matched evidence makes a general performance claim, but it does not explicitly confirm response times under 2 seconds."
            )
            result["forced_gap"] = "No explicit sub-2-second response-time commitment"
            return result

    return result


# Mapping status with support
def status_requirement_vendor_match(
    match_row: Dict[str, Any],
    requirement: Dict[str, Any]
) -> Dict[str, Any]:
    requirement_id = match_row["requirement_id"]
    vendor = match_row["vendor"]

    requirement_text = requirement.get("requirement_text", "")
    priority = requirement.get("priority", "")
    requirement_section = requirement.get("section", "")

    matched_capability_ids = match_row.get("matched_vendor_cap_ids", [])
    matched_claims = match_row.get("matched_claims", [])
    matched_sections = match_row.get("matched_sections", [])
    matched_sources = match_row.get("matched_sources", [])
    similarity_scores = match_row.get("similarity_scores", [])
    top_score = match_row.get("top_score", 0.0) or 0.0
    weak_match_warning = match_row.get("weak_match_warning", False)
    support_analysis = analyze_support(matched_claims)
    support_level = support_analysis["support_level"]
    overlap = keyword_overlap_score(requirement_text, matched_claims)
    flags = []
    gaps = []

    if weak_match_warning:
        flags.append("weak_retrieval_match")
    if top_score < LOW_SCORE_THRESHOLD:
        flags.append("low_similarity")
    if overlap < 0.20:
        flags.append("low_keyword_overlap")
    if support_analysis["negative_count"] > 0:
        flags.append("negative_or_missing_language_detected")
    if support_analysis["partial_count"] > 0:
        flags.append("conditional_or_tier_limited_language_detected")

    # Reasoning rules
    if not matched_claims:
        status = "unknown"
        reasoning = "No matched vendor evidence was retrieved for this requirement."
        gaps.append("No supporting evidence found")
    elif support_level == "negative_or_missing":
        status = "does_not_meet"
        reasoning = (
            "The matched evidence contains negative, missing, or unsupported language and does not provide explicit support "
            "for the requirement."
        )
        gaps.append("Requirement appears unsupported in vendor documentation")
    elif top_score < LOW_SCORE_THRESHOLD and support_level == "weak_or_unclear" and overlap < 0.20:
        status = "unknown"
        reasoning = (
            "Only weakly matched evidence was retrieved, so the documentation does not provide enough reliable support "
            "to make a confident judgment."
        )
        gaps.append("Need clearer evidence directly aligned to the requirement")
    elif support_level == "explicit" and overlap >= 0.35:
        status = "meets"
        reasoning = (
            "The matched evidence explicitly supports the requirement and aligns well with the requirement wording."
        )
    elif support_level == "explicit_but_conditioned":
        status = "partially_meets"
        reasoning = (
            "The matched evidence suggests explicit support, but it appears conditional, tier-dependent, deployment-specific, "
            "or otherwise constrained."
        )
        gaps.append("Need confirmation of availability in the intended deployment or pricing scope")
    elif support_level == "partial_or_inferred":
        status = "partially_meets"
        reasoning = (
            "The matched evidence suggests partial or inferred support, but it does not fully or directly satisfy "
            "the requirement as written."
        )
        gaps.append("Need direct confirmation against the requirement text")
    else:
        status = "unknown"
        reasoning = (
            "Some related evidence was retrieved, but it is too vague or indirect to determine whether the requirement "
            "is satisfied."
        )
        gaps.append("Documentation is too vague for a confident compliance decision")

    override = apply_requirement_specific_rules(requirement_text, matched_claims)
    if override["forced_judgment"] is not None:
        status = override["forced_judgment"]
        reasoning = override["forced_reasoning"]
        if override["forced_gap"]:
            gaps.append(override["forced_gap"])
        flags.append("requirement_specific_override_applied")

    if priority.lower() == "mandatory" and status == "partially_meets":
        flags.append("mandatory_requirement_not_fully_satisfied")
    if priority.lower() == "mandatory" and status == "does_not_meet":
        flags.append("mandatory_requirement_failed")
    if priority.lower() == "mandatory" and status == "unknown":
        flags.append("mandatory_requirement_unresolved")

    confidence = score_to_confidence(top_score, weak_match_warning, status)

    # Evidence collection
    evidence = []
    for i, claim in enumerate(matched_claims):
        evidence.append({
            "source": matched_sources[i] if i < len(matched_sources) else None,
            "section": matched_sections[i] if i < len(matched_sections) else None,
            "snippet": claim
        })

    return {
        "requirement_id": requirement_id,
        "requirement_text": requirement_text,
        "requirement_section": requirement_section,
        "requirement_priority": priority,
        "vendor": vendor,
        "status": status,
        "confidence": confidence,
        "support_level": support_level,
        "reasoning": reasoning,
        "matched_vendor_cap_ids": matched_capability_ids,
        "evidence": evidence,
        "gaps": list(dict.fromkeys(gaps)),
        "flags": list(dict.fromkeys(flags)),
        "top_score": round(top_score, 4),
        "similarity_scores": similarity_scores
    }


# Main Function
def main():
    requirements = load_jsonl(REQ_PATH)
    matches = load_jsonl(MATCHES_PATH)
    req_lookup = build_requirement_lookup(requirements)
    status = []
    for match_row in matches:
        req_id = match_row["requirement_id"]
        requirement = req_lookup.get(req_id)
        if not requirement:
            print(f"WARNING: requirement_id {req_id} not found in requirements file")
            continue
        judgment_row = status_requirement_vendor_match(match_row, requirement)
        status.append(judgment_row)
    write_jsonl(status, OUTPUT_PATH)
    print(f"Process done! Saved {len(status)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()