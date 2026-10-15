"""The parts of the semi-manual image workflow that are not in the repository.

Two kinds of thing are missing from a fresh checkout: Python packages nobody
else in DazedTL needs (numpy, OpenCV, an OCR client) and around 450 MB of
neural-network weights. Neither belongs in ``requirements.txt``, because
everyone who never opens this workflow would pay for both.

So nothing here is fetched until the user asks for it. The local inpainting
bridge (``scripts/image_inpaint.py``) reports what each missing method costs
in its ``status`` and fetches it with ``install``, which works from any folder
because the bridge sets up the engine's import path itself.

Model files are pinned to a repository revision and checked against their
published SHA-256, so a model replaced upstream is refused rather than loaded.

On Windows the models need one thing more: Microsoft's C++ runtime, which
onnxruntime links to and a fresh Windows lacks. ``install`` runs Microsoft's
own Redistributable for it, verified by its signature rather than a pinned
checksum, because Microsoft replaces that download with every runtime update
and the newest one is what every onnxruntime build can run on.

**This module must import on a bare checkout**, before any of it is installed,
because it is what does the installing. Standard library only - no numpy, no
cv2, no PyQt. The rest of ``util.imagetools`` is not importable until
``install`` has run, which is why nothing here imports its siblings.

Downloading works without a restart. New packages land in a ``site-packages``
that is already on ``sys.path``, so ``activate`` only has to drop the import
caches for the interpreter to see them - but that is only true because nothing
imported numpy or cv2 earlier in the session. Every route into the toolkit is a
deferred import inside a function for exactly this reason; a module-level
``import cv2`` anywhere in the always-loaded path would quietly reintroduce the
restart.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import ssl
import struct
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from util.paths import DATA_DIR

#: Where ``util.imagetools.inpaint`` looks. Repeated rather than imported
#: because that module needs numpy and cv2, which may be exactly what is
#: missing.
MODEL_DIR = DATA_DIR / "models"

USER_AGENT = "DazedTL"
#: Big enough that the syscall overhead disappears on a 200 MB model, small
#: enough that a progress bar still moves smoothly.
CHUNK = 256 * 1024
TIMEOUT = 60

HUGGINGFACE = "https://huggingface.co/{repo}/resolve/{revision}/{filename}"

#: Rough wheel sizes, only ever used to fill in the "about this much" line
#: before anything is downloaded. The progress bars use ``Content-Length``.
PIP_SIZES = {
    "numpy": 16_000_000,
    "opencv-python-headless": 40_000_000,
    "chrome-lens-py": 12_000_000,
    "onnxruntime": 24_000_000,
    "pypatchmatch": 650_000,
    "rapidocr-onnxruntime": 15_000_000,
}

#: Microsoft's permanent link to the newest x64 Visual C++ Redistributable.
VC_REDIST_URL = "https://aka.ms/vc14/vc_redist.x64.exe"
#: Its size in October 2026, for the "about this much" line only.
VC_REDIST_SIZE = 18_731_856
#: The parts of that runtime onnxruntime loads besides the vcruntime140 pair
#: that every Python on Windows carries next to itself.
VC_LIBRARIES = ("msvcp140.dll", "msvcp140_1.dll")


class Cancelled(Exception):
    """The user stopped the download."""


@dataclass(frozen=True)
class Resource:
    """One thing that can be fetched, and how to tell whether it is here."""

    key: str
    label: str
    detail: str
    #: Requirement specifiers handed to pip.
    pips: tuple[str, ...] = ()
    #: The import name that proves each pip landed, in the same order. Checked
    #: with ``find_spec``, which does not execute them - importing numpy here
    #: would defeat the whole deferred-import arrangement.
    modules: tuple[str, ...] = ()
    #: A file to download.
    url: str = ""
    dest: Path | None = None
    size: int = 0
    #: The file's published SHA-256; a download that does not match is refused.
    sha256: str = ""
    #: Pre-ticked in the download prompt.
    default: bool = False
    #: The workflow cannot start without it, so it cannot be unticked.
    required: bool = False
    #: Runs on onnxruntime, which needs Microsoft's C++ runtime on Windows.
    cpp_runtime: bool = False

    def missing_pips(self) -> tuple[str, ...]:
        """The requirement specifiers whose import name is not found."""
        return tuple(
            spec
            for spec, module in zip(self.pips, self.modules, strict=True)
            if not importable(module)
        )


RESOURCES: tuple[Resource, ...] = (
    Resource(
        key="core",
        label="Required",
        detail="numpy, OpenCV and the Google Lens OCR client",
        pips=("numpy>=2.0", "opencv-python-headless>=4.10", "chrome-lens-py>=3.4"),
        modules=("numpy", "cv2", "chrome_lens_py"),
        default=True,
        required=True,
    ),
    Resource(
        key="aot",
        label="AOT reconstruction",
        detail="fast neural fill; weaker on saturated colour",
        pips=("onnxruntime>=1.17",),
        modules=("onnxruntime",),
        cpp_runtime=True,
        url=HUGGINGFACE.format(
            repo="ogkalu/aot-inpainting",
            revision="42ffc84ff1bd46dd95f1c5a41e83ee7e98f39189",
            filename="aot.onnx",
        ),
        dest=MODEL_DIR / "aot.onnx",
        size=23_068_213,
        sha256="ffd39ed8e2a275869d3b49180d030f0d8b8b9c2c20ed0e099ecd207201f0eada",
        default=True,
    ),
    Resource(
        key="lama_manga",
        label="LaMa-manga reconstruction",
        detail="LaMa fine-tuned on manga and anime - the best of these on game art",
        pips=("onnxruntime>=1.17",),
        modules=("onnxruntime",),
        cpp_runtime=True,
        url=HUGGINGFACE.format(
            repo="ogkalu/lama-manga-onnx-dynamic",
            revision="ee4ed4a8447b6730fc41d34f90876b6c48af925a",
            filename="lama-manga-dynamic.onnx",
        ),
        dest=MODEL_DIR / "lama-manga-dynamic.onnx",
        size=206_291_843,
        sha256="de31ffa5ba26916b8ea35319f6c12151ff9654d4261bccf0583a69bb095315f9",
    ),
    Resource(
        key="lama",
        label="LaMa reconstruction",
        detail="the original LaMa export, trained on photographs",
        pips=("onnxruntime>=1.17",),
        modules=("onnxruntime",),
        cpp_runtime=True,
        url=HUGGINGFACE.format(
            repo="Carve/LaMa-ONNX",
            revision="c3c0c9e468934d62e79c329e35d82dd09ff8c444",
            filename="lama_fp32.onnx",
        ),
        dest=MODEL_DIR / "lama_fp32.onnx",
        size=208_044_816,
        sha256="1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6",
    ),
    Resource(
        key="patchmatch",
        label="PatchMatch reconstruction",
        detail="best texture of these, and by far the slowest (~4.5s a box)",
        # Its wheels carry the compiled library with OpenCV linked in, for
        # Windows, Linux and macOS alike. Pinned exactly: it is native code
        # from a young release line, so an update is a choice, not a surprise.
        pips=("pypatchmatch==2.1.1",),
        modules=("patchmatch",),
    ),
    Resource(
        key="rapidocr",
        label="Offline OCR",
        detail=(
            "a local fallback for when the Google Lens endpoint is unreachable "
            "(also pulls in the full opencv-python)"
        ),
        # The maintained successor to rapidocr-onnxruntime, which caps out at
        # Python 3.12 - asking for the old name on 3.13 silently resolves to a
        # three-year-old release. util/imagetools/ocr/rapid.py accepts either,
        # so an existing install of the old one keeps working.
        pips=("rapidocr",),
        modules=("rapidocr",),
        size=0,
    ),
)


# ----------------------------------------------------------------- inspection

def available() -> tuple[Resource, ...]:
    """The resources that can be fetched on this machine."""
    return RESOURCES


def get(key: str) -> Resource:
    for resource in RESOURCES:
        if resource.key == key:
            return resource
    raise KeyError(f"No image-workflow resource named {key!r}")


def importable(module: str) -> bool:
    from importlib.util import find_spec

    try:
        return find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def installed(resource: Resource | str) -> bool:
    """Whether everything this resource brings is already present."""
    if isinstance(resource, str):
        resource = get(resource)
    if resource.missing_pips():
        return False
    if resource.cpp_runtime and vc_runtime_problem():
        return False
    return resource.dest is None or resource.dest.is_file()


def missing(keys: list[str] | tuple[str, ...] | None = None) -> list[Resource]:
    """Selected resources that are not fully present, in manifest order."""
    wanted = available() if keys is None else [get(key) for key in keys]
    return [resource for resource in wanted if not installed(resource)]


def ready() -> bool:
    """Whether the workflow can start at all."""
    return all(installed(r) for r in available() if r.required)


def defaults() -> list[str]:
    """The keys pre-ticked in the prompt: required, plus the cheap ones."""
    return [r.key for r in available() if r.default]


def _requirement_name(spec: str) -> str:
    for separator in (">=", "==", "<=", "~=", ">", "<", "!=", "["):
        if separator in spec:
            return spec.split(separator, 1)[0].strip()
    return spec.strip()


def estimate(resources) -> int:
    """Bytes the given resources will roughly cost, counting pips once."""
    total = 0
    seen: set[str] = set()
    for resource in resources:
        if resource.dest is not None and not resource.dest.is_file():
            total += resource.size
        for spec in resource.missing_pips():
            name = _requirement_name(spec)
            if name not in seen:
                seen.add(name)
                total += PIP_SIZES.get(name, 0)
    if any(resource.cpp_runtime for resource in resources) and vc_runtime_problem():
        total += VC_REDIST_SIZE
    return total


# ------------------------------------------------- Microsoft's C++ runtime

def _system_folder() -> Path:
    """Windows' System32, asked of Windows rather than of the environment.

    Helpers can run with a filtered environment that has no ``SystemRoot``.
    """
    import ctypes

    buffer = ctypes.create_unicode_buffer(260)
    ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))  # type: ignore[attr-defined]
    return Path(buffer.value)


def linker_version(path: Path) -> tuple[int, int] | None:
    """The MSVC toolset a Windows DLL was linked with, from its PE header."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(4096)
    except OSError:
        return None
    if head[:2] != b"MZ" or len(head) < 0x40:
        return None
    (offset,) = struct.unpack_from("<I", head, 0x3C)
    # The optional header follows the 4-byte signature and the 20-byte file
    # header; its third and fourth bytes are the linker's major and minor.
    if offset + 28 > len(head) or head[offset : offset + 4] != b"PE\0\0":
        return None
    return head[offset + 26], head[offset + 27]


#: VS_FIXEDFILEINFO's signature and structure version, as stored in a DLL.
_FIXED_FILE_INFO = struct.pack("<II", 0xFEEF04BD, 0x00010000)


def file_version(path: Path) -> tuple[int, int, int, int] | None:
    """A Windows DLL's file version, from the fixed block of its resources."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    at = data.find(_FIXED_FILE_INFO)
    if at < 0 or at + 16 > len(data):
        return None
    high, low = struct.unpack_from("<II", data, at + 8)
    return high >> 16, high & 0xFFFF, low >> 16, low & 0xFFFF


def runtime_problem(needed: tuple[int, int] | None, folders) -> str:
    """What keeps a DLL linked with toolset *needed* from running, or "".

    *folders* are searched in order, as Windows searches for an extension's
    dependencies; the first copy of each library is the one that loads.
    """
    for name in VC_LIBRARIES:
        copy = next(
            (folder / name for folder in folders if (folder / name).is_file()), None
        )
        if copy is None:
            return (
                "this Windows lacks the Microsoft Visual C++ Redistributable (x64) "
                "that onnxruntime needs"
            )
        version = file_version(copy)
        if needed and version and version[:2] < needed:
            return (
                f"onnxruntime needs the Microsoft Visual C++ Redistributable "
                f"{needed[0]}.{needed[1]} or newer, and this Windows has "
                f"{'.'.join(map(str, version))}"
            )
    return ""


def vc_runtime_problem() -> str:
    """Why onnxruntime cannot run on this Windows, or "" when it can.

    onnxruntime's Windows wheels link Microsoft's C++ library (msvcp140)
    dynamically. The Python DazedTL installs carries only vcruntime140, so on a
    fresh Windows the import fails with "DLL load failed". A runtime older than
    the toolset onnxruntime was built with is worse: it can load and then crash
    the process. So this reads the files instead of importing anything. Before
    onnxruntime is installed, only a missing runtime can be told.
    """
    if sys.platform != "win32":
        return ""
    from importlib.util import find_spec

    try:
        spec = find_spec("onnxruntime")
    except (ImportError, ValueError):
        spec = None
    capi = Path(spec.origin).parent / "capi" if spec and spec.origin else None
    # The extension's own folder, the Python beside the executable, then
    # System32.
    folders = [Path(sys.base_prefix), _system_folder()]
    if capi:
        folders.insert(0, capi)
    return runtime_problem(
        linker_version(capi / "onnxruntime.dll") if capi else None, folders
    )


def human(size: int) -> str:
    if size >= 1_000_000_000:
        return f"{size / 1_000_000_000:.1f} GB"
    if size >= 1_000_000:
        return f"{size / 1_000_000:.0f} MB"
    if size >= 1_000:
        return f"{size / 1_000:.0f} KB"
    return f"{size} bytes"


# -------------------------------------------------------------- installation

def _log(log, message: str) -> None:
    if log is None:
        print(message, flush=True)
    else:
        log(message)


def _check(should_stop) -> None:
    if should_stop is not None and should_stop():
        raise Cancelled("Download stopped.")


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _pip(specs, log=None, should_stop=None) -> None:
    """Install requirement specifiers into *this* interpreter.

    ``sys.executable -m pip``, never bare ``pip``: the ``Scripts\\*.exe`` shims
    hardcode the interpreter they were built against, so in a virtualenv that
    was copied rather than created in place, bare ``pip`` installs into
    whichever tree the copy came from and the caller then reports the package
    as missing forever.
    """
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        *specs,
    ]
    _log(log, "$ " + " ".join(command))
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_no_window(),
    )
    try:
        for line in process.stdout or ():
            line = line.rstrip()
            if line:
                _log(log, line)
            if should_stop is not None and should_stop():
                process.terminate()
                raise Cancelled("Download stopped.")
    finally:
        code = process.wait()
    if code:
        raise RuntimeError(
            f"pip exited {code}. The lines above say why; a proxy or a missing "
            "wheel for this Python version are the usual causes."
        )


def _tls() -> ssl.SSLContext:
    """A context that can verify the download servers on every platform.

    The Python DazedTL installs on Windows brings no certificate authorities of
    its own, so urllib's default context refused every HTTPS download there
    ("unable to get local issuer certificate") while pip, which carries its
    own, worked. The system's store comes first, so a proxy's certificate
    that the machine trusts is trusted here too.
    """
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        pass
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _fetch(
    url: str, dest: Path, sha256: str = "", progress=None, log=None, should_stop=None
) -> None:
    """Download to ``<dest>.part``, check it, then rename.

    The rename is the only thing that publishes the file, so an interrupted
    or altered download can never be mistaken for a complete one - which for
    a 200 MB model would surface much later as an unreadable ONNX graph.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    _log(log, f"Downloading {dest.name}")
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=_tls()) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with open(part, "wb") as handle:
                while True:
                    _check(should_stop)
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
        if total and done != total:
            raise OSError(
                f"{dest.name} stopped short: {done} of {total} bytes. "
                "Nothing was kept."
            )
        if sha256 and digest.hexdigest() != sha256:
            raise OSError(
                f"{dest.name} does not match its published checksum. "
                "Nothing was kept."
            )
        part.replace(dest)
        _log(log, f"{dest.name} ready ({human(done)})")
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def _check_signature(path: Path) -> None:
    """Refuse a file that Microsoft did not sign, or whose signature is broken."""
    powershell = _system_folder() / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    # The path travels in the environment, so no quoting can reinterpret it.
    script = (
        "$s = Get-AuthenticodeSignature -LiteralPath $env:DAZEDTL_SIGNED; "
        "[Console]::Out.Write([string]$s.Status + \"`n\" + "
        "$s.SignerCertificate.Subject)"
    )
    try:
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            errors="replace",
            env={**os.environ, "DAZEDTL_SIGNED": str(path)},
            creationflags=_no_window(),
            timeout=120,
        )
        status, _, subject = result.stdout.partition("\n")
    except (OSError, subprocess.SubprocessError) as exc:
        status, subject = f"unreadable ({exc})", ""
    if status.strip() != "Valid" or "O=Microsoft Corporation" not in subject:
        raise OSError(
            f"{path.name} does not carry a valid Microsoft signature "
            f"({status.strip() or 'unreadable'}), so it was not run."
        )


#: Exit codes of Microsoft's installer that leave the runtime in place:
#: success, success pending a restart, and a newer runtime already installed.
_VC_REDIST_DONE = (0, 3010, 1638)
#: The user said no, in the installer or at Windows' administrator prompt.
_VC_REDIST_DECLINED = (1602, 1223)


def install_vc_runtime(progress=None, log=None, should_stop=None) -> None:
    """Install Microsoft's C++ runtime when onnxruntime cannot run without it.

    Microsoft's installer asks Windows for administrator rights, so the user
    sees one Windows prompt; nothing else here needs one.
    """
    problem = vc_runtime_problem()
    if not problem:
        return
    _log(log, f"- Microsoft Visual C++ Redistributable: {problem}")
    # One fixed folder, emptied first, so an install stopped while Windows'
    # prompt was open leaves no installer behind for long.
    folder = Path(tempfile.gettempdir()) / "dazedtl-vc-redist"
    shutil.rmtree(folder, ignore_errors=True)
    installer = folder / "vc_redist.x64.exe"
    try:
        _fetch(
            VC_REDIST_URL, installer, progress=progress, log=log, should_stop=should_stop
        )
        _check_signature(installer)
        _check(should_stop)
        _log(
            log,
            "Running Microsoft's installer; Windows asks for administrator "
            "permission",
        )
        code = subprocess.run(
            [str(installer), "/install", "/passive", "/norestart"], check=False
        ).returncode
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if code in _VC_REDIST_DECLINED:
        raise Cancelled(
            "The Microsoft Visual C++ Redistributable was not installed because "
            "its installer or the administrator prompt was declined."
        )
    if code not in _VC_REDIST_DONE:
        raise RuntimeError(
            f"Microsoft's Visual C++ Redistributable installer exited {code}. "
            f"Its log is in {tempfile.gettempdir()} (dd_vcredist_amd64_*.log); "
            f"it can also be installed by hand from {VC_REDIST_URL}"
        )
    problem = vc_runtime_problem()
    if problem:
        raise RuntimeError(
            f"Microsoft's installer finished (exit {code}), but {problem}"
            + (". Restart Windows, then check again." if code == 3010 else ".")
        )
    _log(log, "Microsoft Visual C++ Redistributable ready")


def activate() -> None:
    """Make freshly installed packages importable without a restart."""
    import importlib
    import site

    candidates: list[str] = []
    try:
        candidates.extend(site.getsitepackages())
    except AttributeError:  # a virtualenv old enough to lack it
        pass
    try:
        user = site.getusersitepackages()
    except Exception:
        user = None
    if user:
        candidates.append(user)
    for path in candidates:
        if path and path not in sys.path:
            sys.path.append(path)
    importlib.invalidate_caches()


def install(resources, progress=None, log=None, should_stop=None) -> None:
    """Fetch everything in *resources*, in order.

    ``progress(key, done, total)`` is called as bytes arrive, with ``total``
    zero while a step has no measurable length (pip does not report one).
    Raises on the first failure - a half-installed set is reported honestly
    rather than papered over, and every step is safe to run again.
    """
    handled: set[str] = set()
    for resource in resources:
        _check(should_stop)
        if progress is not None:
            progress(resource.key, 0, 0)

        specs = [
            spec
            for spec in resource.missing_pips()
            if _requirement_name(spec) not in handled
        ]
        if specs:
            _log(log, f"- {resource.label}: installing {', '.join(specs)}")
            _pip(specs, log=log, should_stop=should_stop)
            activate()
        for spec in resource.pips:
            handled.add(_requirement_name(spec))
        # After pip, so the check knows which toolset the onnxruntime just
        # installed needs; before the model, which is useless without it.
        if resource.cpp_runtime and "vc_redist" not in handled:
            handled.add("vc_redist")
            install_vc_runtime(
                progress=lambda done, total, key=resource.key: (
                    progress(key, done, total) if progress else None
                ),
                log=log,
                should_stop=should_stop,
            )

        if resource.dest is None:
            continue
        if resource.dest.is_file():
            _log(log, f"- {resource.label}: already here")
            continue

        _check(should_stop)
        _fetch(
            resource.url,
            resource.dest,
            resource.sha256,
            progress=lambda done, total, key=resource.key: (
                progress(key, done, total) if progress else None
            ),
            log=log,
            should_stop=should_stop,
        )

    activate()


# ----------------------------------------------------------------------- CLI

def _report(log=print) -> None:
    log("Semi-manual image workflow - extra resources\n")
    for resource in available():
        mark = "installed" if installed(resource) else "missing"
        size = human(estimate([resource])) if not installed(resource) else "-"
        log(f"  {resource.key:<12} {mark:<10} {size:>8}   {resource.label}")
        log(f"  {'':<12} {resource.detail}")
    log("")
    log(f"  Workflow can start: {'yes' if ready() else 'no'}")


def main(argv: list[str] | None = None) -> int:
    # pip's output is not ASCII and this console may not be UTF-8 - a Japanese
    # Windows console is cp932, where one stray character in a wheel's name
    # would otherwise end the install with a UnicodeEncodeError.
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    argv = list(sys.argv[1:] if argv is None else argv)
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        print(
            "Usage: python -m util.imagetools.resources "
            "[--all | --default | KEY ...]"
        )
        return 0

    if "--all" in argv:
        chosen = list(available())
    elif "--default" in argv:
        chosen = [r for r in available() if r.default]
    else:
        keys = [arg for arg in argv if not arg.startswith("-")]
        if not keys:
            _report()
            return 0
        try:
            chosen = [get(key) for key in keys]
        except KeyError as exc:
            print(exc)
            return 1

    wanted = [r for r in chosen if not installed(r)]
    if not wanted:
        print("Everything asked for is already installed.")
        return 0

    print(f"About {human(estimate(wanted))} to download:")
    for resource in wanted:
        print(f"  - {resource.label}")
    print()

    last = [-1]

    def progress(key: str, done: int, total: int) -> None:
        if not total:
            return
        percent = done * 100 // total
        if percent != last[0]:
            last[0] = percent
            print(f"\r  {key}: {percent}%", end="", flush=True)
            if percent == 100:
                print()

    try:
        install(wanted, progress=progress, log=print)
    except Cancelled:
        print("\nStopped.")
        return 1
    except Exception as exc:
        print(f"\nFailed: {type(exc).__name__}: {exc}")
        return 1
    print("\nDone. DazedTL does not need restarting.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
