# Commonworld API changelog

Semantic versioning of the data shape (schema_version). Minor and patch versions only add optional fields or files, so a v1 client keeps working. Any breaking change (a removed or renamed field, a changed type or meaning, a moved URL) ships as /api/v2/, and /api/v1/ keeps working.

## 1.0.0 (2026-10-16)

- First release of the Commonworld static API v1 at /api/v1/ with the Atlas module at /api/v1/atlas/.
- Endpoints: index.json, atlas/index.json, atlas/platforms.json, atlas/platforms/{id}.json, atlas/categories/{category}.json, atlas/earn.json.
- OpenAPI 3.1 description (openapi.json) and JSON Schema 2020-12 schemas (schemas/).
- Same records as the older /atlas/*.json files, which keep working unchanged.
- An ID or category that does not exist returns HTTP 404 (the site's HTML error page, not JSON). Never construct an ID; take it from atlas/platforms.json.
