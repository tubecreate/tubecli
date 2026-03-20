import { search } from './search.js';

export async function search_extract(page, params) {
    console.log(`[SearchExtract] Starting search for: ${params.keyword}`);
    
    // Re-use the existing robust search logic
    await search(page, params);
    
    console.log(`[SearchExtract] Extracting results from page...`);
    
    // After search completes, ensure results are loaded and wait a bit
    await page.waitForTimeout(2000);
    
    // Extract text from the page (e.g., search result snippets)
    const extractedData = await page.evaluate(() => {
        // Collect headings and snippets from Google search results
        const results = Array.from(document.querySelectorAll('.g, .VwiC3b, .BNeawe, .wob_t'));
        let text = '';
        const seen = new Set();
        
        for (const el of results) {
            const inner = el.innerText.trim();
            if (inner && inner.length > 20 && !seen.has(inner)) {
                text += inner + '\n---\n';
                seen.add(inner);
            }
        }
        return text.substring(0, 3000); // Limit to 3000 chars to avoid overwhelming LLM context
    });
    
    console.log('<<<SEARCH_RESULT_START>>>');
    console.log(extractedData || "No clear text snippets found.");
    console.log('<<<SEARCH_RESULT_END>>>');
}
