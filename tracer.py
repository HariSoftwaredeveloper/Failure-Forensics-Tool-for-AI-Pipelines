import contextvars
import time
import os
import json
import uuid
import traceback
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult, SimpleSpanProcessor
from opentelemetry.trace import Status, StatusCode

import db

# Context variables to store the current trace context
current_trace_id_var = contextvars.ContextVar("current_trace_id", default=None)
current_input_doc_var = contextvars.ContextVar("current_input_doc", default=None)

TRACES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "traces")
os.makedirs(TRACES_DIR, exist_ok=True)

def write_trace_json(trace_id):
    """Fetches all trace data from SQLite and writes it to a clean JSON file."""
    trace_details = db.get_trace_details(trace_id)
    if not trace_details:
        return
        
    file_path = os.path.join(TRACES_DIR, f"{trace_id}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(trace_details, f, indent=2, ensure_ascii=False)

class SQLiteSpanExporter(SpanExporter):
    def export(self, spans):
        for span in spans:
            # Generate the string representation of trace_id and span_id
            trace_id = format(span.context.trace_id, '032x')
            span_id = format(span.context.span_id, '016x')
            
            # Extract custom attributes
            attrs = span.attributes
            input_data = attrs.get("pipeline.input_data", "{}")
            output_data = attrs.get("pipeline.output_data", "{}")
            prompt = attrs.get("pipeline.prompt", "")
            raw_response = attrs.get("pipeline.raw_response", "")
            confidence = attrs.get("pipeline.confidence", None)
            tokens_used = attrs.get("pipeline.tokens_used", None)
            
            status = "SUCCESS" if span.status.is_ok else "FAILED"
            error_message = span.status.description if not span.status.is_ok else None
            
            start_time = span.start_time / 1e9  # nanoseconds to seconds
            end_time = span.end_time / 1e9
            latency = end_time - start_time
            
            # Save span to SQLite
            db.save_span(
                span_id=span_id,
                trace_id=trace_id,
                name=span.name,
                status=status,
                start_time=start_time,
                end_time=end_time,
                latency=latency,
                input_data=input_data,
                output_data=output_data,
                prompt=prompt,
                raw_response=raw_response,
                confidence=confidence,
                tokens_used=tokens_used,
                error_message=error_message
            )
            
            # Update/Create JSON trace file
            write_trace_json(trace_id)
            
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass

# Initialize OpenTelemetry Global Tracer
provider = TracerProvider()
exporter = SQLiteSpanExporter()
processor = SimpleSpanProcessor(exporter)
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("ai_pipeline_forensics")

class TraceStepContext:
    """Context manager and decorator for tracing individual pipeline steps."""
    def __init__(self, step_name):
        self.step_name = step_name
        self.span = None
        self.start_time = 0
        self.trace_id = current_trace_id_var.get()
        
    def __enter__(self):
        self.start_time = time.time()
        
        # If no trace_id is set in the context, create a new one automatically
        if not self.trace_id:
            self.trace_id = uuid.uuid4().hex
            current_trace_id_var.set(self.trace_id)
            db.save_trace(self.trace_id, "RUNNING", "")
            
        # Start Otel Span
        # We parse the trace_id string into an OpenTelemetry SpanContext if required, 
        # but the default Otel context manager automatically propagates trace ID.
        # To force our custom trace_id, we start a span and then get the trace_id.
        self.span = tracer.start_span(self.step_name)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        latency = time.time() - self.start_time
        
        if exc_type is not None:
            # Handle exception
            error_msg = f"{exc_type.__name__}: {str(exc_val)}\n{traceback.format_exc()}"
            self.span.set_status(Status(StatusCode.ERROR, error_msg))
            self.span.record_exception(exc_val)
            self.span.set_attribute("pipeline.error_message", error_msg)
            # Update trace status in DB
            db.save_trace(self.trace_id, "FAILED", current_input_doc_var.get() or "")
        else:
            self.span.set_status(Status(StatusCode.OK))
            
        self.span.end()
        # Force flush to ensure SQLite and JSON files are updated immediately
        provider.force_flush()
        
        # Rewrite JSON file to ensure final span statuses are locked in
        write_trace_json(self.trace_id)
        return False # Propagate exception if any

    def record_inputs(self, inputs):
        """Records step inputs in the current span."""
        if self.span:
            # Handle Pydantic models or dictionaries safely
            if hasattr(inputs, "dict"):
                inputs_data = inputs.dict()
            elif hasattr(inputs, "model_dump"):
                inputs_data = inputs.model_dump()
            elif isinstance(inputs, dict):
                inputs_data = inputs
            else:
                try:
                    inputs_data = dict(inputs)
                except:
                    inputs_data = {"value": str(inputs)}
            self.span.set_attribute("pipeline.input_data", json.dumps(inputs_data))

    def record_outputs(self, outputs, prompt=None, raw_response=None, confidence=None, tokens_used=None):
        """Records outputs and LLM metadata in the current span."""
        if self.span:
            self.span.set_attribute("pipeline.output_data", json.dumps(outputs))
            if prompt:
                self.span.set_attribute("pipeline.prompt", prompt)
            if raw_response:
                self.span.set_attribute("pipeline.raw_response", raw_response)
            if confidence is not None:
                self.span.set_attribute("pipeline.confidence", confidence)
            if tokens_used is not None:
                self.span.set_attribute("pipeline.tokens_used", tokens_used)

def trace_step(step_name):
    """Decorator to trace a function as a step."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Extract first argument as input_data for logging if present
            input_val = args[0] if args else kwargs
            with TraceStepContext(step_name) as ctx:
                ctx.record_inputs(input_val)
                result = func(*args, **kwargs)
                
                # Check if result is a Pydantic model
                if hasattr(result, "dict"):
                    result_dict = result.dict()
                else:
                    result_dict = result
                
                # Extract LLM attributes if present in the Pydantic output
                prompt = result_dict.pop("_prompt", None) if isinstance(result_dict, dict) else None
                raw_response = result_dict.pop("_raw_response", None) if isinstance(result_dict, dict) else None
                confidence = result_dict.get("confidence") if isinstance(result_dict, dict) else None
                tokens_used = result_dict.pop("_tokens_used", None) if isinstance(result_dict, dict) else None
                
                ctx.record_outputs(
                    outputs=result_dict,
                    prompt=prompt,
                    raw_response=raw_response,
                    confidence=confidence,
                    tokens_used=tokens_used
                )
                return result
        return wrapper
    return decorator

def run_with_trace(trace_id, input_doc, pipeline_func, *args, **kwargs):
    """Runs a pipeline function with a pre-set trace context."""
    current_trace_id_var.set(trace_id)
    current_input_doc_var.set(input_doc)
    
    # Initialize the trace entry in the database
    db.save_trace(trace_id, "RUNNING", input_doc)
    
    try:
        # Run pipeline
        final_output = pipeline_func(input_doc, *args, **kwargs)
        
        # If the pipeline successfully returned, serialize the output
        if hasattr(final_output, "json"):
            final_output_str = final_output.json()
        elif isinstance(final_output, (dict, list)):
            final_output_str = json.dumps(final_output)
        else:
            final_output_str = str(final_output)
            
        # Update trace as SUCCESS
        db.save_trace(trace_id, "SUCCESS", input_doc, final_output=final_output_str)
        write_trace_json(trace_id)
        return final_output
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
        db.save_trace(trace_id, "FAILED", input_doc, error_message=error_msg)
        write_trace_json(trace_id)
        raise e
