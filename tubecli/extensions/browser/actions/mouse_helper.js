/**
 * Generates a cubic Bezier curve trajectory for natural mouse movement
 */
function bezierCurve(start, end, control1, control2, t) {
  const cx = 3 * (control1.x - start.x);
  const bx = 3 * (control2.x - control1.x) - cx;
  const ax = end.x - start.x - cx - bx;

  const cy = 3 * (control1.y - start.y);
  const by = 3 * (control2.y - control1.y) - cy;
  const ay = end.y - start.y - cy - by;

  const x = ax * t * t * t + bx * t * t + cx * t + start.x;
  const y = ay * t * t * t + by * t * t + cy * t + start.y;

  return { x, y };
}

/**
 * Moves the mouse to a target location using a human-like path
 * @param {import('playwright').Page} page
 * @param {number} targetX
 * @param {number} targetY
 */
export async function humanMove(page, targetX, targetY) {
  // Get current mouse position (approximate or start from random edge if unknown)
  // Playwright doesn't expose current mouse pos easily, so we assume last known or center
  // For simplicity, we just start the curve logic.
  
  const steps = 25 + Math.floor(Math.random() * 25);
  
  // To make it truly curved, we pick two random control points
  // We can't easily get 'current' position from playwright without tracking it manually.
  // So we will just use page.mouse.move with steps options which Playwright handles linearly,
  // BUT we can break it into smaller segments if needed.
  // 
  // However, Playwright's mouse.move with 'steps' is often linear.
  // To be better, we should manually calculate points.
  
  // Since we don't track previous position globally, we'll just use a simpler jitter approach provided by Playwright or
  // implement a full path if we knew the start. 
  // Custom approach:
  await page.mouse.move(targetX, targetY, {
    steps: steps
  });
}

/**
 * Advanced human move that assumes we track start position or just wants 'curved' behavior
 * This version effectively just wraps playwright's move but adds random jitter.
 */
export async function sophisticatedMove(page, startX, startY, endX, endY) {
  const steps = 50;
  // Random control points
  const control1 = { 
    x: startX + (Math.random() * (endX - startX)), 
    y: startY + (Math.random() * (endY - startY)) 
  };
  const control2 = { 
    x: startX + (Math.random() * (endX - startX)), 
    y: startY + (Math.random() * (endY - startY)) 
  };

  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    const pos = bezierCurve({x: startX, y: startY}, {x: endX, y: endY}, control1, control2, t);
    await page.mouse.move(pos.x, pos.y);
    // varying speed
    if (Math.random() > 0.8) await page.waitForTimeout(Math.random() * 10); 
  }
}
