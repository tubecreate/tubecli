import { plugin } from 'playwright-with-fingerprints';
console.log('Plugin version:', plugin.version);
console.log('versions method:', typeof plugin.versions);
console.log('fetch method:', typeof plugin.fetch);

if (typeof plugin.versions === 'function') {
    try {
        const v = await plugin.versions('extended');
        console.log('Versions result (first 2):', v.slice(0, 2));
    } catch (e) {
        console.error('versions() failed:', e.message);
    }
} else {
    // Check if it's on default export
    import fp from 'playwright-with-fingerprints';
    console.log('Default export keys:', Object.keys(fp));
    console.log('Default export plugin versions:', typeof fp.plugin?.versions);
}
process.exit(0);
