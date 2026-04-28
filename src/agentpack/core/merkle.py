import hashlib


def root_hash(file_hashes: dict[str, str]) -> str:
    h = hashlib.sha256()
    for path in sorted(file_hashes):
        h.update(f"{path}:{file_hashes[path]}".encode())
    return h.hexdigest()
