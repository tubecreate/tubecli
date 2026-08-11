import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

// Asked once per process, not once per poll.
//
// A machine either has nvidia-smi or it does not, and that answer never changes
// while the process runs. Retrying on every call spawned a shell each time and
// printed a warning each time, so a headless VPS with no GPU produced an endless
// column of
//
//   [GPUMonitor] Could not get GPU usage: Command failed: nvidia-smi ...
//   /bin/sh: 1: nvidia-smi: not found
//
// That is worse than noise: the run log keeps only the last 2000 characters of
// a session's output, so this reliably pushed the actual failure — the reason
// someone opens the log at all — out of view.
let available = null;   // null = not asked yet, then true/false
let warned = false;

/**
 * Get current NVIDIA GPU utilization percentage.
 * Returns 0 on any machine without an NVIDIA GPU, which is the same answer the
 * caller acted on before — this only stops it costing a process and a log line.
 * @returns {Promise<number>} Usage percentage (0-100)
 */
export async function getGpuUsage() {
  if (available === false) return 0;

  try {
    const { stdout } = await execAsync(
      'nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits');
    available = true;
    const usage = parseInt(stdout.trim(), 10);
    return isNaN(usage) ? 0 : usage;
  } catch (error) {
    // ENOENT / "not found" means there is no NVIDIA tooling here at all: stop
    // asking. Any other failure (a driver hiccup, a busy device) might pass next
    // time, so leave the door open for it.
    const msg = String(error && error.message || '');
    const missing = /not found|ENOENT|is not recognized/i.test(msg);
    if (missing) {
      available = false;
      if (!warned) {
        warned = true;
        console.log('[GPUMonitor] No NVIDIA GPU on this machine — GPU-aware pacing disabled.');
      }
    } else if (!warned) {
      warned = true;
      console.warn('[GPUMonitor] Could not read GPU usage:', msg.split('\n')[0]);
    }
    return 0;
  }
}
