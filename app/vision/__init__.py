import hashlib
from pathlib import Path


def source_hash(*filenames):
    root = Path(__file__).resolve().parent
    return hashlib.sha256(b"".join((root / name).read_bytes() for name in filenames)).hexdigest()[:16]
