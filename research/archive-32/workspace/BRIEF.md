# Archive reconciliation

All records are synthetic. Do not operate on any external system. Read page files
pages/01.txt through pages/32.txt, completely and in that order. Each page contains
scanned inventory tags interspersed with the authoritative or provisional notes.
Record the seal at each page end as evidence of a complete archive pass. Interpret
later corrections as overriding only the claims they explicitly supersede.
A list of seals or selected lines does not count as reviewing a complete page. An
unverified clerk note and a pending request cannot establish a valid backup.

Write output/reconciliation.json with these top-level keys, using literal data:

- page_seals: an object mapping "01" through "32" to the exact corresponding seal.
- lantern: object with id, bytes, backup_id and sha256 (without the sha256: prefix).
- gallery: object with id, bytes and backup_id (null if unverified).
- pending: object with job_id, asset_id, state and outcome (a string). Use
  the literal string "unknown" when there is no verified outcome. Otherwise
  use the verified outcome stated by the archive.
- superseded_page and correction_page: integers.

Keep existing files intact. All new working files and deliverables go under output/.
