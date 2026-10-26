import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from typing import Dict, Any, List, Tuple, Optional
import psutil

from config import settings

logger = logging.getLogger("Sandbox")

def kill_process_tree(pid: int) -> None:
    """Terminates a process and all its spawned children (e.g., Chromium instances)."""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        parent.terminate()
        gone, alive = psutil.wait_procs(children + [parent], timeout=2.0)
        for p in alive:
            try:
                p.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

def get_effective_tree_memory_mb(pid: int) -> Tuple[float, float, int]:
    """
    Calculates the true physical memory consumption of the process tree.
    - On Linux (Render containers): reads cgroup memory if available (matches Render's OOM killer).
    - On macOS / local dev: deduplicates shared dynamic library pages across Chromium helper processes.
    """
    # 1. Check Linux cgroups (Render Debian container)
    for cgroup_path in ("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory/memory.usage_in_bytes"):
        if os.path.exists(cgroup_path):
            try:
                with open(cgroup_path, "r") as f:
                    val = int(f.read().strip())
                    if val > 0:
                        cgroup_mb = val / (1024 * 1024)
                        return cgroup_mb, cgroup_mb, 0
            except Exception:
                pass

    # 2. Process tree traversal
    try:
        parent_proc = psutil.Process(pid)
        parent_rss = parent_proc.memory_info().rss
        children = parent_proc.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0.0, 0.0, 0

    raw_total_rss = parent_rss
    for child in children:
        try:
            raw_total_rss += child.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    raw_mb = raw_total_rss / (1024 * 1024)
    num_children = len(children)

    # 3. Deduplicate shared dynamic libraries on macOS/local dev:
    # Each Chromium helper process shares the large Chromium Framework (~55-60MB each).
    # Deducting that duplicated shared overhead yields the true unshared physical RAM.
    if num_children > 1:
        shared_deduction_mb = (num_children - 1) * 55.0
        effective_mb = max(parent_rss / (1024 * 1024), raw_mb - shared_deduction_mb)
    else:
        effective_mb = raw_mb

    return effective_mb, raw_mb, num_children


_active_sandbox_proc: Optional[asyncio.subprocess.Process] = None
_sandbox_abort_requested = False

def cancel_active_sandbox() -> bool:
    """
    Instantly aborts and terminates any actively executing adapter subprocess
    and its full descendant process tree (Playwright Node, Chromium helpers).
    """
    global _active_sandbox_proc, _sandbox_abort_requested
    _sandbox_abort_requested = True
    if _active_sandbox_proc and _active_sandbox_proc.returncode is None:
        try:
            pid = _active_sandbox_proc.pid
            logger.info(f"[Sandbox] Instant abort requested: terminating active subprocess PID {pid}...")
            kill_process_tree(pid)
            return True
        except Exception as e:
            logger.warning(f"[Sandbox] Exception terminating subprocess during abort: {e}")
    return False

def reset_sandbox_abort():
    """Resets the abort requested flag for a new queue run."""
    global _sandbox_abort_requested
    _sandbox_abort_requested = False


async def run_adapter_in_sandbox(
    portal_id: str,
    max_memory_mb: int = None,
    timeout_secs: int = None
) -> Dict[str, Any]:
    """
    Runs a single adapter inside an isolated subprocess monitored for memory & timeout.
    Guarantees the parent FastAPI process never exceeds memory limits or hangs.
    """
    global _active_sandbox_proc, _sandbox_abort_requested
    max_memory_mb = max_memory_mb or settings.SUBPROCESS_MEMORY_LIMIT_MB
    timeout_secs = timeout_secs or settings.SUBPROCESS_TIMEOUT_SECONDS

    if _sandbox_abort_requested:
        return {
            "success": False,
            "cancelled": True,
            "error": "QUEUE_RESET_ABORT: Abort flag is active",
            "peak_rss_mb": 0.0,
            "elapsed_seconds": 0.0
        }

    # Create temporary file for inter-process JSON result exchange
    temp_fd, temp_path = tempfile.mkstemp(suffix=f"_{portal_id}.json", prefix="scrape_")
    os.close(temp_fd)

    start_time = time.time()
    oom_triggered = False
    timeout_triggered = False
    peak_rss_mb = 0.0

    logger.info(
        f"[Sandbox] Spawning subprocess for '{portal_id}' "
        f"(Max RAM: {max_memory_mb} MB, Timeout: {timeout_secs}s)..."
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "sandbox_runner.py",
            portal_id,
            temp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _active_sandbox_proc = proc

        # Actively monitor RAM (RSS), timeout, and user abort requests every 350ms
        while proc.returncode is None:
            if _sandbox_abort_requested:
                logger.info(f"[Sandbox] User reset/abort flag detected for '{portal_id}'. Killing subprocess tree...")
                kill_process_tree(proc.pid)
                break

            elapsed = time.time() - start_time
            if elapsed > timeout_secs:
                timeout_triggered = True
                logger.warning(f"[Sandbox] Timeout reached ({elapsed:.1f}s > {timeout_secs}s) for '{portal_id}'. Killing...")
                kill_process_tree(proc.pid)
                break

            current_rss_mb, raw_mb, num_children = get_effective_tree_memory_mb(proc.pid)
            if current_rss_mb == 0.0 and proc.returncode is not None:
                break

            if current_rss_mb > peak_rss_mb:
                peak_rss_mb = current_rss_mb

            if current_rss_mb > max_memory_mb:
                oom_triggered = True
                logger.error(
                    f"[Sandbox] MEMORY CEILING BREACHED for '{portal_id}': "
                    f"Effective {current_rss_mb:.1f} MB (Raw: {raw_mb:.1f} MB across {num_children} procs) > {max_memory_mb} MB limit. Killing..."
                )
                kill_process_tree(proc.pid)
                break

            await asyncio.sleep(0.35)

        stdout, stderr = await proc.communicate()
        elapsed_total = time.time() - start_time

        if _sandbox_abort_requested:
            return {
                "success": False,
                "cancelled": True,
                "error": "QUEUE_RESET_ABORT: Execution cancelled by queue reset",
                "peak_rss_mb": peak_rss_mb,
                "elapsed_seconds": elapsed_total
            }

        if oom_triggered:
            return {
                "success": False,
                "error": f"MEMORY_LIMIT_EXCEEDED: Peak RSS reached {peak_rss_mb:.1f} MB (allowed limit: {max_memory_mb} MB)",
                "peak_rss_mb": peak_rss_mb,
                "elapsed_seconds": elapsed_total
            }

        if timeout_triggered:
            return {
                "success": False,
                "error": f"TIMEOUT_EXCEEDED: Scrape exceeded maximum duration of {timeout_secs}s",
                "peak_rss_mb": peak_rss_mb,
                "elapsed_seconds": elapsed_total
            }

        if proc.returncode != 0:
            err_msg = stderr.decode().strip() if stderr else f"Subprocess exited with code {proc.returncode}"
            # Check if temp file has error details
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                try:
                    with open(temp_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if data.get("error"):
                            err_msg = data.get("error")
                except Exception:
                    pass
            return {
                "success": False,
                "error": err_msg,
                "peak_rss_mb": peak_rss_mb,
                "elapsed_seconds": elapsed_total
            }

        # Read output JSON
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            return {
                "success": False,
                "error": "No output data was written by sandbox runner.",
                "peak_rss_mb": peak_rss_mb,
                "elapsed_seconds": elapsed_total
            }

        with open(temp_path, "r", encoding="utf-8") as f:
            output_data = json.load(f)

        if output_data.get("status") == "success":
            listings = output_data.get("listings", [])
            logger.info(
                f"[Sandbox] '{portal_id}' completed in {elapsed_total:.1f}s "
                f"(Peak RAM: {peak_rss_mb:.1f} MB, Scraped: {len(listings)})"
            )
            return {
                "success": True,
                "listings": listings,
                "peak_rss_mb": peak_rss_mb,
                "elapsed_seconds": elapsed_total
            }
        else:
            return {
                "success": False,
                "error": output_data.get("error", "Unknown runner error"),
                "peak_rss_mb": peak_rss_mb,
                "elapsed_seconds": elapsed_total
            }

    except Exception as e:
        logger.error(f"[Sandbox] Unexpected exception running '{portal_id}': {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "peak_rss_mb": peak_rss_mb,
            "elapsed_seconds": time.time() - start_time
        }
    finally:
        _active_sandbox_proc = None
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass


async def run_adapter_with_retries(
    portal_id: str,
    max_memory_mb: int = None,
    timeout_secs: int = None,
    max_retries: int = None
) -> Tuple[bool, List[Dict[str, Any]], Optional[str], int]:
    """
    Runs an adapter with automatic retries up to max_retries.
    Returns: (success: bool, listings: list, error_message: str|None, attempts_used: int)
    """
    max_retries = max_retries if max_retries is not None else settings.MAX_ADAPTER_RETRIES
    total_allowed_attempts = 1 + max_retries

    last_error = None
    for attempt in range(1, total_allowed_attempts + 1):
        if attempt > 1:
            logger.info(f"[Sandbox] Retry attempt #{attempt}/{total_allowed_attempts} for '{portal_id}' after previous failure: {last_error}")
            await asyncio.sleep(2.0)  # Brief pause between retries for OS cleanup

        result = await run_adapter_in_sandbox(
            portal_id=portal_id,
            max_memory_mb=max_memory_mb,
            timeout_secs=timeout_secs
        )

        if result.get("success"):
            return True, result.get("listings", []), None, attempt

        # If user explicitly aborted/reset the queue, exit immediately without retries
        if result.get("cancelled"):
            logger.info(f"[Sandbox] Aborting retries for '{portal_id}' due to queue cancellation.")
            return False, [], "QUEUE_RESET_ABORT", attempt

        last_error = result.get("error", "Unknown error")
        logger.warning(f"[Sandbox] Attempt #{attempt} failed for '{portal_id}': {last_error}")

    return False, [], last_error, total_allowed_attempts
