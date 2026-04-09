# Imports
import json
from typing import List, Dict, Any
import numpy as np
from sentence_transformers import SentenceTransformer

# Paths
REQ_PATH = "new/company_requirements.jsonl"
ASSISTPRO_PATH = "new/assistpro_capabilities.jsonl"
DESKGENIE_PATH = "new/deskgenie_capabilities.jsonl"
OUTPUT_PATH = "new/requirement_vendor_matches.jsonl"

# Configurations
EMBEDDINGS_MODEL = "all-MiniLM-L6-v2"
TOP_K = 3
SIMILARITY_THRESHOLD = 0.6


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


# Company requirement builder - collects relevant information from the JSON into a string
def build_requirement_text(req: Dict[str, Any]) -> str:
    parts = []

    if req.get("priority"):
        parts.append(f"Priority: {req['priority']}")

    if req.get("section"):
        parts.append(f"Section: {req['section']}")

    if req.get("requirement_text"):
        parts.append(f"Requirement: {req['requirement_text']}")

    return " | ".join(parts)

# Vendor claims builder - collects relevant information from the JSON into a string
def build_vendor_capability_text(claim: Dict[str, Any]) -> str:
    claims = []

    if claim.get("section"):
        claims.append(f"Section: {claim['section']}")

    if claim.get("claim_text"):
        claims.append(f"Claim: {claim['claim_text']}")

    return " | ".join(claims)


# Validation Metrics
def cosine_similarity(query_vec: np.ndarray, doc_matrix: np.ndarray) -> np.ndarray:
    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-12)
    doc_norm = doc_matrix / (np.linalg.norm(doc_matrix, axis=1, keepdims=True) + 1e-12)
    return np.dot(doc_norm, query_norm)

def score_to_confidence(score: float) -> str:
    if score >= 0.75:
        return "high"
    elif score >= 0.65:
        return "medium"
    return "low"

# Retreival by comparing vendor embedding with requirement
def retrieve_matches_for_vendor(
    requirement: Dict[str, Any],
    vendor_name: str,
    vendor_caps: List[Dict[str, Any]],
    vendor_embeddings: np.ndarray,
    model: SentenceTransformer,
    top_k: int = 3,
    threshold: float = 0.60
) -> Dict[str, Any]:
    req_text = build_requirement_text(requirement)
    req_embedding = model.encode(req_text, convert_to_numpy=True)

    scores = cosine_similarity(req_embedding, vendor_embeddings)
    ranked_indices = np.argsort(scores)[::-1]

    selected = []
    for idx in ranked_indices:
        score = float(scores[idx])
        cap = vendor_caps[idx]

        if score >= threshold:
            selected.append((cap, score))

        if len(selected) >= top_k:
            break

    # Here, the top ranked single retrievals with low score activated the weak_match_warning flag
    weak_match_warning = False
    if not selected and len(ranked_indices) > 0:
        best_idx = ranked_indices[0]
        selected = [(vendor_caps[best_idx], float(scores[best_idx]))]
        weak_match_warning = True

    matched_vendor_cap_ids = [cap["vendor_cap_id"] for cap, _ in selected]
    matched_claims = [cap["claim_text"] for cap, _ in selected]
    matched_sections = [cap.get("section") for cap, _ in selected]
    matched_sources = [cap.get("source") for cap, _ in selected]
    similarity_scores = [round(score, 4) for _, score in selected]

    combined_evidence_text = " ".join(
        [f"{cap['vendor_cap_id']}: {cap['claim_text']}" for cap, _ in selected]
    )

    top_score = similarity_scores[0] if similarity_scores else None

    return {
        "requirement_id": requirement["requirement_id"],
        "requirement_text": requirement["requirement_text"],
        "priority": requirement.get("priority"),
        "requirement_section": requirement.get("section"),
        "vendor": vendor_name,
        "matched_sources": matched_sources,
        "matched_sections": matched_sections,
        "matched_vendor_cap_ids": matched_vendor_cap_ids,
        "matched_claims": matched_claims,
        "similarity_scores": similarity_scores,
        "top_score": top_score,
        "retrieval_confidence": score_to_confidence(top_score) if top_score is not None else None,
        "weak_match_warning": weak_match_warning,
        "retrieval_threshold": threshold,
        "combined_evidence_text": combined_evidence_text
    }

# Main function
def main():
    requirements = load_jsonl(REQ_PATH)
    assistpro_claims = load_jsonl(ASSISTPRO_PATH)
    deskgenie_claims = load_jsonl(DESKGENIE_PATH)

    assistpro_texts = [build_vendor_capability_text(claim) for claim in assistpro_claims]
    deskgenie_texts = [build_vendor_capability_text(claim) for claim in deskgenie_claims]

    model = SentenceTransformer(EMBEDDINGS_MODEL)

    assistpro_embeddings = model.encode(assistpro_texts, convert_to_numpy=True)
    deskgenie_embeddings = model.encode(deskgenie_texts, convert_to_numpy=True)

    req_vendor_matches = []

    for req in requirements:
        assistpro_result = retrieve_matches_for_vendor(
            requirement=req,
            vendor_name="AssistPro",
            vendor_caps=assistpro_claims,
            vendor_embeddings=assistpro_embeddings,
            model=model,
            top_k=TOP_K,
            threshold=SIMILARITY_THRESHOLD
        )
        req_vendor_matches.append(assistpro_result)

        deskgenie_result = retrieve_matches_for_vendor(
            requirement=req,
            vendor_name="DeskGenie",
            vendor_caps=deskgenie_claims,
            vendor_embeddings=deskgenie_embeddings,
            model=model,
            top_k=TOP_K,
            threshold=SIMILARITY_THRESHOLD
        )
        req_vendor_matches.append(deskgenie_result)

    write_jsonl(req_vendor_matches, OUTPUT_PATH)
    print(f"Process done! Saved {len(req_vendor_matches)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()