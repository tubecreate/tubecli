import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

/**
 * Get current NVIDIA GPU utilization percentage
 * @returns {Promise<number>} Usage percentage (0-100)
 */
export async function getGpuUsage() {
  try {
    // Query NVIDIA GPU utilization using nvidia-smi
    const { stdout } = await execAsync('nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits');
    const usage = parseInt(stdout.trim());
    if (isNaN(usage)) return 0;
    return usage;
  } catch (error) {
    // If nvidia-smi is not available or fails
    console.warn('[GPUMonitor] Could not get GPU usage:', error.message);
    return 0; // Fallback to 0 to avoid breaking logic
  }
}
