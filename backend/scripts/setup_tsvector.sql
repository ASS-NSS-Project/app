-- Setup full-text search on chunks.text column
-- This trigger automatically updates text_vector whenever text changes

-- Create trigger function
CREATE OR REPLACE FUNCTION chunks_text_vector_update() RETURNS trigger AS $$
BEGIN
  NEW.text_vector := to_tsvector('english', COALESCE(NEW.text, ''));
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger
DROP TRIGGER IF EXISTS chunks_text_vector_trigger ON chunks;
CREATE TRIGGER chunks_text_vector_trigger
  BEFORE INSERT OR UPDATE OF text
  ON chunks
  FOR EACH ROW
  EXECUTE FUNCTION chunks_text_vector_update();

-- Backfill existing rows
UPDATE chunks SET text_vector = to_tsvector('english', COALESCE(text, ''))
WHERE text_vector IS NULL;

-- Verify
SELECT COUNT(*) as total_chunks,
       COUNT(text_vector) as chunks_with_tsvector
FROM chunks;
