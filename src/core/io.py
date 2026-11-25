"""Atomowe operacje zapisu plików oraz blokady plikowe (advisory lock)."""

import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Union

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


@contextmanager
def file_lock(path: Union[Path, str], timeout: float = 10.0, exclusive: bool = True) -> Iterator[None]:
    """Kontekstowy menedżer blokady plikowej oparty na fcntl.flock."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.parent / f".{target.name}.lock"

    if fcntl is None:
        yield
        return

    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    start_time = time.time()
    locked = False
    try:
        while True:
            try:
                fcntl.flock(fd, mode | fcntl.LOCK_NB)
                locked = True
                break
            except (BlockingIOError, OSError):
                if time.time() - start_time >= timeout:
                    raise TimeoutError(f"Nie udało się uzyskać blokady pliku {lock_path} w ciągu {timeout}s")
                time.sleep(0.02)
        yield
    finally:
        if locked:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass


def _atomic_write_impl(
    target: Path,
    writer: Callable[[Any], None],
    binary: bool = False,
    encoding: str = "utf-8",
    mode: Optional[int] = 0o600,
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.parent / f".{target.name}.tmp.{uuid.uuid4().hex}"
    open_mode = "wb" if binary else "w"
    kwargs: dict[str, Any] = {} if binary else {"encoding": encoding}
    try:
        with open(temp_path, open_mode, **kwargs) as f:
            writer(f)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            try:
                os.chmod(temp_path, mode)
            except OSError:
                pass
        os.replace(temp_path, target)
        return target
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise


def atomic_write_text(
    path: Union[Path, str],
    content: str,
    encoding: str = "utf-8",
    mode: Optional[int] = 0o600,
    lock: bool = False,
    lock_timeout: float = 10.0,
) -> Path:
    """Atomowo zapisuje tekst do pliku przez plik tymczasowy i os.replace."""
    target = Path(path)
    if lock:
        with file_lock(target, timeout=lock_timeout):
            return _atomic_write_impl(target, lambda f: f.write(content), binary=False, encoding=encoding, mode=mode)
    return _atomic_write_impl(target, lambda f: f.write(content), binary=False, encoding=encoding, mode=mode)


def atomic_write_bytes(
    path: Union[Path, str],
    content: bytes,
    mode: Optional[int] = 0o600,
    lock: bool = False,
    lock_timeout: float = 10.0,
) -> Path:
    """Atomowo zapisuje dane binarne (np. PDF) do pliku."""
    target = Path(path)
    if lock:
        with file_lock(target, timeout=lock_timeout):
            return _atomic_write_impl(target, lambda f: f.write(content), binary=True, mode=mode)
    return _atomic_write_impl(target, lambda f: f.write(content), binary=True, mode=mode)


def atomic_write_json(
    path: Union[Path, str],
    data: Any,
    indent: int = 2,
    ensure_ascii: bool = False,
    default: Optional[Callable[[Any], Any]] = None,
    encoding: str = "utf-8",
    mode: Optional[int] = 0o600,
    lock: bool = False,
    lock_timeout: float = 10.0,
) -> Path:
    """Atomowo zapisuje dane JSON do pliku."""
    target = Path(path)
    serialized = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii, default=default)
    return atomic_write_text(target, serialized, encoding=encoding, mode=mode, lock=lock, lock_timeout=lock_timeout)
