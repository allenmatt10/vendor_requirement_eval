# Leica Biosystems Second Round Task (Allen Mathews)

## Problem Statement

The goal of this assessment is to build a system that can read documents and compare them in a structured and systematic way. Given three documents (Company_Requirements_Full.pdf, Deskgenie_doc.pdf, AssistPro_doc.pdf), the objective is to produce a clear and traceable evaluation of the vendors.
The company document outlines the requirements for an AI helpdesk system, including areas such as security, logging, data deletion, performance, cost, and deployment expectations. The vendor documents describe the capabilities of AssistPro and DeskGenie in relation to these requirements.
The system is designed to answer five key questions:
- Does each vendor meet each requirement?
- Are there any violations?
- Is partial evidence good enough to support a requirement?
- What information is missing or unclear?
- Which vendor should be recommended overall?

To achieve this, A step-by-step pipeline is designed. Instead of treating the task as simple summarization, each requirement is treated as a query and search the vendor documents for supporting evidence. This approach ensures the results are structured, explainable, and easy to validate.

## Architecture

The architecture design is as follows:

1. **Document ingestion and text extraction:**

The first stage extracts text from the three source PDFs:
- Company requirement (Company_Requirements_Full.pdf)
- AssistPro vendor capabilities (Deskgenie_doc.pdf)
- DeskGenie vendor capabilities (AssistPro_doc.pdf)

This stage performs basic cleanup such as removing malformed PDF characters, normalizing whitespace, and preparing the content for section-based parsing.

2. **Structure-aware chunking:**

After extraction, documents are chunked by section headings rather than by arbitrary token windows. This was important because the source files already contain meaningful sections such as authentication, audit logging, data deletion, security, pricing, and deployment. Preserving those boundaries improves downstream interpretability and retrieval quality.
For the company document, headings such as Authentication and Access Control, Knowledge Ingestion, Audit Logging, Security Standards, Performance Requirements, Cost Constraints, and Deployment and Timeline provided natural logical units. For the vendor documents, sections such as Knowledge Base Integration, Authentication and Access, Data Protection, Audit Logging, Pricing and Plans, and Deployment served the same purpose.

3. **Atomic requirement decomposition:**

One of the main challenges in this assignment was that many company requirements were written as bundled, multi-clause statements. For example, a single requirement could include format support, document processing, structured extraction, and dynamic knowledge base updates. Similarly, security requirements often combined encryption, access control, and audit expectations into one statement.
To improve evaluation quality, I decomposed these into atomic requirement records using the Ollama. Each atomic record represents a single, independently evaluable condition. This helped avoid overusing “unknown” in cases where a vendor satisfied only part of a bundled requirement.
During this process, I preserved key metadata fields such as:
- source
- section
- requirement text
- requirement priority

This step resulted in a structured JSONL requirements layer that could be used for evaluation in the later stages.


4. **Vendor capability normalization:**

The AssistPro and DeskGenie documents were also transformed into structured JSONL records, but at the level of vendor capability claims rather than requirements. Each record contained:
- vendor name
- vendor capability ID
- source file
- source section
- claim text

The goal of this stage was to convert narrative vendor descriptions into retrievable evidence units while preserving section context for traceability.


5. **Retreival - Requirement to Vendor:**

Once both sides were normalized, the next stage treated each company requirement as a retrieval query and each vendor claim as a candidate evidence item.
Sentence embeddings was used to compare:
- requirement text
- vendor claim text
- associated section information

For each requirement, the system retrieved the top matching claims separately for AssistPro and DeskGenie. This created one requirement-to-vendor evidence record per vendor, rather than choosing a single best match across both vendors. That distinction was important because the task is to compare the evaluations, rather than any kind of Q&A generations.

The retrieval output included:
- matched vendor capability IDs
- matched claim texts
- similarity scores
- retrieval confidence indicators
- section and source provenance

6. **Rule-based compliance judgment:**

The retrieved evidence was then passed into a judgment layer that classifies each requirement-vendor pair into one of four status required in this assignment:
- `meets`
- `partially_meets`
- `does_not_meet`
- `unknown`

This stage used a combination of:
- retrieval strength
- lexical overlap between requirement and evidence
- support/limitation heuristics
- requirement-specific override logic for hard constraints

For example:
- A '45–60 day deletion timeline' conflicts with a '30-day requirement' and should be marked as `does_not_meet`
- support that exists only in enterprise or higher-tier plans is usually `partially_meets`
- general pricing language without concrete numbers results in `unknown`
- direct support with strong alignment becomes `meets`

This design helped distinguish true compliance gaps from incomplete documentation.

7. **Evidence-backed output generation:**

For every requirement-vendor pair, the system generated:
- requirement text
- vendor name
- status
- reasoning
- evidence snippets with source traceability

This intermediate layer was then aggregated into the final assignment format for each vendor:
- `requirements_analysis`
- `violations`
- `partial_compliance`
- `unknowns`

8. **Final recommendation engine:**

The final recommendation was based on aggregate vendor performance, with heavier emphasis on high-priority or mandatory requirements. This mattered because the company explicitly notes that systems failing mandatory requirements may be rejected unless mitigations are available.

The recommendation logic therefore considered:

- mandatory requirement outcomes
- number of clear violations
- number of partial matches
- unresolved unknowns in critical areas
- overall compliance profile

This produced a final selected vendor, a justification, and a set of tradeoffs.


## Design Decision

1. **Section-based chunking:** Documents are split based on section headings rather than fixed size chunks. This preserves the original structure and improves traceability, making it easier to map results back to the source.
2. **Atomic decomposition of requirements:** Many company requirements contain multiple conditions within a single sentence. These are decomposed into smaller, independently evaluable requirements. This improves accuracy and reduces overuse of unknown classifications.
3. **LLM-assisted requirement splitting:** An LLM (via Ollama) is used to semantically split company requirements into atomic units. This approach handles complex, multi-clause sentences more effectively than rule-based methods. Vendor documents are processed using rule-based splitting to preserve original wording and avoid unintended modifications.
4. **Retrieval-based matching:** Each requirement is treated as a query and matched against vendor claims using embedding-based similarity. This ensures that evaluation is grounded in actual vendor documentation.
5. **Hybrid evaluation approach:** A combination of semantic similarity and rule-based heuristics is used. Embeddings capture overall meaning, while rules help detect specific conditions such as constraints, qualifiers, and limitations.
6. **Evidence-driven judgment:** All compliance decisions (`meets`, `partially_meets`, `does_not_meet`, `unknown`) are based on retrieved evidence. Each result includes supporting snippets, ensuring transparency and verifiability.
7. **Priority-aware recommendation:** Requirements are weighted by priority during final evaluation. Mandatory requirements have a greater impact on the recommendation, aligning the decision process with real-world evaluation criteria.

## Execution Flow
1. The documents are first analysed and chunked from the directory `/problem_statement` by running `doc_chunking_v3.py`
2. Run `vector_matching_v2.py` for retreival based matching. The JSON result is stored in the directory `/new` as `requirement_vendor_matches.jsonl`
3. Run `status_generator_v2.py` to evaluate and map judgements. The JSON result is stored in the directory `/new` as `requirement_vendor_judgements.jsonl`
4. Run `final_json_v2.py` for the final JSON which compares the two vendors. The JSON result is stored in the directory `/new` as `final_vendor_evaluation.jsonl`

## Limitations

1. **High number of “unknown” classifications:**
A significant number of requirements are classified as unknown, even when related evidence exists. This occurs when vendor documentation is vague or does not explicitly confirm specific constraints. As a result, the system is conservative and avoids over-claiming compliance.
2. **Over-fragmentation due to atomic splitting:**
While atomic decomposition improves precision, it also leads to fragmented requirements. These fragments lack full context, making it harder for the system to confidently match them with vendor evidence, which increases unknown outcomes.
3. **Limited semantic understanding of constraints:**
The system relies on similarity scores and heuristic rules, which may miss nuanced constraints. For example:
“acceptable enterprise thresholds” is not interpreted as meeting “2 seconds response time”
“encryption at rest and in transit” is not always confidently mapped to individual requirements
This leads to under-classification of valid matches.
4. **Dependency on vendor documentation quality:**
The system can only evaluate what is explicitly stated in vendor documents. Missing or incomplete descriptions (e.g., pricing details, audit depth, deletion guarantees) directly result in unknown classifications, even if the capability may exist in reality.


#### Overall Comparison

| Metric               | AssistPro | DeskGenie |
|---------------------|-----------|-----------|
| Meets               | 13        | 6         |
| Partially Meets     | 11        | 18        |
| Does Not Meet       | 0         | 4         |
| Unknown             | 19        | 15        |
| Total Requirements  | 43        | 43        |

#### Mandatory Requirements Focus

| Metric               | AssistPro | DeskGenie |
|---------------------|-----------|-----------|
| Meets               | 2         | 1         |
| Partially Meets     | 1         | 1         |
| Does Not Meet       | 0         | 1         |
| Unknown             | 2         | 2         |

## Future Improvements

1. **Improve requirement splitting:**
Atomic splitting can be refined to avoid breaking requirements into very small or incomplete fragments. Keeping related clauses together would help improve matching and reduce unknown results.
2. **Add more metadata:**
Including metadata such as requirement type, key terms (e.g. okta, encryption, logging, ingestion, retension), and constraints (e.g., 30 days, 2 seconds) can improve retrieval and matching accuracy.
3. **Combine multiple pieces of evidence:**
Instead of relying on only the top few matches, combining multiple relevant vendor claims can give a more complete picture and reduce uncertainty.
4. **Handle vague vendor language better:**
To improve how the system interprets unclear phrases like “enterprise grade” or “acceptable thresholds” so they can be better aligned with specific requirements.

## Conclusion

This assessment presents a structured way to evaluate vendor compliance using document processing, retrieval, and rule-based reasoning. The system produces clear, evidence-backed results for each requirement and supports a final recommendation. The results show that AssistPro has stronger overall compliance, but also highlight challenges such as incomplete documentation and uncertainty in some areas. With improvements in requirement structuring and evidence handling, the system can become more accurate and reliable.
