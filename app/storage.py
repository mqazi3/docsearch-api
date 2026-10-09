from pathlib import Path

from app.config import get_settings


class LocalStorage:
    """Stores uploaded files on local disk. Same interface could be backed by S3 later."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        # Defense in depth: never read or write outside the storage root.
        if self.root.resolve() not in path.parents:
            raise ValueError(f"Invalid storage key: {key!r}")
        return path

    def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file, then rename: readers never see a half-written file.
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


def get_storage() -> LocalStorage:
    return LocalStorage(get_settings().upload_dir)
