import os
import json
import re
import random
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from tracer import trace_step

# Configure Hugging Face settings
HF_TOKEN = os.environ.get("HF_TOKEN", "")
# If the environment variable USE_MOCK_LLM is set to 'true', we bypass Hugging Face
USE_MOCK_LLM = os.environ.get("USE_MOCK_LLM", "false").lower() == "true"

# Define Pydantic Models for Pipeline Steps

class IntakeInput(BaseModel):
    raw_text: str

class IntakeOutput(BaseModel):
    sanitized_text: str
    metadata: Dict[str, Any]
    status: str

class ExtractionInput(BaseModel):
    text: str

class ExtractionOutput(BaseModel):
    vendor: str
    invoice_date: str
    amount: float
    currency: str
    line_items: List[str]
    confidence: int = Field(..., ge=1, le=5)
    reasoning: str

class ClassificationInput(BaseModel):
    text: str
    extracted_fields: Dict[str, Any]

class ClassificationOutput(BaseModel):
    category: str  # e.g., Invoice, Receipt, Purchase Order, Support Ticket, Unknown
    confidence: int = Field(..., ge=1, le=5)
    reasoning: str

class SummarizationInput(BaseModel):
    text: str
    extracted_fields: Dict[str, Any]
    category: str

class SummarizationOutput(BaseModel):
    summary: str
    action_items: List[str]
    confidence: int = Field(..., ge=1, le=5)

# LLM Inference Helper with robust fallbacks
def call_llm(prompt: str, system_prompt: str, model: str = None) -> tuple[str, int]:
    """Calls Hugging Face Inference API. Falls back to other models if needed.
    If USE_MOCK_LLM is True, runs mock generation."""
    if USE_MOCK_LLM:
        return run_mock_llm(prompt, system_prompt)
        
    models_to_try = []
    if model:
        models_to_try.append(model)
        
    models_to_try.extend([
        "Qwen/Qwen2.5-7B-Instruct",
        "Qwen/Qwen2.5-72B-Instruct",
        "meta-llama/Llama-3.3-70B-Instruct",
        "meta-llama/Meta-Llama-3-8B-Instruct",
        "THUDM/glm-4-9b-chat"
    ])
    
    from huggingface_hub import InferenceClient
    
    last_error = None
    for m in models_to_try:
        try:
            client = InferenceClient(model=m, token=HF_TOKEN)
            response = client.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=800,
                temperature=0.1
            )
            content = response.choices[0].message.content
            # Approximate token counts
            prompt_tokens = len(prompt.split()) + len(system_prompt.split()) + 20
            output_tokens = len(content.split())
            return content, prompt_tokens + output_tokens
        except Exception as e:
            last_error = e
            continue
            
    print(f"Hugging Face API failed: {last_error}. Falling back to Mock LLM.")
    return run_mock_llm(prompt, system_prompt)

def clean_json_response(raw_text: str) -> str:
    """Cleans markdown JSON blocks and extra text around JSON response."""
    # Find ```json ... ``` block
    match = re.search(r"```json\s*(.*?)\s*```", raw_text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
        
    # Find first '{' and last '}'
    start = raw_text.find('{')
    end = raw_text.rfind('}')
    if start != -1 and end != -1 and end > start:
        return raw_text[start:end+1].strip()
        
    return raw_text.strip()

# Mock LLM Engine for robustness and testing
def run_mock_llm(prompt: str, system_prompt: str) -> tuple[str, int]:
    """Generates structured mock outputs based on prompt contents."""
    # Extract any context fields from prompt
    text_match = re.search(r"Source Text:\s*(.*?)(?:\n\n|\Z)", prompt, re.DOTALL | re.IGNORECASE)
    text_content = text_match.group(1) if text_match else prompt
    
    # Setup default values
    vendor = "Acme Corp"
    amount = 150.00
    currency = "USD"
    date_str = "2026-06-25"
    items = ["Services Rendered"]
    
    # Try regex matching to extract fields
    if "Vendor:" in text_content:
        v_m = re.search(r"Vendor:\s*([^\n]+)", text_content)
        if v_m: vendor = v_m.group(1).strip()
    if "Total:" in text_content or "Amount:" in text_content:
        a_m = re.search(r"(?:Total|Amount):\s*(?:[\$\€\£])?\s*([\d\.,]+)", text_content)
        if a_m:
            try: amount = float(a_m.group(1).replace(",", ""))
            except: pass
    if "Date:" in text_content:
        d_m = re.search(r"Date:\s*([^\n]+)", text_content)
        if d_m: date_str = d_m.group(1).strip()
        
    # Determine type of mock response to output based on the system prompt instruction
    tokens = len(prompt.split()) // 3 + 100
    
    if "ExtractionOutput" in prompt or "extract" in system_prompt.lower():
        # Extraction output requested
        # Check for failure triggers
        confidence = 5
        reasoning = "Fields successfully extracted using semantic matching."
        
        if "FAIL_EXTRACTION_HALLUCINATION" in text_content:
            # Hallucinate: total amount is wrong
            amount = amount * 10 # 10x amount
            confidence = 2
            reasoning = "Extracted total amount from summary line but line items do not sum up correctly."
        elif "FAIL_EXTRACTION_MISSING" in text_content:
            vendor = "N/A"
            date_str = "N/A"
            confidence = 1
            reasoning = "Missing critical fields like vendor name and invoice date."
            
        data = {
            "vendor": vendor,
            "invoice_date": date_str,
            "amount": amount,
            "currency": currency,
            "line_items": items,
            "confidence": confidence,
            "reasoning": reasoning
        }
        return json.dumps(data), tokens
        
    elif "ClassificationOutput" in prompt or "classify" in system_prompt.lower():
        category = "Invoice"
        confidence = 5
        reasoning = "Contains clear layout with vendor, line items, and total amount payable."
        
        if "FAIL_MISCLASSIFY" in text_content:
            # Force misclassification
            category = "Support Ticket"
            confidence = 2
            reasoning = "Classified as Support Ticket due to the email format request."
        elif "PO" in text_content or "Purchase Order" in text_content:
            category = "Purchase Order"
        elif "Receipt" in text_content:
            category = "Receipt"
            
        data = {
            "category": category,
            "confidence": confidence,
            "reasoning": reasoning
        }
        return json.dumps(data), tokens
        
    elif "SummarizationOutput" in prompt or "summarize" in system_prompt.lower():
        summary_text = f"Executive summary of document from {vendor}."
        action_items = [f"Process payment of {currency} {amount}."]
        confidence = 5
        
        # Check for propagation errors
        extracted_fields_match = re.search(r"Extracted Fields:\s*(.*?)(?:\n\n|\Z)", prompt, re.DOTALL)
        extracted_fields = {}
        if extracted_fields_match:
            try: extracted_fields = json.loads(extracted_fields_match.group(1))
            except: pass
            
        # Check if the extraction step was wrong
        if extracted_fields.get("amount", 0) > 1000 and "FAIL_EXTRACTION_HALLUCINATION" in text_content:
            # Propagation error: summarization uses the bad amount
            summary_text = f"Urgent review required: High-value invoice from {vendor} with total of {currency} {extracted_fields.get('amount')}."
            action_items = [f"Verify charges immediately. Large amount mismatch expected."]
            confidence = 3
        elif "FAIL_CONTEXT_LOSS" in text_content:
            # Incomplete summary
            summary_text = "Document summary."
            action_items = []
            confidence = 2
            
        data = {
            "summary": summary_text,
            "action_items": action_items,
            "confidence": confidence
        }
        return json.dumps(data), tokens
        
    elif "quality judge" in prompt.lower() or "evaluate" in system_prompt.lower():
        # LLM-as-Judge span evaluation
        step_match = re.search(r"step named '([^']+)'", prompt)
        step_name = step_match.group(1) if step_match else "Unknown"
        
        score = 5
        is_propagation = False
        explanation = "Step output is correct and complete based on its inputs."
        
        # Check for failure triggers
        if "FAIL_INTAKE_CRASH" in prompt:
            score = 1
            explanation = "Intake step crashed or failed to parse corrupted data."
        elif "FAIL_EXTRACTION_HALLUCINATION" in prompt:
            if step_name == "Extraction":
                score = 2
                explanation = "Extraction step hallucinated an amount 10x larger than the sum of the line items."
            elif step_name in ["Classification", "Summarization"]:
                score = 3
                is_propagation = True
                explanation = f"{step_name} step processed fields containing errors propagated from the Extraction step."
        elif "FAIL_EXTRACTION_MISSING" in prompt:
            if step_name == "Extraction":
                score = 2
                explanation = "Extraction step failed to identify critical vendor name and date fields."
            elif step_name in ["Classification", "Summarization"]:
                score = 3
                is_propagation = True
                explanation = f"{step_name} step received incomplete fields (N/A) from the Extraction step."
        elif "FAIL_MISCLASSIFY" in prompt:
            if step_name == "Classification":
                score = 2
                explanation = "Classification step misclassified a Purchase Order as a Support Ticket due to the email format request."
            elif step_name == "Summarization":
                score = 3
                is_propagation = True
                explanation = "Summarization step summarized the document based on the incorrect category (Support Ticket)."
        elif "FAIL_CONTEXT_LOSS" in prompt:
            if step_name == "Summarization":
                score = 2
                explanation = "Summarization step failed to capture required payment deadlines and action items."
                
        data = {
            "score": score,
            "is_propagation": is_propagation,
            "explanation": explanation
        }
        return json.dumps(data), tokens
        
    elif "diagnose" in prompt.lower() or "diagnose" in system_prompt.lower() or "failure forensics" in prompt.lower():
        # LLM Root Cause Diagnosis
        root_cause_step = "Unknown"
        root_cause_type = "Unknown"
        explanation = "No failure triggers detected."
        
        if "FAIL_INTAKE_CRASH" in prompt:
            root_cause_step = "Intake"
            root_cause_type = "Prompt Failure"
            explanation = "Intake step crashed due to database read/parse corruption error."
        elif "FAIL_EXTRACTION_HALLUCINATION" in prompt:
            root_cause_step = "Extraction"
            root_cause_type = "Extraction Hallucination"
            explanation = "Extraction step hallucinated an incorrect amount (10x higher) which was subsequently propagated downstream to the summarization step."
        elif "FAIL_EXTRACTION_MISSING" in prompt:
            root_cause_step = "Extraction"
            root_cause_type = "Extraction Hallucination"
            explanation = "Extraction step failed to capture required fields (vendor name and invoice date) from the ambiguous document structure."
        elif "FAIL_MISCLASSIFY" in prompt:
            root_cause_step = "Classification"
            root_cause_type = "Misclassification"
            explanation = "Classification step misclassified a Purchase Order document as a Support Ticket because it contained email-like requests."
        elif "FAIL_CONTEXT_LOSS" in prompt:
            root_cause_step = "Summarization"
            root_cause_type = "Context Loss"
            explanation = "Summarization step failed to list key action items and payment deadlines, leading to context loss."
            
        data = {
            "root_cause_step": root_cause_step,
            "root_cause_type": root_cause_type,
            "explanation": explanation
        }
        return json.dumps(data), tokens
        
    # Default fallback
    return '{"status": "ok"}', tokens

# ----------------- PIPELINE STEP FUNCTIONS -----------------

@trace_step("Intake")
def step_intake(input_data: IntakeInput) -> IntakeOutput:
    text = input_data.raw_text
    
    # Failure Injection check
    if not text.strip():
        raise ValueError("Intake step failed: Document text is empty or unreadable.")
    if "FAIL_INTAKE_CRASH" in text:
        raise ValueError("Intake step encountered database read/parse corruption error.")
        
    # Clean up double spacing and trailing newlines
    sanitized = re.sub(r'\s+', ' ', text).strip()
    
    # Basic metadata extraction
    metadata = {
        "char_count": len(text),
        "word_count": len(text.split()),
        "has_numbers": any(c.isdigit() for c in text),
        "source": "api_upload"
    }
    
    return IntakeOutput(
        sanitized_text=sanitized,
        metadata=metadata,
        status="SUCCESS"
    )

@trace_step("Extraction")
def step_extraction(input_data: ExtractionInput) -> ExtractionOutput:
    prompt = f"""
    You are an expert OCR and document data extractor. Extract key details from the source document.
    You must output a raw JSON object matching the JSON schema below. Do not wrap in extra commentary or text.
    
    Schema:
    {{
        "vendor": "Name of the merchant/vendor or 'Unknown'",
        "invoice_date": "Date formatted as YYYY-MM-DD or 'Unknown'",
        "amount": 0.00,
        "currency": "3-letter currency code (e.g. USD, EUR) or 'Unknown'",
        "line_items": ["item description 1", "item description 2"],
        "confidence": 1-5 (5 being extremely confident, 1 being complete guess),
        "reasoning": "Brief explanation of why you set this confidence level"
    }}
    
    Source Text:
    {input_data.text}
    """
    
    system_prompt = "You extract structured invoice details. You only output valid JSON matching the schema."
    
    raw_response, tokens = call_llm(prompt, system_prompt)
    cleaned = clean_json_response(raw_response)
    
    try:
        data = json.loads(cleaned)
        # Parse into Pydantic
        output = ExtractionOutput(**data)
    except Exception as e:
        # Create a low-confidence error-mitigated object to represent a parsing/prompt failure
        output = ExtractionOutput(
            vendor="Unknown",
            invoice_date="Unknown",
            amount=0.0,
            currency="Unknown",
            line_items=[],
            confidence=1,
            reasoning=f"LLM output parsing failed: {str(e)}. Raw: {cleaned}"
        )
        
    # Attach LLM metadata for the tracer to capture
    output_dict = output.dict()
    output_dict["_prompt"] = prompt
    output_dict["_raw_response"] = raw_response
    output_dict["_tokens_used"] = tokens
    
    # Re-wrap in Pydantic with attributes attached so tracer decorator can read them
    class ExtendedExtractionOutput(ExtractionOutput):
        _prompt: str = prompt
        _raw_response: str = raw_response
        _tokens_used: int = tokens
        
    return ExtendedExtractionOutput(**output_dict)

@trace_step("Classification")
def step_classification(input_data: ClassificationInput) -> ClassificationOutput:
    prompt = f"""
    You are a document classifier. Determine the category of the document based on its text and extracted fields.
    You must output a raw JSON object matching the JSON schema below. Do not wrap in extra text.
    
    Schema:
    {{
        "category": "Invoice", "Receipt", "Purchase Order", "Contract", or "Unknown",
        "confidence": 1-5,
        "reasoning": "Reason for this classification"
    }}
    
    Source Text:
    {input_data.text}
    
    Extracted Fields:
    {json.dumps(input_data.extracted_fields)}
    """
    
    system_prompt = "You classify documents. You only output valid JSON matching the schema."
    
    raw_response, tokens = call_llm(prompt, system_prompt)
    cleaned = clean_json_response(raw_response)
    
    try:
        data = json.loads(cleaned)
        output = ClassificationOutput(**data)
    except Exception as e:
        output = ClassificationOutput(
            category="Unknown",
            confidence=1,
            reasoning=f"Classification LLM response parsing failed: {str(e)}."
        )
        
    output_dict = output.dict()
    output_dict["_prompt"] = prompt
    output_dict["_raw_response"] = raw_response
    output_dict["_tokens_used"] = tokens
    
    class ExtendedClassificationOutput(ClassificationOutput):
        _prompt: str = prompt
        _raw_response: str = raw_response
        _tokens_used: int = tokens
        
    return ExtendedClassificationOutput(**output_dict)

@trace_step("Summarization")
def step_summarization(input_data: SummarizationInput) -> SummarizationOutput:
    prompt = f"""
    Summarize the document and list all required action items (e.g. payment deadlines, approvals, signatures).
    You must output a raw JSON object matching the JSON schema below. Do not wrap in extra text.
    
    Schema:
    {{
        "summary": "Short 2-3 sentence executive summary",
        "action_items": ["Action item 1", "Action item 2"],
        "confidence": 1-5
    }}
    
    Source Text:
    {input_data.text}
    
    Document Category:
    {input_data.category}
    
    Extracted Fields:
    {json.dumps(input_data.extracted_fields)}
    """
    
    system_prompt = "You summarize documents. You only output valid JSON matching the schema."
    
    raw_response, tokens = call_llm(prompt, system_prompt)
    cleaned = clean_json_response(raw_response)
    
    try:
        data = json.loads(cleaned)
        output = SummarizationOutput(**data)
    except Exception as e:
        output = SummarizationOutput(
            summary="Failed to generate summary.",
            action_items=[],
            confidence=1
        )
        
    output_dict = output.dict()
    output_dict["_prompt"] = prompt
    output_dict["_raw_response"] = raw_response
    output_dict["_tokens_used"] = tokens
    
    class ExtendedSummarizationOutput(SummarizationOutput):
        _prompt: str = prompt
        _raw_response: str = raw_response
        _tokens_used: int = tokens
        
    return ExtendedSummarizationOutput(**output_dict)

# ----------------- MAIN PIPELINE RUNNER -----------------

def run_pipeline(raw_text: str) -> Dict[str, Any]:
    """Runs the 4-step pipeline sequentially."""
    # Step 1: Intake
    intake_in = IntakeInput(raw_text=raw_text)
    intake_out = step_intake(intake_in)
    
    # Step 2: Extraction
    extract_in = ExtractionInput(text=intake_out.sanitized_text)
    extract_out = step_extraction(extract_in)
    
    # Step 3: Classification
    class_in = ClassificationInput(
        text=intake_out.sanitized_text,
        extracted_fields=extract_out.dict()
    )
    class_out = step_classification(class_in)
    
    # Step 4: Summarization
    sum_in = SummarizationInput(
        text=intake_out.sanitized_text,
        extracted_fields=extract_out.dict(),
        category=class_out.category
    )
    sum_out = step_summarization(sum_in)
    
    return {
        "intake": intake_out.dict(),
        "extraction": extract_out.dict(),
        "classification": class_out.dict(),
        "summarization": sum_out.dict()
    }
