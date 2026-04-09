import re
import json
import requests
from pathlib import Path
from typing import List, Dict, Any

from pypdf import PdfReader


# Paths
INPUT_FILES = {
    "company": "problem_statement/Company_Requirements_Full.pdf",
    "assistpro": "problem_statement/AssistPro_doc.pdf",
    "deskgenie": "problem_statement/Deskgenie_doc.pdf",
}

OUTPUT_FILES = {
    "company": "new/company_requirements.jsonl",
    "assistpro": "new/assistpro_capabilities.jsonl",
    "deskgenie": "new/deskgenie_capabilities.jsonl",
}

# Configurations
USE_OLLAMA_FOR_COMPANY = True # here, we are only splitting the company requirements for atomic representations
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3"
OLLAMA_TIMEOUT = 120

# Save chunks after splitting
def save_jsonl(records: List[Dict[str, str]], path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

# PDF parsing and cleaning
def extract_pdf_text(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)

    return "\n".join(pages)

def clean_text(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = text.replace("\uf0b7", "•")
    text = text.replace("￾", "")
    text = text.replace("–", "-")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Section headings matching and cleaning
def is_heading(line: str) -> bool:
    line = line.strip()
    patterns = [
        r"^\d+\s+[A-Z].*",
        r"^\d+\.\d+\s+[A-Z].*",
        r"^\d+\.\d+\.\d+\s+[A-Z].*"
    ]
    return any(re.match(p, line) for p in patterns)

def clean_section_heading(heading: str) -> str:
    cleaned = re.sub(r"^\d+(\.\d+)*\s+", "", heading.strip())
    return cleaned

def chunk_by_headings(text: str) -> List[Dict[str, str]]:
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    chunks = []
    current_heading = "Document Start"
    current_lines = []
    for line in lines:
        if is_heading(line):
            if current_lines:
                chunks.append({
                    "heading": current_heading,
                    "text": " ".join(current_lines).strip()
                })
            current_heading = clean_section_heading(line)
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        chunks.append({
            "heading": current_heading,
            "text": " ".join(current_lines).strip()
        })
    return chunks

# This is used to avoid ireelevant section, such as introduction, conclusion, evaluation metrics for selection.
def is_relevant_section(heading: str, doc_type: str) -> bool:
    h = heading.lower()
    if "document start" in h:
        return False
    if any(k in h for k in ["introduction", "overview", "conclusion"]):
        return False
    if doc_type == "company":
        if "evaluation criteria" in h:
            return False
    return True


# Rule-Based splitting
def split_bullets(text: str) -> List[str]:
    text = re.sub(r"\s+•\s+", "\n• ", text)
    text = re.sub(r"\s+-\s+", "\n- ", text)
    parts = re.split(r"\n(?=[•-]\s)", text)
    parts = [p.strip("•- ").strip() for p in parts if p.strip()]
    if len(parts) <= 1:
        return [text.strip()]
    return parts

def split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip())
    return [p.strip() for p in parts if p.strip()]

def split_into_atomic(text: str) -> List[str]:
    bullet_parts = split_bullets(text)
    if len(bullet_parts) > 1:
        return bullet_parts
    sentences = split_sentences(text)
    if len(sentences) <= 2:
        return [text.strip()]
    chunks = []
    current = []
    for sent in sentences:
        current.append(sent)
        joined = " ".join(current)
        if len(joined.split()) >= 22:
            chunks.append(joined.strip())
            current = []

    if current:
        chunks.append(" ".join(current).strip())

    return chunks if chunks else [text.strip()]


# Using the Ollama endpoint for atomic splitting of company requirements
def extract_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    brace_match = re.search(r"(\{.*\})", text, flags=re.DOTALL)
    if brace_match:
        return json.loads(brace_match.group(1))
    raise ValueError("Could not parse JSON from Ollama response.")


def dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        cleaned = re.sub(r"\s+", " ", item).strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key not in seen:
            seen.add(key)
            result.append(cleaned)

    return result


def ollama_split_company_requirements(text: str, heading: str) -> List[str]:
    fallback = split_into_atomic(text)

    if not USE_OLLAMA_FOR_COMPANY:
        return fallback

    prompt = f"""
You are converting requirement text into atomic requirement records.

Task:
Split the input text into the smallest independently evaluable requirements.

Rules:
1. Preserve the original meaning exactly.
2. Do not add new information.
3. Keep important modal words like "must", "should", and "required".
4. If one sentence contains multiple independent requirements, split them.
5. Each output item must be a complete requirement sentence.
6. Do not explain anything.
7. Return only valid JSON.

Return format:
{{
  "atomic_requirements": [
    {{"requirement_text": "..."}},
    {{"requirement_text": "..."}}
  ]
}}

Section:
{heading}

Input text:
{text}
""".strip()

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json"
    }

    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        response_json = resp.json()
        raw_response = response_json.get("response", "").strip()
        parsed = extract_json_object(raw_response)
        items = parsed.get("atomic_requirements", [])
        atomic_texts = []
        for item in items:
            if isinstance(item, dict):
                value = item.get("requirement_text", "").strip()
                if value:
                    atomic_texts.append(value)

        atomic_texts = dedupe_preserve_order(atomic_texts)
        if not atomic_texts:
            return fallback

        return atomic_texts

    except Exception as e:
        print(f"[WARN] Ollama split failed for company section '{heading}': {e}")
        return fallback


# Inferring priority based on section headings
def infer_priority(heading: str, text: str) -> str:
    h = heading.lower()
    t = text.lower()

    if "mandatory requirements" in h:
        return "mandatory"

    if "functional requirements" in h:
        return "functional"

    if "compliance and security requirements" in h:
        return "compliance"

    if "performance requirements" in h:
        return "performance"

    if "cost constraints" in h:
        return "cost cap"

    if "deployment and timeline" in h:
        return "deployment"

    if any(k in t for k in [
        "improving employee satisfaction",
        "reducing operational overhead",
        "enabling analytics-driven decision-making"
    ]):
        return "secondary"

    return "general"


# Building company requirements and vendor capabilities
def build_company(section_chunks: List[Dict[str, str]], source: str) -> List[Dict[str, str]]:
    records = []
    counter = 1

    for chunk in section_chunks:
        if not is_relevant_section(chunk["heading"], "company"):
            continue

        items = ollama_split_company_requirements(
            text=chunk["text"],
            heading=chunk["heading"]
        )

        for item in items:
            item = item.strip()
            if not item:
                continue

            records.append({
                "requirement_id": f"REQ0{counter:03d}",
                "source": source,
                "section": chunk["heading"],
                "requirement_text": item,
                "priority": infer_priority(chunk["heading"], item)
            })
            counter += 1

    return records


def build_vendor(section_chunks: List[Dict[str, str]], source: str, vendor: str, prefix: str) -> List[Dict[str, str]]:
    records = []
    counter = 1

    for chunk in section_chunks:
        if not is_relevant_section(chunk["heading"], "vendor"):
            continue
        items = split_into_atomic(chunk["text"])
        for item in items:
            item = item.strip()
            if not item:
                continue

            records.append({
                "vendor": vendor,
                "vendor_cap_id": f"{prefix}0{counter:03d}",
                "source": source,
                "section": chunk["heading"],
                "claim_text": item
            })
            counter += 1

    return records

# Main Function
def process() -> None:
    # Company requirement splitting by API calls
    company_text = clean_text(extract_pdf_text(INPUT_FILES["company"]))
    company_chunks = chunk_by_headings(company_text)
    company_records = build_company(company_chunks, "Company_Requirements_Full")
    save_jsonl(company_records, OUTPUT_FILES["company"])

    # Vendor capabilities chunking using rule-based split
    assist_text = clean_text(extract_pdf_text(INPUT_FILES["assistpro"]))
    assist_chunks = chunk_by_headings(assist_text)
    assist_records = build_vendor(assist_chunks, "AssistPro_doc", "AssistPro", "ASP")
    save_jsonl(assist_records, OUTPUT_FILES["assistpro"])

    desk_text = clean_text(extract_pdf_text(INPUT_FILES["deskgenie"]))
    desk_chunks = chunk_by_headings(desk_text)
    desk_records = build_vendor(desk_chunks, "Deskgenie_doc", "DeskGenie", "DG")
    save_jsonl(desk_records, OUTPUT_FILES["deskgenie"])
    print("Chunking done. Json files are created!")

if __name__ == "__main__":
    process()