-- ==============================================================================
-- Module 3 Challenge 2.2: Optimize POS Troubleshooting Embeddings with Sliding Window
-- Project: praxis-magnet-508004-d7
-- ==============================================================================

-- Step 1: Create Sliding-Window Chunks (500 chars, 100 char overlap / 400 step)
CREATE OR REPLACE TABLE `praxis-magnet-508004-d7.cymbal_gold.pos_manual_chunk_embeddings` AS
WITH chunk_offsets AS (
  SELECT
    document_filename,
    document_title,
    equipment_covered,
    source_pdf_uri,
    offset_pos,
    OFFSET AS chunk_index,
    SUBSTR(extracted_full_content, offset_pos, 500) AS chunk_content
  FROM
    `praxis-magnet-508004-d7.module1_unstructureddata.pos_manual_generic_sections_extracted`,
    UNNEST(GENERATE_ARRAY(1, GREATEST(LENGTH(extracted_full_content), 1), 400)) AS offset_pos WITH OFFSET
)
SELECT
  document_filename,
  document_title,
  equipment_covered,
  source_pdf_uri,
  chunk_index,
  chunk_content
FROM
  chunk_offsets
WHERE
  LENGTH(TRIM(chunk_content)) > 30;

-- Step 2: Add Embedding Vector Column
ALTER TABLE `praxis-magnet-508004-d7.cymbal_gold.pos_manual_chunk_embeddings`
ADD COLUMN IF NOT EXISTS embedding ARRAY<FLOAT64>;

-- Step 3: Populate Embeddings using BigQuery ML text-embedding-005 model
UPDATE `praxis-magnet-508004-d7.cymbal_gold.pos_manual_chunk_embeddings` target
SET target.embedding = emb.ml_generate_embedding_result
FROM (
  SELECT
    document_filename,
    chunk_index,
    ml_generate_embedding_result
  FROM
    ML.GENERATE_EMBEDDING(
      MODEL `praxis-magnet-508004-d7.module1_unstructureddata.pos_text_embedding_model`,
      (
        SELECT
          document_filename,
          chunk_index,
          CONCAT('[', document_title, ']\n', chunk_content) AS content
        FROM
          `praxis-magnet-508004-d7.cymbal_gold.pos_manual_chunk_embeddings`
      ),
      STRUCT('RETRIEVAL_DOCUMENT' AS task_type)
    )
) emb
WHERE target.document_filename = emb.document_filename
  AND target.chunk_index = emb.chunk_index;

-- Step 4: Verification Check
SELECT
  document_filename,
  COUNT(*) AS total_chunks,
  COUNT(embedding) AS chunks_with_embeddings
FROM
  `praxis-magnet-508004-d7.cymbal_gold.pos_manual_chunk_embeddings`
GROUP BY
  document_filename;
