"""Paths, target files and the ECD scope keys. Nothing here is a build date."""
from pathlib import Path

FTP_BASE = "https://ftp.ncbi.nlm.nih.gov/pub/lu/PubTator3"

# Native ext4, not /mnt/c - WSL's Windows mount is several times slower on write
# and we move ~4.86 GB and parse ~200M rows. Code/results live in the project dir.
DATA_ROOT = Path.home() / "pubtator3-data"
RAW_DIR = DATA_ROOT / "raw"
DB_PATH = DATA_ROOT / "pubtator.duckdb"
SCRATCH_DB = DATA_ROOT / "scratch.duckdb"

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Decision 1 (31 Aug): chemical included. Decision 4: species/cellline excluded.
ENTITY_FILES = {
    "disease2pubtator3.gz": "Disease",
    "gene2pubtator3.gz": "Gene",
    "mutation2pubtator3.gz": "Mutation",
    "chemical2pubtator3.gz": "Chemical",
}
RELATION_FILE = "relation2pubtator3.gz"
TARGET_FILES = list(ENTITY_FILES) + [RELATION_FILE]

# A build whose files span more than this was probably fetched mid-publish.
# Measured span of the 2026-08-17 build: 96 seconds.
MAX_BUILD_SPAN_HOURS = 24

# --- ECD scope, per erdheim-chester-scope.md ---
ECD_MESH = "MESH:D031249"
ECD_GENES = {           # NCBI Gene IDs for the recurrent drivers
    "673": "BRAF", "5604": "MAP2K1", "369": "ARAF",
    "4893": "NRAS", "3845": "KRAS", "5290": "PIK3CA",
}
# PubMed denominators, measured 31 Aug 2026 via E-utilities. Query strings kept
# because the two numbers mean different things - see ARCHITECTURE.md finding 5.
PUBMED_DENOMINATORS = {
    "mesh_indexed": {"count": 965, "query": '"erdheim chester disease"[MeSH Terms]'},
    "text_matched": {"count": 1599, "query": '"Erdheim-Chester"[All Fields]'},
}
