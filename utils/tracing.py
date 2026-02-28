import logging
import os
from typing import Optional, Dict, Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor

# OTLP Exporter imports
try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
except ImportError:
    try:
        from opentelemetry.exporter.otlp.proto.grpc import trace_exporter as otlp_grpc
        OTLPSpanExporter = otlp_grpc.OTLPSpanExporter
    except ImportError:
        OTLPSpanExporter = None

_logger = logging.getLogger("tracing")
_tracing_initialized: bool = False


def _parse_resource_attributes(attrs_str: str) -> Dict[str, Any]:
    """
    Parse OTEL_RESOURCE_ATTRIBUTES string into a dictionary.
    Format: "key1=value1,key2=value2"
    """
    if not attrs_str:
        return {}
    
    attrs = {}
    for pair in attrs_str.split(","):
        pair = pair.strip()
        if "=" in pair:
            key, value = pair.split("=", 1)
            attrs[key.strip()] = value.strip()
    return attrs


def _get_sampling_probability() -> float:
    """
    Get sampling probability from environment variables.
    Supports both OTEL_TRACES_SAMPLER_ARG and MANAGEMENT_TRACING_SAMPLING_PROBABILITY.
    """
    # Check OTEL standard first
    sampler_arg = os.getenv("OTEL_TRACES_SAMPLER_ARG")
    if sampler_arg:
        try:
            return float(sampler_arg)
        except ValueError:
            pass
    
    # Fallback to management tracing sampling probability
    mgmt_prob = os.getenv("MANAGEMENT_TRACING_SAMPLING_PROBABILITY")
    if mgmt_prob:
        try:
            return float(mgmt_prob)
        except ValueError:
            pass
    
    return 1.0  # Default: sample everything


def init_tracer(service_name: Optional[str] = None) -> None:
    """
    Initialize OpenTelemetry tracer with OTLP exporter (gRPC).

    Supports standard OTEL_ environment variables:
    - OTEL_TRACES_EXPORTER: Set to "otlp" to enable (default: "otlp")
    - OTEL_EXPORTER_OTLP_PROTOCOL: Protocol to use (default: "grpc")
    - OTEL_EXPORTER_OTLP_ENDPOINT: OTLP endpoint URL
    - OTEL_SERVICE_NAME: Service name (overrides function parameter)
    - OTEL_RESOURCE_ATTRIBUTES: Resource attributes as "key=value,key2=value2"
    - OTEL_TRACES_SAMPLER_ARG or MANAGEMENT_TRACING_SAMPLING_PROBABILITY: Sampling probability
    - OTEL_PROPAGATORS: Comma-separated list of propagators (tracecontext is default)

    This function is safe to call multiple times; initialization will
    only happen once per process.
    """
    global _tracing_initialized
    if _tracing_initialized:
        return

    # Check if tracing is enabled
    traces_exporter = os.getenv("OTEL_TRACES_EXPORTER", "otlp").lower()
    if traces_exporter == "none":
        _logger.info("Tracing disabled via OTEL_TRACES_EXPORTER=none")
        _tracing_initialized = True
        return

    # Check if OTLP exporter is available
    if OTLPSpanExporter is None:
        _logger.warning(
            "OTLP exporter not available. Install opentelemetry-exporter-otlp-proto-grpc"
        )
        _tracing_initialized = True
        return

    # Get service name from env or parameter
    service_name = os.getenv("OTEL_SERVICE_NAME", service_name)
    if not service_name:
        service_name = "unknown-service"

    # Build resource attributes
    resource_attrs = {"service.name": service_name}
    
    # Parse OTEL_RESOURCE_ATTRIBUTES
    otel_attrs = os.getenv("OTEL_RESOURCE_ATTRIBUTES", "")
    if otel_attrs:
        parsed_attrs = _parse_resource_attributes(otel_attrs)
        resource_attrs.update(parsed_attrs)

    resource = Resource.create(resource_attrs)
    
    # Configure sampling
    sampling_prob = _get_sampling_probability()
    if sampling_prob < 1.0:
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
        sampler = TraceIdRatioBased(sampling_prob)
        provider = TracerProvider(resource=resource, sampler=sampler)
        _logger.info("Using TraceIdRatioBased sampler with probability: %.2f", sampling_prob)
    else:
        provider = TracerProvider(resource=resource)

    # Configure OTLP exporter
    otlp_protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").lower()
    otlp_endpoint = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://jaeger-collector.observability.svc.cluster.local:4317"
    )

    if otlp_protocol != "grpc":
        _logger.warning(
            "Only gRPC protocol is supported. Got: %s. Using gRPC.",
            otlp_protocol
        )

    try:
        otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        span_processor = BatchSpanProcessor(otlp_exporter)
        provider.add_span_processor(span_processor)
    except Exception as exc:
        _logger.error("Failed to create OTLP exporter: %s", exc, exc_info=True)
        _tracing_initialized = True
        return

    trace.set_tracer_provider(provider)

    # Configure propagators (tracecontext is always included by default)
    propagators = os.getenv("OTEL_PROPAGATORS", "tracecontext")
    if propagators:
        try:
            from opentelemetry.propagate import set_global_textmap
            from opentelemetry.propagators.composite import CompositeHTTPPropagator
            
            propagator_list = []
            for prop_name in propagators.split(","):
                prop_name = prop_name.strip()
                if prop_name == "tracecontext":
                    from opentelemetry.propagators.tracecontext import TraceContextTextMapPropagator
                    propagator_list.append(TraceContextTextMapPropagator())
                elif prop_name == "baggage":
                    from opentelemetry.propagators.baggage import BaggageTextMapPropagator
                    propagator_list.append(BaggageTextMapPropagator())
                # Note: custom-propagator would need to be implemented separately
            
            if propagator_list:
                set_global_textmap(CompositeHTTPPropagator(propagator_list))
                _logger.info("Configured propagators: %s", propagators)
        except Exception as exc:
            _logger.warning("Failed to configure propagators: %s", exc)

    # Auto-instrument common libraries
    try:
        RequestsInstrumentor().instrument()
    except Exception as exc:
        _logger.warning("Failed to instrument requests: %s", exc)

    try:
        RedisInstrumentor().instrument()
    except Exception as exc:
        _logger.warning("Failed to instrument redis: %s", exc)

    try:
        LoggingInstrumentor().instrument(set_logging_format=True)
    except Exception as exc:
        _logger.warning("Failed to instrument logging: %s", exc)

    _tracing_initialized = True
    _logger.info(
        "Tracing initialized for service '%s' → OTLP/gRPC at %s (sampling: %.2f%%)",
        service_name,
        otlp_endpoint,
        sampling_prob * 100,
    )


def get_tracer(name: Optional[str] = None) -> trace.Tracer:
    """
    Convenience accessor for a module-level tracer.
    """
    return trace.get_tracer(name or __name__)


def instrument_fastapi(app) -> None:
    """
    Attach OpenTelemetry instrumentation to a FastAPI app.
    """
    try:
        FastAPIInstrumentor.instrument_app(app)
        _logger.info("FastAPI instrumentation enabled for tracing")
    except Exception as exc:  # pragma: no cover - defensive logging
        _logger.warning("Failed to instrument FastAPI app: %s", exc)


def extract_trace_context_from_trace_dto(trace_dto: Dict[str, Any]) -> Optional[trace.SpanContext]:
    """
    Extract OpenTelemetry trace context from traceDto dictionary.
    
    Supports multiple formats:
    1. traceDto.traceId (string) - creates a new span linked to this trace ID
    2. traceDto.traceparent (W3C Trace Context format) - full trace context
    3. traceDto.spanId - span ID if provided
    
    Args:
        trace_dto: Dictionary containing trace information from user input
        
    Returns:
        SpanContext if trace information found, None otherwise
    """
    if not trace_dto or not isinstance(trace_dto, dict):
        return None
    
    try:
        # Try W3C traceparent format first (most complete)
        traceparent = trace_dto.get("traceparent")
        if traceparent:
            from opentelemetry.propagate import extract
            from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
            
            # Extract context from traceparent header format
            carrier = {"traceparent": traceparent}
            if "tracestate" in trace_dto:
                carrier["tracestate"] = trace_dto["tracestate"]
            
            context = TraceContextTextMapPropagator().extract(carrier)
            span_context = trace.get_current_span(context).get_span_context()
            if span_context.is_valid:
                _logger.debug("Extracted trace context from traceparent: %s", traceparent[:20])
                return span_context
        
        # Fallback: try traceId (assume it's a hex string)
        trace_id_str = trace_dto.get("traceId") or trace_dto.get("trace_id")
        if trace_id_str:
            try:
                # Convert hex string to trace ID (128-bit)
                # OpenTelemetry trace IDs are 32 hex characters (16 bytes)
                trace_id_hex = str(trace_id_str).replace("-", "").lower()
                
                # Pad or truncate to 32 hex chars
                if len(trace_id_hex) < 32:
                    trace_id_hex = trace_id_hex.ljust(32, "0")
                elif len(trace_id_hex) > 32:
                    trace_id_hex = trace_id_hex[:32]
                
                # Convert to bytes and create TraceId
                from opentelemetry.trace import TraceId
                trace_id_bytes = bytes.fromhex(trace_id_hex)
                trace_id = int.from_bytes(trace_id_bytes, byteorder="big")
                
                # Create span context (we don't have span_id, so use 0)
                span_id = trace_dto.get("spanId") or trace_dto.get("span_id")
                if span_id:
                    span_id_hex = str(span_id).replace("-", "").lower()
                    if len(span_id_hex) < 16:
                        span_id_hex = span_id_hex.ljust(16, "0")
                    elif len(span_id_hex) > 16:
                        span_id_hex = span_id_hex[:16]
                    span_id_bytes = bytes.fromhex(span_id_hex)
                    span_id_int = int.from_bytes(span_id_bytes, byteorder="big")
                else:
                    span_id_int = 0
                
                from opentelemetry.trace import SpanId
                from opentelemetry.trace import TraceFlags
                
                span_context = trace.SpanContext(
                    trace_id=TraceId(trace_id),
                    span_id=SpanId(span_id_int),
                    is_remote=True,
                    trace_flags=TraceFlags(0x01),  # Sampled
                )
                
                if span_context.is_valid:
                    _logger.debug("Extracted trace context from traceId: %s", trace_id_str[:20])
                    return span_context
            except (ValueError, TypeError) as e:
                _logger.debug("Failed to parse traceId: %s", e)
        
    except Exception as exc:
        _logger.warning("Failed to extract trace context from traceDto: %s", exc)
    
    return None


def use_trace_dto_context(trace_dto: Dict[str, Any], operation_name: str = "operation"):
    """
    Context manager to use trace context from traceDto.
    
    Usage:
        with use_trace_dto_context(task.get("traceDto", {}), "process_task"):
            # Your code here - will be part of the trace from traceDto
            process_task()
    
    Args:
        trace_dto: Dictionary containing trace information
        operation_name: Name for the span if creating a new one
        
    Returns:
        Context manager that sets the trace context
    """
    from contextlib import contextmanager
    
    @contextmanager
    def _trace_context():
        span_context = extract_trace_context_from_trace_dto(trace_dto)
        
        if span_context and span_context.is_valid:
            # Create a span with the extracted context
            tracer = get_tracer()
            parent_context = trace.set_span_in_context(trace.NonRecordingSpan(span_context))
            span = tracer.start_span(operation_name, context=parent_context)
            try:
                # Add traceDto info as span attributes
                if trace_dto:
                    trace_id = trace_dto.get("traceId") or trace_dto.get("trace_id")
                    if trace_id:
                        span.set_attribute("user.trace_id", str(trace_id))
                    
                    # Add any other traceDto fields as attributes
                    for key, value in trace_dto.items():
                        if key not in ["traceId", "trace_id", "spanId", "span_id", "traceparent", "tracestate"]:
                            try:
                                span.set_attribute(f"user.trace_dto.{key}", str(value))
                            except Exception:
                                pass
                
                with trace.use_span(span):
                    yield span
            finally:
                span.end()
        else:
            # No valid trace context, create new trace
            tracer = get_tracer()
            with tracer.start_as_current_span(operation_name) as span:
                # Still add traceDto info as attributes even if not linking
                if trace_dto:
                    trace_id = trace_dto.get("traceId") or trace_dto.get("trace_id")
                    if trace_id:
                        span.set_attribute("user.trace_id", str(trace_id))
                yield span
    
    return _trace_context()


def add_trace_dto_to_span(span: trace.Span, trace_dto: Dict[str, Any]) -> None:
    """
    Add traceDto information as attributes to an existing span.
    
    Args:
        span: OpenTelemetry span to add attributes to
        trace_dto: Dictionary containing trace information
    """
    if not trace_dto or not isinstance(trace_dto, dict):
        return
    
    try:
        trace_id = trace_dto.get("traceId") or trace_dto.get("trace_id")
        if trace_id:
            span.set_attribute("user.trace_id", str(trace_id))
        
        # Add other traceDto fields as attributes
        for key, value in trace_dto.items():
            if key not in ["traceId", "trace_id", "spanId", "span_id", "traceparent", "tracestate"]:
                try:
                    span.set_attribute(f"user.trace_dto.{key}", str(value))
                except Exception:
                    pass
    except Exception as exc:
        _logger.debug("Failed to add traceDto to span: %s", exc)


