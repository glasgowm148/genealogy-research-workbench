-- Schema version 2: items kept for review can be resolved without being deleted.
--
-- A legacy_item (input the importer could not interpret, a conflict, an
-- unresolved reference) stays as it was recorded. Its resolution says what was
-- decided and why, by whom and when; an unresolved item has resolution NULL.

ALTER TABLE legacy_item ADD COLUMN resolution TEXT;
ALTER TABLE legacy_item ADD COLUMN resolved_on TEXT;
ALTER TABLE legacy_item ADD COLUMN resolved_by TEXT;
ALTER TABLE legacy_item ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;
CREATE INDEX legacy_item_open ON legacy_item(disposition) WHERE resolution IS NULL;
