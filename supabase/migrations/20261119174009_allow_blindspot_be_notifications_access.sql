-- notifications already has table-level GRANTs (INSERT, SELECT, UPDATE) for
-- blindspot_be, but RLS was enabled with no matching policy for that role,
-- so every insert blindspot_be made (job-completion notifications in
-- callbacks.py) was rejected with "new row violates row-level security
-- policy", which rolled back run completion entirely -- runs stayed stuck
-- in "running" while aiservice retried the doomed callback indefinitely.
CREATE POLICY blindspot_be_notification_access
    ON public.notifications FOR ALL TO blindspot_be
    USING (true)
    WITH CHECK (true);
