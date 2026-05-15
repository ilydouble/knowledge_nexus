# Findings

- Current `.env` uses `NEXUS_STORAGE_BACKEND=memory`, so API and worker do not share processed results across processes.
- API `/api/graph/neighborhood` currently returned no nodes; Neo4j also had zero `NexusFile` nodes.
- Browser URL `/api/auth/cloudreve/callback` returns `{"detail":"Not Found"}` because OAuth callback routes are not implemented yet.
- Existing result lookup endpoint is `/api/files/knowledge?uri=...`; there is no document list or job list endpoint yet.
