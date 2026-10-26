# Reproduce the infrastructure checks

Use an isolated local PostgreSQL cluster. Never point tests at the hosted application database. The suite creates and drops fresh uniquely named databases, creates only missing test roles and uses synthetic auth identities.

On the supplied Quorum server:

    cd /home/nala/quoroum-backend/data/ops/mohagany-reviewed-capstone/BlindSpotBE
    /home/nala/quoroum-backend/data/ops/mohagany-api-test-venv/bin/python -m unittest discover -s tests/infrastructure -v

The default socket is /home/nala/quoroum-backend/data/ops/mohagany-test-postgres/socket, port 55432, user nala. Tests require a local cluster user allowed to create databases and test roles. Change the documented constants when adapting to a different private local cluster; do not pass a production URL.

For a fresh test tool environment:

    python3 -m venv .tools/venv
    .tools/venv/bin/python -m pip install -r requirements-dev.txt
    .tools/venv/bin/python tools/setup_test_tools.py
    .tools/venv/bin/python -m unittest discover -s tests/infrastructure -v

PostgREST v16.5 is downloaded from the official release and its GitHub-published SHA256 digest is verified before extraction. Override POSTGREST_BIN to use an already installed binary.

The bootstrap auth.users table and auth.uid() function exist only in disposable databases. The migration itself never defines either. HTTP tests use genuine signed synthetic JWTs and real PostgREST role switching; they do not validate Supabase password login or the team's hosted configuration.

Frontend checks from the reviewed BlindSpotFE checkout (use Node 26 or a version supported by the lockfile):

    npm ci
    npm run typecheck
    npx eslint src/features/workspace src/app/workspace src/app/projects/page.tsx
    npm test
    npm run build

Build environment requires the team's existing NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY. A disposable placeholder pair was used for the isolated verification build; no real account or secret was needed. Build the deployment again with the actual public values.

The browser check uses a synthetic signed-in identity and routes Data API requests to real local PostgREST/PostgreSQL. It creates project -> application -> environment -> scan request, reloads and verifies persistence. It separately checks the signed-out guard. This is not a claim that the hosted login/deployment has been tested.
