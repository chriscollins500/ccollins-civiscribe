"""Synthetic wheels for comparing checker releases without executing package code."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import re
import subprocess
import sys
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_INFO = "wheel_probe-1.0.dist-info"
RECORD = f"{DIST_INFO}/RECORD"
WHEEL = f"{DIST_INFO}/WHEEL"
FILENAME = "wheel_probe-1.0-py3-none-any.whl"
BASE_LIBRARY = {"wheel_probe/__init__.py": b'VERSION = "1.0"\n'}
REQUIRED_MODULE = b"def required():\n    return 2718\n"
NORMAL_HEADER = b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"


@dataclass(frozen=True, slots=True)
class WheelProbe:
    name: str
    members: Mapping[str, bytes]
    expected: str | None = None
    arguments: tuple[str, ...] = ()
    filename: str = FILENAME
    raw_archive: bytes | None = None


@dataclass(frozen=True, slots=True)
class CheckerOutcome:
    exit_code: int
    checks: tuple[str, ...]
    category: str

    def as_dict(self) -> dict[str, object]:
        return {"exitCode": self.exit_code, "checks": list(self.checks), "category": self.category}


def wheel_members(
    library: Mapping[str, bytes], *, header: bytes = NORMAL_HEADER
) -> dict[str, bytes]:
    members = {
        **library,
        WHEEL: header,
        f"{DIST_INFO}/METADATA": b"Metadata-Version: 2.4\nName: wheel-probe\nVersion: 1.0\n",
    }
    text = io.StringIO(newline="")
    writer = csv.writer(text, lineterminator="\n")
    for name, payload in sorted(members.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
        writer.writerow((name, "sha256=" + digest.decode("ascii"), len(payload)))
    writer.writerow((RECORD, "", ""))
    members[RECORD] = text.getvalue().encode("utf-8")
    return members


def wheel_probes(package: Path) -> tuple[WheelProbe, ...]:
    valid = wheel_members(BASE_LIBRARY)
    matching = wheel_members({**BASE_LIBRARY, "wheel_probe/required.py": REQUIRED_MODULE})
    package_arguments = ("--package", str(package))
    return (
        WheelProbe("valid_pure_python", valid),
        WheelProbe("valid_build_tag", valid, filename="wheel_probe-1.0-1build-py3-none-any.whl"),
        WheelProbe(
            "valid_platform_root",
            wheel_members(BASE_LIBRARY, header=NORMAL_HEADER.replace(b"true", b"false")),
        ),
        WheelProbe(
            "valid_relocated_library",
            wheel_members(
                {
                    f"wheel_probe-1.0.data/purelib/{name}": data
                    for name, data in BASE_LIBRARY.items()
                },
                header=NORMAL_HEADER.replace(b"true", b"false"),
            ),
        ),
        WheelProbe(
            "valid_empty_duplicates",
            wheel_members({"wheel_probe/__init__.py": b"", "wheel_probe/empty.py": b""}),
        ),
        WheelProbe(
            "valid_stubs", wheel_members({"wheel_probe-stubs/__init__.pyi": b"value: str\n"})
        ),
        WheelProbe("valid_package_tree", matching, arguments=package_arguments),
        WheelProbe("valid_toplevel", valid, arguments=("--toplevel", "wheel_probe")),
        WheelProbe(
            "valid_intentional_common_name",
            wheel_members({"tests/__init__.py": b'NAME = "intentional"\n'}),
            arguments=("--toplevel", "tests"),
        ),
        WheelProbe(
            "W001_bytecode",
            wheel_members({**BASE_LIBRARY, "wheel_probe/stray.pyc": b"bytecode"}),
            "W001",
        ),
        WheelProbe(
            "W002_duplicate_contents",
            wheel_members(
                {
                    **BASE_LIBRARY,
                    "wheel_probe/a.py": REQUIRED_MODULE,
                    "wheel_probe/b.py": REQUIRED_MODULE,
                }
            ),
            "W002",
        ),
        WheelProbe(
            "W003_root_data",
            wheel_members({**BASE_LIBRARY, "README.txt": b"unexpected data"}),
            "W003",
        ),
        WheelProbe(
            "W004_unimportable_path",
            wheel_members({**BASE_LIBRARY, "wheel_probe/not-importable!.py": b"value = 1\n"}),
            "W004",
        ),
        WheelProbe(
            "W005_common_name",
            wheel_members({**BASE_LIBRARY, "tests/__init__.py": b"TEST = True\n"}),
            "W005",
        ),
        WheelProbe(
            "W006_root_initializer",
            wheel_members({**BASE_LIBRARY, "__init__.py": b"ROOT = True\n"}),
            "W006",
        ),
        WheelProbe(
            "W007_no_library",
            wheel_members({"wheel_probe-1.0.data/scripts/probe": b"script"}),
            "W007",
        ),
        WheelProbe("W008_empty_wheel", wheel_members({}), "W008"),
        WheelProbe(
            "W009_multiple_packages",
            wheel_members({**BASE_LIBRARY, "extra_probe/__init__.py": b"EXTRA = True\n"}),
            "W009",
        ),
        WheelProbe(
            "W010_nonmodule_directory",
            wheel_members({**BASE_LIBRARY, "assets/image.dat": b"asset"}),
            "W010",
        ),
        WheelProbe("W101_missing_source_file", valid, "W101", package_arguments),
        WheelProbe(
            "W102_extra_library_file",
            wheel_members(
                {
                    **BASE_LIBRARY,
                    "wheel_probe/required.py": REQUIRED_MODULE,
                    "wheel_probe/extra.py": b"EXTRA = 1\n",
                }
            ),
            "W102",
            package_arguments,
        ),
        WheelProbe(
            "W201_missing_toplevel", valid, "W201", ("--toplevel", "wheel_probe,missing_probe")
        ),
        WheelProbe(
            "W202_extra_toplevel",
            wheel_members({**BASE_LIBRARY, "extra_probe.py": b"EXTRA = 2\n"}),
            "W202",
            ("--toplevel", "wheel_probe"),
        ),
        WheelProbe(
            "missing_wheel_metadata",
            {name: data for name, data in valid.items() if name != WHEEL},
            "structure",
        ),
        WheelProbe(
            "missing_record",
            {name: data for name, data in valid.items() if name != RECORD},
            "structure",
        ),
        WheelProbe(
            "invalid_root_header",
            wheel_members(BASE_LIBRARY, header=NORMAL_HEADER.replace(b"true", b"maybe")),
            "structure",
        ),
        WheelProbe(
            "missing_root_header",
            wheel_members(BASE_LIBRARY, header=b"Wheel-Version: 1.0\n"),
            "structure",
        ),
        WheelProbe(
            "mismatched_dist_info",
            {
                name.replace(DIST_INFO, "wrong_probe-1.0.dist-info"): data
                for name, data in valid.items()
            },
            "structure",
        ),
        WheelProbe(
            "multiple_dist_info",
            {**valid, "wrong_probe-1.0.dist-info/METADATA": b"Name: wrong-probe\n"},
            "structure",
        ),
        WheelProbe(
            "mismatched_data_directory",
            wheel_members({**BASE_LIBRARY, "wrong_probe-1.0.data/scripts/run": b"script"}),
            "structure",
        ),
        WheelProbe(
            "record_parent_escape",
            {**valid, RECORD: valid[RECORD] + b"../escape.py,,\n"},
            "structure",
        ),
        WheelProbe(
            "record_absolute_path",
            {**valid, RECORD: valid[RECORD] + b"/escape.py,,\n"},
            "structure",
        ),
        WheelProbe(
            "record_invalid_size",
            {**valid, RECORD: b"wheel_probe/__init__.py,,invalid\n"},
            "structure",
        ),
        WheelProbe(
            "record_duplicate_entry",
            {**valid, RECORD: valid[RECORD] + b"wheel_probe/__init__.py,,\n"},
            "structure",
        ),
        WheelProbe("invalid_filename", valid, "filename", filename="invalid.whl"),
        WheelProbe("invalid_zip_archive", {}, "archive", raw_archive=b"not a zip archive"),
    )


def prepare_probe_tree(root: Path) -> tuple[WheelProbe, ...]:
    package = root / "source" / "wheel_probe"
    package.mkdir(parents=True)
    (package / "__init__.py").write_bytes(BASE_LIBRARY["wheel_probe/__init__.py"])
    (package / "required.py").write_bytes(REQUIRED_MODULE)
    return wheel_probes(package)


def write_probe(root: Path, probe: WheelProbe) -> Path:
    directory = root / probe.name
    directory.mkdir()
    path = directory / probe.filename
    if probe.raw_archive is not None:
        path.write_bytes(probe.raw_archive)
    else:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(probe.members.items()):
                archive.writestr(name, data)
    return path


def run_checker(path: Path, arguments: Sequence[str] = ()) -> CheckerOutcome:
    result = subprocess.run(  # noqa: S603 - fixed interpreter/module and synthetic fixture paths
        [sys.executable, "-m", "check_wheel_contents", *arguments, str(path)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=15,
    )
    output = result.stdout + result.stderr
    checks = tuple(sorted(set(re.findall(r"\bW\d{3}\b", output))))
    category = "other"
    if result.returncode == 0:
        category = "pass"
    elif checks:
        category = "checks"
    elif "invalid filename" in output:
        category = "filename"
    elif "invalid wheel:" in output:
        category = "structure"
    elif "BadZipFile" in output:
        category = "archive"
    return CheckerOutcome(result.returncode, checks, category)
