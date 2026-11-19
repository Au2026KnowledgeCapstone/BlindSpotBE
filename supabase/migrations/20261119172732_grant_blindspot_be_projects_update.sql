-- blindspot_be takes a `SELECT ... FOR UPDATE` lock on projects purely to
-- serialize run numbering/submission across API workers (analysis.py,
-- imports.py). It never writes a column on projects; FOR UPDATE still
-- requires table-level UPDATE, which column grants don't satisfy.
GRANT UPDATE ON public.projects TO blindspot_be;
