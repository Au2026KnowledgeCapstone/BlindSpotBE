-- Run as blindspot_be (table owner) or an authorized database administrator.
-- The current local backend connects as postgres and already has SELECT.
-- These writes are required for document import and draft requirement editing.
GRANT INSERT, UPDATE, DELETE ON
    blindspot.imports,
    blindspot.import_documents,
    blindspot.import_requirements,
    blindspot.requirements,
    blindspot.acceptance_criteria
TO postgres;
