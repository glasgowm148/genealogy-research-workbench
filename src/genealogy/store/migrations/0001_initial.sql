-- Genealogy Research Workbench project database, schema version 1.
--
-- One authoritative SQLite database per research project. Ordinary relational
-- tables hold the structured research; large originals, captures and long prose
-- live in files referenced by `asset` rows with their SHA-256.
--
-- Conventions
--   * Every identifier is an opaque TEXT id that never encodes a WikiTree ID,
--     a name, a filename or a website slug. External identifiers are mapped in
--     `external_id`; public routes in `route_alias`.
--   * Every addressable row is registered in `entity` (by trigger), so link
--     tables can reference any entity with an enforced foreign key.
--   * Mutable rows carry `revision`, raised by every update, for optimistic
--     concurrency (see services: expected revisions).
--   * `access` is the row's own access classification. Publication is decided
--     only by the public projection, never by a flag copied into an export.
--   * `extra_json` holds small, project-specific fields with no core meaning.
--     It must never hold relationships or conclusions the core models.

CREATE TABLE schema_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- A group of changes made together, with who/what made them and why.
CREATE TABLE change_set (
  id         TEXT PRIMARY KEY,
  actor      TEXT NOT NULL,              -- person or agent responsible
  tool       TEXT,                        -- command or program that made it
  source     TEXT,                        -- input file, proposal or URL it came from
  reason     TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE audit_log (
  seq           INTEGER PRIMARY KEY AUTOINCREMENT,
  change_set_id TEXT NOT NULL REFERENCES change_set(id),
  table_name    TEXT NOT NULL,
  row_id        TEXT NOT NULL,
  action        TEXT NOT NULL CHECK (action IN ('insert', 'update', 'delete')),
  revision      INTEGER,
  before_json   TEXT,
  after_json    TEXT
);
CREATE INDEX audit_log_row ON audit_log(table_name, row_id);

CREATE TABLE entity (
  id   TEXT PRIMARY KEY,
  type TEXT NOT NULL
);

-- ---------------------------------------------------------------- identity

CREATE TABLE person (
  id            TEXT PRIMARY KEY,
  sex           TEXT CHECK (sex IS NULL OR sex IN ('male', 'female', 'unknown', 'other')),
  living        TEXT NOT NULL DEFAULT 'unknown' CHECK (living IN ('living', 'deceased', 'unknown')),
  living_basis  TEXT,
  label         TEXT,                     -- researcher's short label, e.g. "Lisnagaver Robert"
  record_defined INTEGER NOT NULL DEFAULT 0 CHECK (record_defined IN (0, 1)),
  summary       TEXT,
  access        TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision      INTEGER NOT NULL DEFAULT 1,
  extra_json    TEXT
);

CREATE TABLE person_name (
  id               TEXT PRIMARY KEY,
  person_id        TEXT NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  full_name        TEXT NOT NULL,
  given            TEXT,
  surname          TEXT,
  kind             TEXT NOT NULL DEFAULT 'unknown',   -- birth, married, preferred, alias, reading, transcription
  original_wording TEXT,
  preferred        INTEGER NOT NULL DEFAULT 0 CHECK (preferred IN (0, 1)),
  sort_order       INTEGER NOT NULL DEFAULT 0,
  basis            TEXT,
  confidence       TEXT CHECK (confidence IS NULL OR confidence IN ('documented', 'probable', 'possible', 'disproved', 'unknown')),
  language         TEXT,
  revision         INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX person_name_person ON person_name(person_id);
CREATE INDEX person_name_surname ON person_name(surname);

-- WikiTree IDs, GEDCOM UIDs, FamilySearch IDs, former IDs and redirects.
CREATE TABLE external_id (
  id          TEXT PRIMARY KEY,
  entity_id   TEXT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  system      TEXT NOT NULL,
  value       TEXT NOT NULL,
  url         TEXT,
  status      TEXT NOT NULL DEFAULT 'current' CHECK (status IN ('current', 'former', 'redirect', 'alias', 'candidate', 'retired')),
  redirect_to TEXT,                       -- for status 'redirect': the external value it now resolves to
  verified    INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
  observed_on TEXT,
  note        TEXT
);
CREATE UNIQUE INDEX external_id_unique ON external_id(system, value, entity_id);
CREATE INDEX external_id_lookup ON external_id(system, value);
CREATE INDEX external_id_entity ON external_id(entity_id);

-- Existing and former public routes, so pages keep their addresses.
CREATE TABLE route_alias (
  path      TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  kind      TEXT NOT NULL DEFAULT 'current' CHECK (kind IN ('current', 'former', 'redirect'))
);

-- Supported merges and splits, with the references they moved.
CREATE TABLE entity_merge (
  id            TEXT PRIMARY KEY,
  kind          TEXT NOT NULL CHECK (kind IN ('merge', 'split')),
  survivor_id   TEXT NOT NULL REFERENCES entity(id),
  retired_ids   TEXT NOT NULL,            -- JSON list
  moved_json    TEXT NOT NULL,            -- JSON list of {table,row_id,column,from,to}
  reason        TEXT NOT NULL,
  change_set_id TEXT NOT NULL REFERENCES change_set(id)
);

-- ------------------------------------------------------------------ places

CREATE TABLE place (
  id         TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  parent_id  TEXT REFERENCES place(id),
  latitude   REAL CHECK (latitude IS NULL OR (latitude BETWEEN -90 AND 90)),
  longitude  REAL CHECK (longitude IS NULL OR (longitude BETWEEN -180 AND 180)),
  precision  TEXT CHECK (precision IS NULL OR precision IN ('exact', 'building', 'street', 'settlement', 'parish', 'district', 'county', 'region', 'country', 'approximate')),
  region     TEXT,
  coordinate_basis TEXT,
  access     TEXT NOT NULL DEFAULT 'public' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision   INTEGER NOT NULL DEFAULT 1,
  extra_json TEXT,
  CHECK ((latitude IS NULL) = (longitude IS NULL))
);

-- ----------------------------------------------------------------- sources

-- An archive, library or website that holds material.
CREATE TABLE repository (
  id       TEXT PRIMARY KEY,
  name     TEXT NOT NULL,
  location TEXT,
  url      TEXT,
  revision INTEGER NOT NULL DEFAULT 1
);

-- A source work or collection (a register, a will book, a census).
CREATE TABLE source (
  id          TEXT PRIMARY KEY,
  title       TEXT NOT NULL,
  kind        TEXT NOT NULL DEFAULT 'unknown',
  author      TEXT,
  publication TEXT,
  url         TEXT,
  originality TEXT CHECK (originality IS NULL OR originality IN ('original', 'derivative', 'authored', 'unknown')),
  licence     TEXT,
  access_note TEXT,
  access      TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision    INTEGER NOT NULL DEFAULT 1,
  extra_json  TEXT
);

-- A repository's holding of a source, with its catalogue reference.
CREATE TABLE source_holding (
  id             TEXT PRIMARY KEY,
  source_id      TEXT NOT NULL REFERENCES source(id),
  repository_id  TEXT REFERENCES repository(id),
  catalogue_ref  TEXT,
  note           TEXT,
  revision       INTEGER NOT NULL DEFAULT 1
);

-- One particular captured or inspected copy (a film, an image, a website page,
-- a PDF). Two copies sharing a catalogue reference remain two rows.
CREATE TABLE source_copy (
  id            TEXT PRIMARY KEY,
  source_id     TEXT NOT NULL REFERENCES source(id),
  holding_id    TEXT REFERENCES source_holding(id),
  form          TEXT NOT NULL DEFAULT 'unknown',     -- original, image, microfilm, transcript_site, index, pdf, abstract
  description   TEXT,
  url           TEXT,
  inspected     INTEGER NOT NULL DEFAULT 0 CHECK (inspected IN (0, 1)),
  inspection_note TEXT,
  captured_on   TEXT,
  accessed_on   TEXT,
  asset_id      TEXT REFERENCES asset(id),
  derived_from_copy_id TEXT REFERENCES source_copy(id),  -- repeated information is not independent
  access        TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision      INTEGER NOT NULL DEFAULT 1
);

-- One record occurrence within a source (an entry, a will, a deed). It exists
-- before, and independently of, any identification of its participants.
CREATE TABLE record (
  id             TEXT PRIMARY KEY,
  source_id      TEXT REFERENCES source(id),
  copy_id        TEXT REFERENCES source_copy(id),
  record_type    TEXT,
  title          TEXT NOT NULL,
  locator        TEXT,
  date_original  TEXT,
  date_start     TEXT,
  date_end       TEXT,
  date_kind      TEXT NOT NULL DEFAULT 'unknown' CHECK (date_kind IN ('exact', 'about', 'before', 'after', 'between', 'range', 'estimated', 'calculated', 'inferred', 'unknown')),
  place_id       TEXT REFERENCES place(id),
  place_wording  TEXT,
  summary        TEXT,                    -- researcher's abstract (interpretation)
  information    TEXT CHECK (information IS NULL OR information IN ('primary', 'secondary', 'undetermined', 'mixed')),
  url            TEXT,
  access         TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision       INTEGER NOT NULL DEFAULT 1,
  extra_json     TEXT
);
CREATE INDEX record_source ON record(source_id);

CREATE TABLE citation (
  id          TEXT PRIMARY KEY,
  source_id   TEXT NOT NULL REFERENCES source(id),
  record_id   TEXT REFERENCES record(id),
  copy_id     TEXT REFERENCES source_copy(id),
  locator     TEXT,
  accessed_on TEXT,
  note        TEXT,
  access      TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision    INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX citation_record ON citation(record_id);

-- A transcription, abstract, translation or reading of a record. Text lives in
-- revisions; correcting a reading adds a revision and keeps the earlier one.
CREATE TABLE transcription (
  id               TEXT PRIMARY KEY,
  record_id        TEXT NOT NULL REFERENCES record(id),
  copy_id          TEXT REFERENCES source_copy(id),
  kind             TEXT NOT NULL DEFAULT 'transcription' CHECK (kind IN ('transcription', 'abstract', 'translation', 'reading', 'index_entry')),
  current_revision INTEGER NOT NULL DEFAULT 1,
  access           TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE transcription_revision (
  transcription_id TEXT NOT NULL REFERENCES transcription(id) ON DELETE CASCADE,
  revision         INTEGER NOT NULL,
  text             TEXT,
  asset_id         TEXT REFERENCES asset(id),
  status           TEXT NOT NULL DEFAULT 'current' CHECK (status IN ('current', 'superseded', 'withdrawn')),
  reader           TEXT,
  read_on          TEXT,
  uncertainty      TEXT,
  reason           TEXT,
  change_set_id    TEXT REFERENCES change_set(id),
  PRIMARY KEY (transcription_id, revision),
  CHECK (text IS NOT NULL OR asset_id IS NOT NULL)
);

-- A participant named in a record, exactly as written. No person is required.
CREATE TABLE mention (
  id              TEXT PRIMARY KEY,
  record_id       TEXT NOT NULL REFERENCES record(id),
  role            TEXT,                   -- subject, father, mother, witness, testator, son...
  name_as_written TEXT,
  details         TEXT,
  sort_order      INTEGER NOT NULL DEFAULT 0,
  access          TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision        INTEGER NOT NULL DEFAULT 1,
  extra_json      TEXT
);
CREATE INDEX mention_record ON mention(record_id);
CREATE INDEX transcription_record ON transcription(record_id);

-- What a document itself says about a relationship between two mentions
-- ("Isaac, son of the testator"). It is not a genealogical conclusion.
CREATE TABLE documentary_relation (
  id              TEXT PRIMARY KEY,
  record_id       TEXT NOT NULL REFERENCES record(id),
  from_mention_id TEXT NOT NULL REFERENCES mention(id),
  to_mention_id   TEXT NOT NULL REFERENCES mention(id),
  relation        TEXT NOT NULL,          -- as stated: son, wife, father, executor...
  wording         TEXT,
  revision        INTEGER NOT NULL DEFAULT 1,
  CHECK (from_mention_id <> to_mention_id)
);

-- ------------------------------------------------------------------ events

CREATE TABLE event (
  id             TEXT PRIMARY KEY,
  kind           TEXT NOT NULL,
  date_original  TEXT,
  date_kind      TEXT NOT NULL DEFAULT 'unknown' CHECK (date_kind IN ('exact', 'about', 'before', 'after', 'between', 'range', 'estimated', 'calculated', 'inferred', 'unknown')),
  date_start     TEXT,
  date_end       TEXT,
  calendar       TEXT,                    -- julian, gregorian, dual-dated...
  date_basis     TEXT,                    -- for inferred/calculated dates: how
  place_id       TEXT REFERENCES place(id),
  place_wording  TEXT,
  description    TEXT,
  record_id      TEXT REFERENCES record(id),
  access         TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision       INTEGER NOT NULL DEFAULT 1,
  extra_json     TEXT
);

CREATE TABLE event_participant (
  event_id  TEXT NOT NULL REFERENCES event(id) ON DELETE CASCADE,
  person_id TEXT NOT NULL REFERENCES person(id),
  role      TEXT NOT NULL DEFAULT 'principal',
  sort_order INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (event_id, person_id, role)
);
CREATE INDEX event_participant_person ON event_participant(person_id);

-- -------------------------------------------------------- claims and evidence

-- An explicit proposition. For relationship claims subject_person_id is the
-- child (or first party), object_person_id the parent (or second party) and
-- predicate the object's role: father, mother, parent, spouse or sibling.
-- "Object's child is subject" is a view derived from the same claim and its
-- assessment; it never has a confidence of its own.
CREATE TABLE claim (
  id                TEXT PRIMARY KEY,
  kind              TEXT NOT NULL CHECK (kind IN ('vital', 'relationship', 'identity', 'attribute', 'other')),
  predicate         TEXT NOT NULL,
  subject_person_id TEXT REFERENCES person(id),
  object_person_id  TEXT REFERENCES person(id),
  subject_mention_id TEXT REFERENCES mention(id),
  event_id          TEXT REFERENCES event(id),
  relation_type     TEXT CHECK (relation_type IS NULL OR relation_type IN ('biological', 'adoptive', 'step', 'foster', 'guardian', 'sealing', 'in_law', 'unknown')),
  value_text        TEXT,
  proposition       TEXT NOT NULL,        -- the asserted statement in words
  origin            TEXT NOT NULL DEFAULT 'research' CHECK (origin IN ('research', 'documentary', 'external_tree', 'imported')),
  access            TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  publication_status TEXT NOT NULL DEFAULT 'unreviewed' CHECK (publication_status IN ('unreviewed', 'approved', 'withheld', 'tree_facts_only')),
  revision          INTEGER NOT NULL DEFAULT 1,
  extra_json        TEXT,
  CHECK (kind <> 'relationship' OR (subject_person_id IS NOT NULL AND object_person_id IS NOT NULL AND subject_person_id <> object_person_id)),
  CHECK (kind <> 'identity' OR subject_mention_id IS NOT NULL OR subject_person_id IS NOT NULL)
);
CREATE INDEX claim_subject ON claim(subject_person_id);
CREATE INDEX claim_object ON claim(object_person_id);
CREATE INDEX claim_event ON claim(event_id);
CREATE INDEX claim_mention ON claim(subject_mention_id);
CREATE INDEX claim_kind ON claim(kind);

-- A record or citation bearing on a claim, for or against.
CREATE TABLE claim_evidence (
  id               TEXT PRIMARY KEY,
  claim_id         TEXT NOT NULL REFERENCES claim(id) ON DELETE CASCADE,
  citation_id      TEXT REFERENCES citation(id),
  record_id        TEXT REFERENCES record(id),
  mention_id       TEXT REFERENCES mention(id),
  stance           TEXT NOT NULL DEFAULT 'supports' CHECK (stance IN ('supports', 'opposes', 'context')),
  interpretation   TEXT,
  information      TEXT CHECK (information IS NULL OR information IN ('primary', 'secondary', 'undetermined', 'mixed')),
  independence_key TEXT,                  -- items sharing a key repeat the same underlying information
  limitation       TEXT,
  revision         INTEGER NOT NULL DEFAULT 1,
  extra_json       TEXT,
  CHECK (citation_id IS NOT NULL OR record_id IS NOT NULL OR mention_id IS NOT NULL)
);
CREATE INDEX claim_evidence_claim ON claim_evidence(claim_id);
CREATE INDEX claim_evidence_record ON claim_evidence(record_id);

-- Whose assessments these are. Independent researchers get separate scopes.
CREATE TABLE assessment_scope (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  researcher  TEXT,
  description TEXT
);

-- One assessment per claim per scope; its revisions are the history.
CREATE TABLE assessment (
  id               TEXT PRIMARY KEY,
  claim_id         TEXT NOT NULL REFERENCES claim(id) ON DELETE CASCADE,
  scope_id         TEXT NOT NULL REFERENCES assessment_scope(id),
  current_revision INTEGER NOT NULL DEFAULT 1,
  revision         INTEGER NOT NULL DEFAULT 1,
  UNIQUE (claim_id, scope_id)
);

CREATE TABLE assessment_revision (
  assessment_id     TEXT NOT NULL REFERENCES assessment(id) ON DELETE CASCADE,
  revision          INTEGER NOT NULL,
  status            TEXT,                 -- the project's own status word, as recorded (proved, probable...)
  grade             TEXT,                 -- the project's grade label, as recorded
  vocabulary        TEXT,                 -- which grading vocabulary status/grade belong to
  confidence        TEXT CHECK (confidence IS NULL OR confidence IN ('documented', 'probable', 'possible', 'disproved', 'unknown')),
  estimate_percent  INTEGER CHECK (estimate_percent IS NULL OR (estimate_percent BETWEEN 0 AND 100)),
  estimate_kind     TEXT CHECK (estimate_kind IS NULL OR estimate_kind IN ('subjective', 'calibrated', 'statistical')),
  reasoning         TEXT,
  limitations       TEXT,
  research_status   TEXT,                 -- open, in_progress, resolved, parked...
  working_selection INTEGER CHECK (working_selection IS NULL OR working_selection IN (0, 1)),
  attachment_status TEXT,                 -- the external tree attachment, separately from belief
  assessed_on       TEXT,
  review_due        TEXT,
  basis_json        TEXT,                 -- JSON list of source/record/citation ids cited as the basis
  change_set_id     TEXT REFERENCES change_set(id),
  extra_json        TEXT,
  PRIMARY KEY (assessment_id, revision),
  CHECK (estimate_percent IS NULL OR estimate_kind IS NOT NULL)
);

-- "This conclusion rests on that premise at that revision."
CREATE TABLE dependency (
  id               TEXT PRIMARY KEY,
  dependent_id     TEXT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  premise_id       TEXT NOT NULL REFERENCES entity(id),
  premise_revision INTEGER,
  note             TEXT,
  status           TEXT NOT NULL DEFAULT 'current' CHECK (status IN ('current', 'review_needed', 'acknowledged')),
  flagged_reason   TEXT,
  flagged_at       TEXT,
  revision         INTEGER NOT NULL DEFAULT 1,
  CHECK (dependent_id <> premise_id),
  UNIQUE (dependent_id, premise_id)
);
CREATE INDEX dependency_premise ON dependency(premise_id);

-- ---------------------------------------------------------------- research

CREATE TABLE finding (
  id                 TEXT PRIMARY KEY,
  recorded_on        TEXT,
  kind               TEXT,
  statement          TEXT NOT NULL,
  status             TEXT NOT NULL DEFAULT 'draft',  -- normalised: draft, current, qualified, withdrawn, superseded
  status_original    TEXT,
  qualification      TEXT,
  limitations        TEXT,
  supersedes_id      TEXT REFERENCES finding(id),
  withdrawn_reason   TEXT,
  access             TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  publication_status TEXT NOT NULL DEFAULT 'unreviewed' CHECK (publication_status IN ('unreviewed', 'approved', 'withheld', 'tree_facts_only')),
  revision           INTEGER NOT NULL DEFAULT 1,
  extra_json         TEXT
);

CREATE TABLE question (
  id               TEXT PRIMARY KEY,
  question         TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'open',      -- open, in_progress, parked, answered, withdrawn
  status_original  TEXT,
  priority         TEXT NOT NULL DEFAULT 'normal',
  resolves         TEXT,                  -- what evidence would answer it
  next_action      TEXT,
  resume_condition TEXT,                  -- when to pick it up again
  opened_on        TEXT,
  closed_on        TEXT,
  access           TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision         INTEGER NOT NULL DEFAULT 1,
  extra_json       TEXT
);

CREATE TABLE search (
  id          TEXT PRIMARY KEY,
  searched_on TEXT,
  repository  TEXT,
  scope       TEXT NOT NULL,              -- collection, years and names searched
  result      TEXT NOT NULL,              -- what was found, including nothing
  outcome     TEXT NOT NULL DEFAULT 'unknown' CHECK (outcome IN ('positive', 'negative', 'partial', 'unknown')),
  limitation  TEXT,
  access      TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision    INTEGER NOT NULL DEFAULT 1,
  extra_json  TEXT
);

CREATE TABLE hypothesis (
  id          TEXT PRIMARY KEY,
  kind        TEXT NOT NULL DEFAULT 'other',  -- identity, parentage, origin, group, other
  statement   TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'open',
  supports    TEXT,
  objections  TEXT,
  access      TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision    INTEGER NOT NULL DEFAULT 1,
  extra_json  TEXT
);

CREATE TABLE study (
  id             TEXT PRIMARY KEY,
  title          TEXT NOT NULL,
  kind           TEXT,
  summary        TEXT,
  rationale      TEXT,
  body           TEXT,                    -- short Markdown; long prose goes in body_asset_id
  body_asset_id  TEXT REFERENCES asset(id),
  conclusion     TEXT,
  limitations    TEXT,
  status         TEXT NOT NULL DEFAULT 'draft',
  updated_on     TEXT,
  access         TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision       INTEGER NOT NULL DEFAULT 1,
  extra_json     TEXT
);

-- Groups within studies (possible households, surname groups). Membership says
-- who is studied together, never that they are kin.
CREATE TABLE research_group (
  id        TEXT PRIMARY KEY,
  study_id  TEXT REFERENCES study(id) ON DELETE CASCADE,
  title     TEXT NOT NULL,
  kind      TEXT,
  note      TEXT,
  access    TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision  INTEGER NOT NULL DEFAULT 1,
  extra_json TEXT
);

-- Free prose linked to an entity: briefs, research plans, narratives, notes.
CREATE TABLE note (
  id        TEXT PRIMARY KEY,
  kind      TEXT NOT NULL DEFAULT 'note',
  title     TEXT,
  text      TEXT,
  asset_id  TEXT REFERENCES asset(id),
  access    TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision  INTEGER NOT NULL DEFAULT 1,
  CHECK (text IS NOT NULL OR asset_id IS NOT NULL)
);

-- Typed links from research items (findings, questions, searches, hypotheses,
-- studies, groups, notes, proposals) to the entities they concern.
CREATE TABLE link (
  from_id    TEXT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  to_id      TEXT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  role       TEXT NOT NULL DEFAULT 'related',
  sort_order INTEGER NOT NULL DEFAULT 0,
  note       TEXT,
  PRIMARY KEY (from_id, to_id, role),
  CHECK (from_id <> to_id)
);
CREATE INDEX link_to ON link(to_id);

-- ---------------------------------------------------------------------- DNA

CREATE TABLE haplogroup (
  id        TEXT PRIMARY KEY,
  name      TEXT NOT NULL,
  parent_id TEXT REFERENCES haplogroup(id),
  date_text TEXT,
  note      TEXT,
  access    TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision  INTEGER NOT NULL DEFAULT 1
);

-- A DNA observation or interpretation: kept apart from documentary claims.
-- Raw genotype or sequence data never enters the database.
CREATE TABLE dna_observation (
  id            TEXT PRIMARY KEY,
  kind          TEXT NOT NULL,            -- branch_assignment, match_summary, str_comparison, interpretation
  person_id     TEXT REFERENCES person(id),
  haplogroup_id TEXT REFERENCES haplogroup(id),
  tester_label  TEXT,
  summary       TEXT NOT NULL,
  limitations   TEXT,
  provenance    TEXT,
  observed_on   TEXT,
  asset_id      TEXT REFERENCES asset(id),
  access        TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision      INTEGER NOT NULL DEFAULT 1
);

-- ------------------------------------------------------------------- files

-- A file outside the database: an original capture, PDF, image, long prose.
-- `root` names a configured asset root; `path` is relative to it.
CREATE TABLE asset (
  id            TEXT PRIMARY KEY,
  sha256        TEXT NOT NULL CHECK (length(sha256) = 64),
  size          INTEGER NOT NULL CHECK (size >= 0),
  media_type    TEXT,
  root          TEXT NOT NULL,
  path          TEXT NOT NULL,
  kind          TEXT NOT NULL DEFAULT 'file',   -- capture, image, pdf, prose, transcription, export, original_import
  immutable     INTEGER NOT NULL DEFAULT 1 CHECK (immutable IN (0, 1)),
  original_name TEXT,
  captured_on   TEXT,
  provenance    TEXT,
  supersedes_id TEXT REFERENCES asset(id),
  access        TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision      INTEGER NOT NULL DEFAULT 1,
  UNIQUE (root, path, sha256)
);
CREATE INDEX asset_sha ON asset(sha256);

-- ------------------------------------------------------------- publication

-- An explicit publication approval. 'exact_file' approvals are scoped to the
-- bytes: they apply only while the file's SHA-256 still matches.
CREATE TABLE approval (
  id           TEXT PRIMARY KEY,
  kind         TEXT NOT NULL CHECK (kind IN ('exact_file', 'entity', 'page')),
  target       TEXT NOT NULL,             -- public path/URL for files and pages, entity id for entities
  sha256       TEXT CHECK (sha256 IS NULL OR length(sha256) = 64),
  source_path  TEXT,                      -- where the approved bytes come from
  entity_id    TEXT REFERENCES entity(id),
  scope        TEXT,                      -- the manifest scope it was granted under
  approved_on  TEXT,
  authority    TEXT NOT NULL,             -- who approved it, in their words
  manifest     TEXT,                      -- the manifest file it was recorded in
  status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
  revision     INTEGER NOT NULL DEFAULT 1,
  CHECK (kind <> 'exact_file' OR sha256 IS NOT NULL)
);
CREATE INDEX approval_target ON approval(target);

-- ------------------------------------------------------ external systems

-- A captured state of an external record (a WikiTree profile, a tree person).
-- Observations are never edited; a refresh adds a new row.
CREATE TABLE external_observation (
  id             TEXT PRIMARY KEY,
  system         TEXT NOT NULL,
  external_value TEXT NOT NULL,
  entity_id      TEXT REFERENCES entity(id),
  captured_on    TEXT,
  fields_json    TEXT NOT NULL,           -- the observed field values
  fields_sha256  TEXT NOT NULL,
  asset_id       TEXT REFERENCES asset(id),
  import_batch_id TEXT REFERENCES import_batch(id),
  UNIQUE (system, external_value, fields_sha256, captured_on)
);
CREATE INDEX external_observation_lookup ON external_observation(system, external_value);

-- The last remote state a local proposal was based on or accepted.
CREATE TABLE remote_baseline (
  system         TEXT NOT NULL,
  external_value TEXT NOT NULL,
  observation_id TEXT NOT NULL REFERENCES external_observation(id),
  accepted_on    TEXT,
  PRIMARY KEY (system, external_value)
);

-- ---------------------------------------------------------------- workflow

CREATE TABLE proposal (
  id              TEXT PRIMARY KEY,
  kind            TEXT NOT NULL,          -- wikitree_update, bulk_change, profile_creation...
  system          TEXT,
  target          TEXT,                   -- external id or local entity id
  status          TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'proposed', 'approved', 'applied', 'verified', 'rejected', 'deferred', 'superseded')),
  status_original TEXT,
  destination     TEXT,
  rationale       TEXT,
  basis_json      TEXT,                   -- expected revisions / baseline observation it was made from
  diff_json       TEXT,
  draft_text      TEXT,
  draft_asset_id  TEXT REFERENCES asset(id),
  authored        INTEGER NOT NULL DEFAULT 1 CHECK (authored IN (0, 1)),  -- 0 when machine generated
  access          TEXT NOT NULL DEFAULT 'private' CHECK (access IN ('public', 'private', 'restricted', 'licensed', 'raw_dna')),
  revision        INTEGER NOT NULL DEFAULT 1,
  extra_json      TEXT
);

CREATE TABLE proposal_event (
  seq           INTEGER PRIMARY KEY AUTOINCREMENT,
  proposal_id   TEXT NOT NULL REFERENCES proposal(id) ON DELETE CASCADE,
  at            TEXT,
  from_status   TEXT,
  to_status     TEXT NOT NULL,
  actor         TEXT,
  note          TEXT,
  change_set_id TEXT REFERENCES change_set(id)
);

-- ------------------------------------------------------------- provenance

CREATE TABLE import_batch (
  id            TEXT PRIMARY KEY,
  adapter       TEXT NOT NULL,
  input_label   TEXT,
  input_sha256  TEXT,
  input_commit  TEXT,
  options_json  TEXT,
  imported_at   TEXT NOT NULL,
  report_json   TEXT,
  asset_id      TEXT REFERENCES asset(id),
  change_set_id TEXT REFERENCES change_set(id)
);

-- Where each imported row came from: file and pointer within it.
CREATE TABLE import_origin (
  entity_id       TEXT NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  import_batch_id TEXT NOT NULL REFERENCES import_batch(id),
  input_path      TEXT NOT NULL,
  pointer         TEXT NOT NULL DEFAULT '',
  input_sha256    TEXT,
  content_sha256  TEXT,                   -- hash of the input item as loaded, for idempotent re-runs
  PRIMARY KEY (entity_id, import_batch_id, input_path, pointer)
);
CREATE INDEX import_origin_batch ON import_origin(import_batch_id);

-- Input the importer could not interpret, preserved verbatim with its origin.
CREATE TABLE legacy_item (
  id              TEXT PRIMARY KEY,
  import_batch_id TEXT REFERENCES import_batch(id),
  input_path      TEXT NOT NULL,
  pointer         TEXT NOT NULL DEFAULT '',
  disposition     TEXT NOT NULL CHECK (disposition IN ('unresolved', 'excluded', 'unsupported', 'conflict')),
  reason          TEXT NOT NULL,
  payload_json    TEXT,
  entity_id       TEXT REFERENCES entity(id),
  UNIQUE (input_path, pointer, disposition)
);
