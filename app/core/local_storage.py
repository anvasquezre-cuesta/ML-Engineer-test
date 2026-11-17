"""Private local files and POSIX locks shared by API workers and maintenance.

Only a local filesystem shared by cooperating processes on one host is supported.
Never unlink a lock file: replacing its inode would let two owners hold a lock.
"""

from contextlib import contextmanager
import errno
import fcntl
import os
from pathlib import Path
import stat
import time


class StorageError(RuntimeError):
    pass


class StorageBusyError(StorageError):
    pass


def private_directory(path: Path) -> None:
    """Create new private directories; do not chmod an existing user's directory."""
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise StorageError("Storage directory must be owned by this user with mode 0700")
    except OSError:
        raise StorageError("Private storage directory is unavailable") from None


def private_file(path: Path, *, create: bool) -> tuple[int, bool]:
    """Open only a private regular file, with symlink and ownership checks."""
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
    created = False
    try:
        if create:
            try:
                fd = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
                created = True
            except FileExistsError:
                fd = os.open(path, flags)
        else:
            fd = os.open(path, flags)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            os.close(fd)
            raise StorageError("Storage file must be private, regular and owned by this user")
        return fd, created
    except OSError:
        raise StorageError("Private storage file is unavailable") from None


@contextmanager
def file_lock(path: Path, *, timeout: float = 0):
    fd, _ = private_file(path, create=True)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in (errno.EAGAIN, errno.EACCES):
                    raise StorageError("Local storage lock failed") from None
                if time.monotonic() >= deadline:
                    raise StorageBusyError("Another process owns this operation") from None
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        yield
    finally:
        os.close(fd)
