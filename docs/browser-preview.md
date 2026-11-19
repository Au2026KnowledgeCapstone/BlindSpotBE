# Live browser and recorded checkpoints

Active runs use the same desktop-streaming architecture as v2:

`headed Chromium → Xvfb :99 → x11vnc → websockify → noVNC canvas`

The first snapshot implementation was not equivalent to v2's live browser. It
is retained only for recorded checkpoints after a run finishes.

## Comparison with v2

| Component | v2 | Current AIService integration |
| --- | --- | --- |
| Browser | Headed Chromium, 250 ms slow motion | Same |
| Display | Xvfb :99 in the worker | Xvfb :99 in AIService |
| Desktop transport | x11vnc, view-only, no clipboard | Same, bound to loopback |
| WebSocket adapter | websockify on port 6080 | Same, bound to loopback |
| Client | noVNC viewer in an iframe at localhost:6080 | Bundled noVNC RFB client on the run page |
| Access | Local Docker-host viewer | Session/project/run-authorized BE WebSocket, service-authenticated AIService relay |
| Isolation | One worker/display | One job and one Cloud Run instance; disconnect when the active job changes |

BE endpoint:
`WS /projects/{pid}/environments/{eid}/runs/{runid}/browser-live`

AIService endpoint:
`WS /v1/jobs/{job_id}/browser-live`

BE validates the exact browser Origin, Supabase session, project membership,
environment/run binding, and persisted job ID. It periodically rechecks both
membership and session validity. Its service token stays server-side. AIService
checks that the requested job owns its current ready desktop, including before
every outgoing frame. A completed or different job cannot keep viewing the
worker. Both x11vnc and noVNC enforce view-only operation. VNC ports are not
publicly exposed.

The viewer connects after login preparation finishes. Firebase IndexedDB state
and the verified post-login URL are preserved in each new test context. Pausing
the viewer disconnects it without pausing the test. The viewer reconnects while
the run is active and can expand to full screen. A run that has already finished
shows its recorded checkpoint instead of claiming that a live browser exists.

## Recorded screenshots

The authenticated browser-preview HTTP endpoint remains available for historical
frames. It rejects blank or changing pages, masks password/email fields, and
strips URL queries and fragments. Legacy blank frames fall back to that job's
latest recorded PNG screenshot and are labeled as recorded checkpoints.

`GET /v1/jobs/{job_id}/evidence/{evidence_id}` checks the job's evidence outbox,
bounds the download, and verifies its digest. BE hydrates missing local files
from that endpoint, including references created by another BE instance. Only
PNG/JPEG evidence renders inline; text and source documents remain attachments.

## Deployment and verification

AIService image:
`europe-west1-docker.pkg.dev/blindspot-512322/cloud-run-source-deploy/aiservice:live-desktop-20261119`

Cloud Run revision: `aiservice-00008-76d`. Runtime settings enable
`BROWSER_LIVE_VIEW=true`, `BROWSER_SLOW_MO_MS=250`, one instance, one concurrent
execution job, session affinity, and a 3600-second WebSocket request timeout.
Existing database, service secrets, bucket, and callback settings are retained.

A protocol-level validation on run 8 completed an actual RFB 3.8 handshake and
received two nonblank 400×300 raw framebuffer updates (480,000 pixel bytes each)
from the 1960×1260 desktop. No mouse/keyboard input or Safari automation was used
by the transport check. Backend authorization/relay tests, noVNC client tests,
TypeScript, lint, and the frontend production build passed.

Executor source changes are based on aiservice
`9926b42018f70dbf4a6733e1e732f7120608f614`. The complete source/test patch is
`browser-preview-aiservice.patch`; apply it to that revision using `git apply`.
The build checkout is `/private/tmp/blindspot-ai-debug-9926`. Backend changes are
in this repository and frontend changes are in BlindSpotFE.
