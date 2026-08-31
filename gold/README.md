# Gold standard - deliberately unpopulated

`ecd-genes.tsv` has its schema and no data rows. That is the correct state right now.

**Why it is empty.** The no-unread-citation rule. Populating it from memory and labelling the
rows "Goyal et.al Blood 2020" would be citing a paper nobody in this project has read, which is
precisely the failure the rule exists to prevent. The gene list in `erdheim-chester-scope.md`
(BRAF, MAP2K1, ARAF, NRAS, KRAS, PIK3CA) is a working scope filter, **not** a gold standard, and
`ingest/config.py` treats it as such.

**Why it cannot be an API call.** ECD is a somatic neoplastic disease - BRAF V600E is acquired in
the histiocytes, not inherited. Orphanet's gene-disease associations are oriented toward germline
aetiology, so a live lookup could return a confidently wrong kind of truth. A frozen file with a
source per row is auditable; an API call at query time is not.

**To unblock:** read Goyal et.al, "Erdheim-Chester disease: consensus recommendations for
evaluation, diagnosis, and treatment in the molecular era", Blood 2020;135(22):1929, and fill in
one row per gene with the source. Optionally add Open Targets somatic evidence as a second
source column value. Reading it is also what makes the post's comments answerable.

Until this file has rows, no experiment claims precision or recall against a gold standard.
Experiments 1-3 measure coverage and agreement, which need no gold standard - see
`ARCHITECTURE.md`.
