import json
from collections import defaultdict
from typing import List, Dict, Any

# Paths
JUDGMENTS_PATH = "new/requirement_vendor_judgments.jsonl"
OUTPUT_PATH = "new/final_vendor_evaluation.json"
STATUS_MAP = {
    "meets": "meets",
    "partially_meets": "partially_meets",
    "does_not_meet": "does_not_meet",
    "unknown": "unknown"
}

# Higher weighting for mandatory requirements
PRIORITY_WEIGHTS = {
    "mandatory": 3,
    "compliance": 2,
    "functional": 1,
    "performance": 1,
    "deployment": 1,
    "secondary": 0.5,
    "general": 1
}

# Base score by status
STATUS_SCORES = {
    "meets": 2,
    "partially_meets": 1,
    "does_not_meet": -2,
    "unknown": -1
}


# Read/Write JSON file
def load_jsonl(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

def write_json(data: Dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# Evidence builders
def build_evidence_list(row: Dict[str, Any]) -> List[Dict[str, str]]:
    evidence_items = row.get("evidence", [])
    cleaned = []
    for item in evidence_items:
        cleaned.append({
            "source": item.get("source", ""),
            "snippet": item.get("snippet", "")
        })
    return cleaned

def build_requirement_analysis_item(row: Dict[str, Any]) -> Dict[str, Any]:
    raw_status = row.get("status", "unknown")
    status = STATUS_MAP.get(raw_status, "unknown")
    return {
        "requirement": row.get("requirement_text", ""),
        "status": status,
        "reasoning": row.get("reasoning", ""),
        "evidence": build_evidence_list(row)
    }

def summarize_bucket(rows: List[Dict[str, Any]], status_filter: str) -> List[Dict[str, Any]]:
    items = []
    for row in rows:
        mapped_status = STATUS_MAP.get(row.get("status", "unknown"), "unknown")
        if mapped_status == status_filter:
            items.append({
                "requirement": row.get("requirement_text", ""),
                "reasoning": row.get("reasoning", ""),
                "evidence": build_evidence_list(row)
            })

    return items


# Weight assignment to evidences
def safe_priority_weight(priority: str) -> float:
    return PRIORITY_WEIGHTS.get((priority or "general").lower(), 1)

def vendor_score(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    weighted_score = 0.0
    counts = {
        "meets": 0,
        "partially_meets": 0,
        "does_not_meet": 0,
        "unknown": 0
    }
    mandatory_counts = {
        "meets": 0,
        "partially_meets": 0,
        "does_not_meet": 0,
        "unknown": 0
    }
    flag_counts = {
        "mandatory_requirement_failed": 0,
        "mandatory_requirement_unresolved": 0,
        "mandatory_requirement_not_fully_satisfied": 0
    }
    for row in rows:
        status = STATUS_MAP.get(row.get("status", "unknown"), "unknown")
        priority = (row.get("requirement_priority", "general") or "general").lower()
        weight = safe_priority_weight(priority)
        counts[status] += 1
        weighted_score += STATUS_SCORES[status] * weight
        if priority == "mandatory":
            mandatory_counts[status] += 1
        for flag in row.get("flags", []):
            if flag in flag_counts:
                flag_counts[flag] += 1

    return {
        "weighted_score": round(weighted_score, 2),
        "counts": counts,
        "mandatory_counts": mandatory_counts,
        "flag_counts": flag_counts
    }


def build_final_recommendation(vendor_rows: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    vendor_scores = {vendor: vendor_score(rows) for vendor, rows in vendor_rows.items()}
    sorted_vendors = sorted(
        vendor_scores.items(),
        key=lambda x: (
            x[1]["weighted_score"],
            x[1]["mandatory_counts"]["meets"],
            -x[1]["mandatory_counts"]["does_not_meet"],
            -x[1]["mandatory_counts"]["unknown"],
            x[1]["counts"]["meets"],
            -x[1]["counts"]["does_not_meet"]
        ),
        reverse=True
    )
    selected_vendor = sorted_vendors[0][0]
    selected_stats = sorted_vendors[0][1]
    tradeoffs = []
    for vendor, stats in vendor_scores.items():
        tradeoffs.append(
            f"{vendor}: "
            f"All Requirements(meets={stats['counts']['meets']}, "
            f"partial={stats['counts']['partially_meets']}, "
            f"failed={stats['counts']['does_not_meet']}, "
            f"unknown={stats['counts']['unknown']}), "
            f"Mandatory Requirements(meets={stats['mandatory_counts']['meets']}, "
            f"partial={stats['mandatory_counts']['partially_meets']}, "
            f"failed={stats['mandatory_counts']['does_not_meet']}, "
            f"unknown={stats['mandatory_counts']['unknown']}) "
        )
    justification = (
        f"{selected_vendor} is recommended because it achieved the strongest overall compliance profile "
        f"after weighting mandatory requirements more heavily. "
        f"It has a weighted score of {selected_stats['weighted_score']}, with "
        f"{selected_stats['mandatory_counts']['meets']} mandatory requirements fully met, "
        f"{selected_stats['mandatory_counts']['partially_meets']} partially met, "
        f"{selected_stats['mandatory_counts']['does_not_meet']} mandatory failures, and "
        f"{selected_stats['mandatory_counts']['unknown']} unresolved mandatory requirements."
    )
    return {
        "selected_vendor": selected_vendor,
        "justification": justification,
        "tradeoffs": tradeoffs
    }


# Main Function
def main():
    judgments = load_jsonl(JUDGMENTS_PATH)
    vendor_rows = defaultdict(list)
    for row in judgments:
        vendor = row.get("vendor", "UnknownVendor")
        vendor_rows[vendor].append(row)

    vendors_output = []
    for vendor_name in sorted(vendor_rows.keys()):
        rows = vendor_rows[vendor_name]
        requirements_analysis = [build_requirement_analysis_item(row) for row in rows]
        violations = summarize_bucket(rows, "does_not_meet")
        partial_compliance = summarize_bucket(rows, "partially_meets")
        unknowns = summarize_bucket(rows, "unknown")
        vendors_output.append({
            "name": vendor_name,
            "requirements_analysis": requirements_analysis,
            "violations": violations,
            "partial_compliance": partial_compliance,
            "unknowns": unknowns
        })
    final_output = {
        "vendors": vendors_output,
        "final_recommendation": build_final_recommendation(vendor_rows)
    }
    write_json(final_output, OUTPUT_PATH)
    print(f"Output JSON saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()