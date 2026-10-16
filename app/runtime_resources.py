"""Share the CPU budget between the sequential audio/Whisper/render stages."""
import logging
import math
import os
import sys
from pathlib import Path

logger = logging.getLogger("karaoke")


def _positive_int(value):
    try:
        result = int(value)
        return result if result > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def _cgroup_cpu_limits():
    """Read v1/v2 quotas, including nested process groups and their parents."""
    roots = {Path("/sys/fs/cgroup")}
    legacy_roots = {Path("/sys/fs/cgroup/cpu"), Path("/sys/fs/cgroup/cpu,cpuacct")}
    for entry in _read_text("/proc/self/cgroup").splitlines():
        fields = entry.split(":", 2)
        if len(fields) != 3 or ".." in Path(fields[2]).parts:
            continue
        controllers, relative = fields[1].split(","), fields[2].lstrip("/")
        if fields[1] == "":
            root = Path("/sys/fs/cgroup")
            group = root / relative
            roots.update([group, *(p for p in group.parents if p.is_relative_to(root))])
        elif "cpu" in controllers:
            for root in tuple(legacy_roots):
                group = root / relative
                legacy_roots.update([group, *(p for p in group.parents if p.is_relative_to(root))])
    limits = []
    for root in roots:
        values = _read_text(root / "cpu.max").split()
        if len(values) == 2:
            quota, period = map(_positive_int, values)
            if quota and period:
                limits.append(max(1, math.ceil(quota / period)))
    for root in legacy_roots:
        quota = _positive_int(_read_text(root / "cpu.cfs_quota_us"))
        period = _positive_int(_read_text(root / "cpu.cfs_period_us"))
        if quota and period:
            limits.append(max(1, math.ceil(quota / period)))
    return limits


def available_cpu_threads(requested=None) -> int:
    """Use all assigned CPUs without multiplying pools beyond the container budget."""
    host_count = os.cpu_count()
    candidates = [host_count] if host_count else []
    try:
        affinity = len(os.sched_getaffinity(0))
        if affinity:
            candidates.append(affinity)
    except (AttributeError, OSError):
        pass
    candidates.extend(_cgroup_cpu_limits())
    if not candidates:
        candidates.append(1)
    for setting in (os.environ.get("KARAOKE_CPU_THREADS"), requested):
        value = _positive_int(setting)
        if value:
            candidates.append(value)
    return max(1, min(candidates))


def thread_environment(threads=None, env=None):
    """Configure child numerical libraries consistently, without changing the server."""
    result = dict(os.environ if env is None else env)
    count = available_cpu_threads(threads)
    for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        result[key] = str(count)
    result["OMP_DYNAMIC"] = "FALSE"
    result["MKL_DYNAMIC"] = "FALSE"
    # Sleeping workers leave the web server time to respond between tensor ops.
    result.setdefault("OMP_WAIT_POLICY", "PASSIVE")
    return result


def release_cached_whisper():
    """Release a loaded Whisper without importing its heavy dependencies."""
    transcriber = sys.modules.get("transcriber")
    if transcriber is not None and hasattr(transcriber, "clear_cached_model"):
        transcriber.clear_cached_model()


def whisper_runtime_options(quality_mode="standard", cpu_threads=None, device=None):
    """Choose only compute types supported by the installed CTranslate2 backend."""
    high_quality = "max" in str(quality_mode).lower()
    requested_device = device or os.environ.get("WHISPER_DEVICE", "auto")
    device = "cpu"
    supported = {"int8", "int8_float32", "float32"}
    try:
        import ctranslate2
        supported = ctranslate2.get_supported_compute_types("cpu")
        requested = str(requested_device).strip().lower()
        if requested in {"auto", "cuda"} and ctranslate2.get_cuda_device_count() > 0:
            cuda_types = ctranslate2.get_supported_compute_types("cuda")
            if cuda_types:
                device, supported = "cuda", cuda_types
    except Exception as error:
        logger.debug("Detecção de recursos CTranslate2 indisponível; usando CPU: %s", error)
    if device == "cuda":
        choices = ("float16", "float32") if high_quality else ("int8_float16", "float16", "int8_float32", "float32")
    else:
        choices = ("float32", "int8_float32", "int8") if high_quality else ("int8", "int8_float32", "float32")
    compute_type = next((choice for choice in choices if choice in supported), "float32")
    configured_compute = os.environ.get("WHISPER_COMPUTE_TYPE", "").strip()
    if configured_compute and configured_compute in supported:
        compute_type = configured_compute
    return dict(device=device, compute_type=compute_type,
                cpu_threads=available_cpu_threads(cpu_threads), num_workers=1)
