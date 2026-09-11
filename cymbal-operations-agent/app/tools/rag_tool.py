"""POS Hardware Troubleshooting RAG Tool with Adjacent Context Stitching & Guardrails."""

import logging
import os
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("PROJECT_ID", "praxis-magnet-508004-d7")
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.70"))
CONNECTION_ID = f"{PROJECT_ID}.us-central1.biglake-iceberg-connection"

_bq_client = None

def _get_bigquery_client():
    global _bq_client
    if _bq_client is None:
        from google.cloud import bigquery
        _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


def _convert_gcs_uri_to_https(gcs_uri: str) -> str:
    """Converts gs:// bucket URIs to authenticated HTTPS links."""
    if not gcs_uri:
        return ""
    if gcs_uri.startswith("gs://"):
        return gcs_uri.replace("gs://", "https://storage.cloud.google.com/")
    return gcs_uri


def _run_stitched_vector_search(query: str, max_retries: int = 3):
    """Executes BigQuery VECTOR_SEARCH with adjacent context stitching (N-1 to N+1)."""
    from google.cloud import bigquery

    sql = f"""
    WITH top_match AS (
      SELECT
        base.document_filename,
        base.document_title,
        base.equipment_covered,
        base.source_pdf_uri,
        base.chunk_index,
        ROUND(1.0 - distance, 4) AS similarity_score
      FROM
        VECTOR_SEARCH(
          TABLE `{PROJECT_ID}.cymbal_gold.pos_manual_chunk_embeddings`,
          'embedding',
          (
            SELECT AI.EMBED(
              @query_text,
              connection_id => '{CONNECTION_ID}',
              endpoint => 'text-embedding-005'
            ).result AS embedding
          ),
          top_k => 1,
          distance_type => 'COSINE'
        )
    ),
    stitched_context AS (
      SELECT
        m.document_filename,
        m.document_title,
        m.equipment_covered,
        m.source_pdf_uri,
        m.similarity_score,
        STRING_AGG(c.chunk_content, '\\n' ORDER BY c.chunk_index ASC) AS full_runbook
      FROM
        top_match m
      JOIN
        `{PROJECT_ID}.cymbal_gold.pos_manual_chunk_embeddings` c
      ON
        m.document_filename = c.document_filename
        AND c.chunk_index BETWEEN (m.chunk_index - 1) AND (m.chunk_index + 1)
      GROUP BY
        m.document_filename, m.document_title, m.equipment_covered, m.source_pdf_uri, m.similarity_score
    )
    SELECT * FROM stitched_context LIMIT 1;
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("query_text", "STRING", query)]
    )

    client = _get_bigquery_client()
    delay = 1.5
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            return list(client.query(sql, job_config=job_config).result())
        except Exception as e:
            last_err = e
            logger.warning(
                f"[Attempt {attempt}/{max_retries}] BigQuery vector query failed: {e}. Retrying in {delay}s..."
            )
            time.sleep(delay)
            delay *= 2.0
    raise last_err


def _run_fulltext_search_fallback(query: str):
    """Fallback to BigQuery SEARCH() function ONLY for recognized error codes."""
    from google.cloud import bigquery

    # Extract explicit error codes like ERR-PAY-4001, ERR-TGCS-COMM-02, etc.
    error_codes = re.findall(r"ERR-[A-Z0-9\-]+", query, re.IGNORECASE)
    if not error_codes:
        return []

    search_term = f"`{error_codes[0]}`"

    sql = f"""
    WITH top_match AS (
      SELECT
        document_filename,
        document_title,
        equipment_covered,
        source_pdf_uri,
        chunk_index,
        0.75 AS similarity_score
      FROM
        `{PROJECT_ID}.cymbal_gold.pos_manual_chunk_embeddings`
      WHERE
        SEARCH(chunk_content, '{search_term}')
      LIMIT 1
    ),
    stitched_context AS (
      SELECT
        m.document_filename,
        m.document_title,
        m.equipment_covered,
        m.source_pdf_uri,
        m.similarity_score,
        STRING_AGG(c.chunk_content, '\\n' ORDER BY c.chunk_index ASC) AS full_runbook
      FROM
        top_match m
      JOIN
        `{PROJECT_ID}.cymbal_gold.pos_manual_chunk_embeddings` c
      ON
        m.document_filename = c.document_filename
        AND c.chunk_index BETWEEN (m.chunk_index - 1) AND (m.chunk_index + 1)
      GROUP BY
        m.document_filename, m.document_title, m.equipment_covered, m.source_pdf_uri, m.similarity_score
    )
    SELECT * FROM stitched_context LIMIT 1;
    """
    client = _get_bigquery_client()
    return list(client.query(sql).result())


def pos_troubleshooting_rag_tool(diagnostic_query: str) -> str:
    """Searches official POS hardware engineering manuals for troubleshooting runbooks and error codes.

    Use this tool when users ask about:
    - POS hardware error codes (e.g. ERR-PAY-4001, ERR-DN-PRNT-24V).
    - EMV terminal contactless payment freezes and recovery procedures.
    - Thermal receipt printer jams, cutter locks, and power supplies.
    - Barcode scanner configuration and hardware diagnostic steps.

    Args:
        diagnostic_query: The technical hardware error or diagnostic query.
    Returns:
        Stitched procedural runbook, equipment model, and certified GCS manual link.
    """
    try:
        rows = _run_stitched_vector_search(diagnostic_query)

        # Check threshold
        if rows and rows[0].similarity_score >= SIMILARITY_THRESHOLD:
            row = rows[0]
        else:
            # Fallback to keyword SEARCH if vector similarity is below threshold
            fallback_rows = _run_fulltext_search_fallback(diagnostic_query)
            if fallback_rows:
                row = fallback_rows[0]
            else:
                return (
                    "⚠️ WARNING: No certified POS hardware documentation found matching this query. "
                    "The requested equipment or topic is out-of-scope for Cymbal Retail POS hardware maintenance."
                )

        https_link = _convert_gcs_uri_to_https(row.source_pdf_uri)
        return (
            f"### POS Hardware Field Diagnostic Runbook\n"
            f"- **Equipment Covered:** {row.equipment_covered}\n"
            f"- **Manual Document:** {row.document_title} (`{row.document_filename}`)\n"
            f"- **Relevance Score:** {row.similarity_score}\n"
            f"- **Certified Manual URL:** [{row.document_title}]({https_link})\n\n"
            f"#### Procedural Instructions:\n"
            f"{row.full_runbook}\n"
        )
    except Exception as e:
        logger.error(f"Error executing POS RAG search: {e}", exc_info=True)
        return (
            "Hardware diagnostic service is currently unavailable. "
            "Please consult the physical store runbook or escalate to Store IT Operations."
        )


troubleshoot_pos_hardware = pos_troubleshooting_rag_tool
