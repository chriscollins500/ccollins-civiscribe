"""Atomic, no-overwrite publication of complete image files."""

from __future__ import annotations

import errno
import os
import re
import tempfile
from pathlib import Path

from ..domain import WriteError
from .paths import OutputPlan

MAX_COUNTER = 999_999_999
_LINK_UNAVAILABLE = {
    errno.EACCES,
    errno.EPERM,
    getattr(errno, "ENOTSUP", errno.EPERM),
    getattr(errno, "EOPNOTSUPP", errno.EPERM),
}
_SAFE_EXTENSION = re.compile(r"^\.[a-z0-9]+$", re.IGNORECASE)


def _validated_extension(extension: str) -> str:
    if _SAFE_EXTENSION.fullmatch(extension) is None:
        raise WriteError("output_extension_invalid")
    return extension.casefold()


def create_temporary_path(directory: Path, extension: str) -> Path:
    """Create a private sibling temporary file for one complete image."""

    safe_extension = _validated_extension(extension)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=".civiscribe-",
        suffix=f"{safe_extension}.tmp",
        dir=directory,
    )
    os.close(descriptor)
    return Path(raw_path)


def flush_file(path: Path) -> None:
    """Flush a completed temporary file before publication."""

    with path.open("rb+") as handle:
        os.fsync(handle.fileno())


def _publish_with_reservation(temporary: Path, destination: Path) -> None:
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    try:
        temporary.replace(destination)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def publish_image(temporary: Path, plan: OutputPlan, extension: str) -> Path:
    """Publish a complete image without replacing an existing numbered output."""

    safe_extension = _validated_extension(extension)
    counter = plan.next_counter(safe_extension)
    while counter <= MAX_COUNTER:
        destination = plan.directory / f"{plan.stem}_{counter:05}_{safe_extension}"
        try:
            os.link(temporary, destination)
        except FileExistsError:
            counter += 1
            continue
        except OSError as exc:
            if exc.errno not in _LINK_UNAVAILABLE:
                raise
            try:
                _publish_with_reservation(temporary, destination)
            except FileExistsError:
                counter += 1
                continue
            return destination
        temporary.unlink()
        return destination
    raise WriteError("output_counter_exhausted")


def publish_companion(temporary: Path, destination: Path) -> Path:
    """Publish one sibling companion file without replacing an existing file."""

    if temporary.parent.resolve() != destination.parent.resolve():
        raise WriteError("companion_directory_mismatch")
    try:
        os.link(temporary, destination)
    except FileExistsError as exc:
        raise WriteError("companion_destination_exists") from exc
    except OSError as exc:
        if exc.errno not in _LINK_UNAVAILABLE:
            raise
        try:
            _publish_with_reservation(temporary, destination)
        except FileExistsError as reservation_exc:
            raise WriteError("companion_destination_exists") from reservation_exc
        return destination
    temporary.unlink()
    return destination
