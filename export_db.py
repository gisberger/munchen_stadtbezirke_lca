# Tables with data
pg_dump -h localhost -U gisuser -d gisdb \
  --schema=lca \
  --no-owner --no-acl \
  -F p -f lca_export.sql

# If the geometry comes from public schema, export that table too
pg_dump -h localhost -U gisuser -d gisdb \
  -t 'public."vablock_stadtbezirk.geojson"' \
  --no-owner --no-acl \
  -F p -f geom_export.sql