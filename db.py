import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forensics.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Traces table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS traces (
        trace_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        input_doc TEXT,
        final_output TEXT,
        error_message TEXT,
        root_cause_step TEXT,
        root_cause_type TEXT,
        root_cause_explanation TEXT,
        human_flagged INTEGER DEFAULT 0,
        human_category TEXT,
        human_notes TEXT,
        corrected_output TEXT
    )
    """)
    
    # Spans table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS spans (
        span_id TEXT PRIMARY KEY,
        trace_id TEXT NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL,
        start_time REAL NOT NULL,
        end_time REAL NOT NULL,
        latency REAL NOT NULL,
        input_data TEXT,
        output_data TEXT,
        prompt TEXT,
        raw_response TEXT,
        confidence INTEGER,
        tokens_used INTEGER,
        error_message TEXT,
        FOREIGN KEY (trace_id) REFERENCES traces (trace_id) ON DELETE CASCADE
    )
    """)
    
    # Eval cases table (for feedback loop)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS eval_cases (
        case_id TEXT PRIMARY KEY,
        trace_id TEXT,
        input_doc TEXT NOT NULL,
        failing_step TEXT NOT NULL,
        bad_output TEXT,
        corrected_output TEXT NOT NULL,
        category TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)
    
    conn.commit()
    conn.close()

def save_trace(trace_id, status, input_doc, final_output=None, error_message=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    created_at = datetime.utcnow().isoformat()
    cursor.execute("""
    INSERT INTO traces (trace_id, status, created_at, input_doc, final_output, error_message)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(trace_id) DO UPDATE SET
        status=excluded.status,
        final_output=excluded.final_output,
        error_message=excluded.error_message
    """, (trace_id, status, created_at, input_doc, final_output, error_message))
    conn.commit()
    conn.close()

def update_trace_root_cause(trace_id, root_cause_step, root_cause_type, root_cause_explanation):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE traces
    SET root_cause_step = ?, root_cause_type = ?, root_cause_explanation = ?
    WHERE trace_id = ?
    """, (root_cause_step, root_cause_type, root_cause_explanation, trace_id))
    conn.commit()
    conn.close()

def save_span(span_id, trace_id, name, status, start_time, end_time, latency, 
              input_data, output_data, prompt=None, raw_response=None, 
              confidence=None, tokens_used=None, error_message=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Convert input_data and output_data to JSON strings if they are dicts/lists
    if isinstance(input_data, (dict, list)):
        input_data = json.dumps(input_data)
    if isinstance(output_data, (dict, list)):
        output_data = json.dumps(output_data)
        
    cursor.execute("""
    INSERT INTO spans (span_id, trace_id, name, status, start_time, end_time, latency, 
                       input_data, output_data, prompt, raw_response, confidence, tokens_used, error_message)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(span_id) DO UPDATE SET
        status=excluded.status,
        end_time=excluded.end_time,
        latency=excluded.latency,
        output_data=excluded.output_data,
        raw_response=excluded.raw_response,
        confidence=excluded.confidence,
        tokens_used=excluded.tokens_used,
        error_message=excluded.error_message
    """, (span_id, trace_id, name, status, start_time, end_time, latency,
          input_data, output_data, prompt, raw_response, confidence, tokens_used, error_message))
    conn.commit()
    conn.close()

def flag_trace(trace_id, human_category, human_notes, corrected_output=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE traces
    SET human_flagged = 1,
        human_category = ?,
        human_notes = ?,
        corrected_output = ?
    WHERE trace_id = ?
    """, (human_category, human_notes, corrected_output, trace_id))
    
    # Fetch trace and spans to create an eval case
    cursor.execute("SELECT input_doc, final_output, root_cause_step FROM traces WHERE trace_id = ?", (trace_id,))
    trace_row = cursor.fetchone()
    
    if trace_row and corrected_output:
        input_doc = trace_row['input_doc']
        failing_step = trace_row['root_cause_step'] or "Unknown"
        
        # Determine the bad output from the failing step if possible, otherwise use final_output
        bad_output = trace_row['final_output']
        if failing_step != "Unknown":
            cursor.execute("SELECT output_data FROM spans WHERE trace_id = ? AND name = ?", (trace_id, failing_step))
            span_row = cursor.fetchone()
            if span_row:
                bad_output = span_row['output_data']
                
        # Generate clean case ID
        case_id = f"case_{trace_id[:8]}"
        created_at = datetime.utcnow().isoformat()
        
        cursor.execute("""
        INSERT INTO eval_cases (case_id, trace_id, input_doc, failing_step, bad_output, corrected_output, category, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(case_id) DO UPDATE SET
            corrected_output=excluded.corrected_output,
            category=excluded.category
        """, (case_id, trace_id, input_doc, failing_step, bad_output, corrected_output, human_category, created_at))
        
    conn.commit()
    conn.close()

def get_all_traces():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT t.*, 
           (SELECT COUNT(*) FROM spans s WHERE s.trace_id = t.trace_id) as span_count,
           (SELECT SUM(s.latency) FROM spans s WHERE s.trace_id = t.trace_id) as total_latency
    FROM traces t
    ORDER BY created_at DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_trace_details(trace_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM traces WHERE trace_id = ?", (trace_id,))
    trace_row = cursor.fetchone()
    
    if not trace_row:
        conn.close()
        return None
        
    cursor.execute("SELECT * FROM spans WHERE trace_id = ? ORDER BY start_time ASC", (trace_id,))
    span_rows = cursor.fetchall()
    
    conn.close()
    return {
        "trace": dict(trace_row),
        "spans": [dict(s) for s in span_rows]
    }

def get_eval_cases():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM eval_cases ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_failure_analytics():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Root cause step distribution
    cursor.execute("""
    SELECT root_cause_step, COUNT(*) as count
    FROM traces
    WHERE status = 'FAILED' OR root_cause_step IS NOT NULL
    GROUP BY root_cause_step
    """)
    steps_dist = [dict(r) for r in cursor.fetchall()]
    
    # Failure category distribution (combining automated diagnosis and human flagged)
    cursor.execute("""
    SELECT COALESCE(human_category, root_cause_type) as failure_type, COUNT(*) as count
    FROM traces
    WHERE (status = 'FAILED' OR root_cause_step IS NOT NULL OR human_flagged = 1)
      AND failure_type IS NOT NULL
    GROUP BY failure_type
    """)
    types_dist = [dict(r) for r in cursor.fetchall()]
    
    conn.close()
    return {
        "steps_distribution": steps_dist,
        "types_distribution": types_dist
    }

# Automatically initialize database when imported
init_db()
