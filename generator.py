import os
import uuid
import random
import traceback
from datetime import datetime, timedelta

# Force mock LLM mode for speed and deterministic failure tracing during generation
os.environ["USE_MOCK_LLM"] = "true"

import db
import tracer
import pipeline
import analyzer

# Setup folders
TRACES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traces")
os.makedirs(TRACES_DIR, exist_ok=True)

# Templates for document generation
VENDORS = ["Global Logistics Inc", "Tech Solutions Ltd", "Office Depot", "Amazon Business", "WeWork", "Starbucks", "Delta Airlines", "Digital Ocean", "Zoom Video Communications", "H&M Wholesale"]
ITEMS = [
    ("Monthly Subscription Fee", 15.00),
    ("Consulting Services - Architecture Review", 1250.00),
    ("Ergonomic Office Chair", 350.00),
    ("Keyboard and Mouse Combo", 85.00),
    ("Hot Desk Booking - 5 Days", 150.00),
    ("Coffee & Pastries Catering", 45.50),
    ("Flight Ticket - NY to SF", 420.00),
    ("Cloud Server Instance - Droplet 4GB", 24.00),
    ("Zoom Pro annual license", 149.90),
    ("Bulk Copier Paper", 62.10)
]

def generate_invoice(doc_num, fail_type=None):
    vendor = random.choice(VENDORS)
    inv_num = f"INV-2026-{doc_num:03d}"
    days_ago = random.randint(1, 30)
    date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    
    # Choose items
    item_list = random.sample(ITEMS, random.randint(1, 3))
    lines = []
    total = 0.0
    for it, price in item_list:
        lines.append(f"- {it}: ${price:.2f}")
        total += price
        
    doc_text = f"""
    INVOICE
    -----------------------------
    Invoice Number: {inv_num}
    Date: {date}
    Vendor: {vendor}
    
    Items:
    """ + "\n".join(lines) + f"\n\nTotal Amount Due: ${total:.2f}\n-----------------------------\nPlease remit payment to {vendor} within 30 days."
    
    if fail_type == "FAIL_EXTRACTION_HALLUCINATION":
        # Inject hallucination trigger
        doc_text += "\nFAIL_EXTRACTION_HALLUCINATION: The invoice sum total is correct, but the LLM should extract an inflated total value."
    elif fail_type == "FAIL_EXTRACTION_MISSING":
        # Strip vendor and date details
        doc_text = doc_text.replace(f"Vendor: {vendor}", "Vendor: ")
        doc_text = doc_text.replace(f"Date: {date}", "Date: [ILLEGIBLE]")
        doc_text += "\nFAIL_EXTRACTION_MISSING: The critical vendor and date fields are missing/unreadable."
    elif fail_type == "FAIL_CONTEXT_LOSS":
        doc_text += "\nFAIL_CONTEXT_LOSS: Trigger summary quality drop."
        
    return doc_text

def generate_receipt(doc_num):
    vendor = random.choice(["Starbucks", "McDonalds", "Shell Fuel Station", "Walmart", "Subway"])
    days_ago = random.randint(1, 30)
    date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    amount = random.uniform(5.50, 75.00)
    
    doc_text = f"""
    RECEIPT
    -----------------------------
    Store: {vendor}
    Date: {date}
    Transaction Ref: TXN-{random.randint(100000, 999999)}
    
    Card Payment: **** **** **** 4321
    Amount: ${amount:.2f}
    
    Thank you for your business!
    """
    return doc_text

def generate_purchase_order(doc_num, fail_type=None):
    vendor = random.choice(VENDORS)
    po_num = f"PO-9988-{doc_num:03d}"
    date = datetime.now().strftime("%Y-%m-%d")
    item_list = random.sample(ITEMS, 1)
    it, price = item_list[0]
    total = price * 5
    
    doc_text = f"""
    PURCHASE ORDER
    -----------------------------
    PO Number: {po_num}
    Date: {date}
    To Vendor: {vendor}
    Please deliver: 5x {it} @ ${price:.2f} each.
    
    Approved Total: ${total:.2f}
    Bill to: Acme Finance Dept
    """
    
    if fail_type == "FAIL_MISCLASSIFY":
        doc_text += "\nFAIL_MISCLASSIFY: This document has a Purchase Order header but represents a Support request to change invoicing email addresses."
        doc_text += "\nFrom: billing@acme.com. Please route this to support. We need to update our email."
        
    return doc_text

def generate_ticket(doc_num):
    users = ["alice@acme.com", "bob@tech.com", "charlie@logistics.com"]
    user = random.choice(users)
    
    doc_text = f"""
    SUPPORT TICKET
    -----------------------------
    Ticket ID: TKT-{doc_num:03d}
    From: {user}
    Subject: Login issues with billing dashboard
    
    Hi support team, I'm having trouble logging in to view my invoices since yesterday. It keeps showing a 403 Forbidden error. Please reset my password or check my permissions.
    
    Thanks,
    User
    """
    return doc_text

def generate_corrupt_doc():
    return "FAIL_INTAKE_CRASH: Document contains unreadable binary segments and is corrupt."

def build_and_run_dataset():
    print("Initializing Failure Forensics Tool Database...")
    db.init_db()
    
    print("\nStarting generation of 50 documents...")
    
    # Pre-select where we inject failures (total ~9 failures)
    failure_indices = {
        5: "FAIL_INTAKE_CRASH",
        12: "FAIL_EXTRACTION_HALLUCINATION",
        18: "FAIL_EXTRACTION_MISSING",
        24: "FAIL_MISCLASSIFY",
        30: "FAIL_CONTEXT_LOSS",
        35: "FAIL_EXTRACTION_HALLUCINATION",
        41: "FAIL_EXTRACTION_MISSING",
        47: "FAIL_MISCLASSIFY",
        49: "FAIL_INTAKE_CRASH"
    }
    
    success_count = 0
    failure_count = 0
    
    for i in range(1, 51):
        trace_id = f"trace_{uuid.uuid4().hex}"
        doc_type = ""
        doc_text = ""
        
        # Determine what type of document to generate
        fail_type = failure_indices.get(i)
        
        if fail_type == "FAIL_INTAKE_CRASH":
            doc_text = generate_corrupt_doc()
            doc_type = "Corrupted Doc"
        elif fail_type in ["FAIL_EXTRACTION_HALLUCINATION", "FAIL_EXTRACTION_MISSING", "FAIL_CONTEXT_LOSS"]:
            doc_text = generate_invoice(i, fail_type)
            doc_type = "Invoice"
        elif fail_type == "FAIL_MISCLASSIFY":
            doc_text = generate_purchase_order(i, fail_type)
            doc_type = "Purchase Order"
        elif i % 4 == 1:
            doc_text = generate_invoice(i)
            doc_type = "Invoice"
        elif i % 4 == 2:
            doc_text = generate_receipt(i)
            doc_type = "Receipt"
        elif i % 4 == 3:
            doc_text = generate_purchase_order(i)
            doc_type = "Purchase Order"
        else:
            doc_text = generate_ticket(i)
            doc_type = "Support Ticket"
            
        print(f"[{i:02d}/50] Processing {doc_type} (Injection: {fail_type or 'None'})... ", end="")
        
        try:
            tracer.run_with_trace(trace_id, doc_text, pipeline.run_pipeline)
            
            # Fetch trace details to check if any step reported a low confidence score
            trace_details = db.get_trace_details(trace_id)
            has_soft_failure = False
            for span in trace_details["spans"]:
                if span["confidence"] is not None and span["confidence"] <= 2:
                    has_soft_failure = True
                    break
                    
            if has_soft_failure or fail_type:
                # Run analyzer for forensics analysis
                analysis = analyzer.analyze_trace_forensics(trace_id)
                diagnosis = analysis["diagnosis"]
                print(f"SOFT FAIL - Forensics Ran. Root Cause: {diagnosis['root_cause_type']} ({diagnosis['root_cause_step']})")
                failure_count += 1
            else:
                print("SUCCESS")
                success_count += 1
                
        except Exception as e:
            # Handle hard failure (Intake Crash)
            print(f"HARD FAIL - Exception Raised. Running Forensics... ", end="")
            try:
                analysis = analyzer.analyze_trace_forensics(trace_id)
                diagnosis = analysis["diagnosis"]
                print(f"Root Cause: {diagnosis['root_cause_type']} ({diagnosis['root_cause_step']})")
            except Exception as fe:
                print(f"Forensics Error: {fe}")
            failure_count += 1
            
    print("\n=========================================")
    print(f"Dataset Processing Completed!")
    print(f"Total Traces Saved: 50")
    print(f"  - Healthy Traces: {success_count}")
    print(f"  - Failed/Flagged Traces: {failure_count}")
    print("=========================================")

if __name__ == "__main__":
    build_and_run_dataset()
