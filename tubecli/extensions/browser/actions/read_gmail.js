import { navigate } from './navigate.js';

/**
 * Specialized action to read Gmail emails
 * 
 * @param {import('playwright').Page} page
 * @param {object} params { view, maxMails }
 */
export async function read_gmail(page, params = {}) {
  const view = params.view || 'unread';
  const maxMails = params.maxMails || 3;
  
  console.log(`[READ_GMAIL] Starting extraction for view: ${view}`);

  // Base Gmail URL
  let targetUrl = 'https://mail.google.com/mail/u/0/';
  
  if (view === 'unread') {
      targetUrl += '#search/is%3Aunread';
  } else if (view === 'starred') {
      targetUrl += '#starred';
  } else if (view === 'recent') {
      targetUrl += '#inbox';
  } else {
      targetUrl += '#inbox';
  }

  // Navigate to the list
  await navigate(page, { url: targetUrl });
  
  // Wait for emails to load
  try {
      if (view === 'unread') {
          await page.waitForSelector('tr.zA.zE', { timeout: 10000 });
      } else {
          await page.waitForSelector('tr.zA', { timeout: 10000 });
      }
  } catch (e) {
      console.log(`[READ_GMAIL] No emails found for view '${view}' or timed out.`);
      return { content: `No emails found for view: ${view}` };
  }

  // Get rows depending on view
  let rows;
  if (view === 'unread') {
      rows = await page.$$('tr.zA.zE');
  } else {
      rows = await page.$$('tr.zA');
  }

  if (rows.length === 0) {
      console.log(`[READ_GMAIL] Inbox is empty or no matching emails.`);
      return { content: `0 matching emails found for view: ${view}` };
  }

  const emailsToRead = rows.slice(0, maxMails);
  console.log(`[READ_GMAIL] Found ${rows.length} emails. Reading top ${emailsToRead.length}...`);

  let aggregatedContent = `--- GMAIL EXTRACT (${view.toUpperCase()}) ---\n`;

  for (let i = 0; i < emailsToRead.length; i++) {
      console.log(`[READ_GMAIL] Processing email ${i + 1}/${emailsToRead.length}...`);
      try {
          // Re-query the row because DOM might change after navigating back and forth
          const currentRows = await page.$$(view === 'unread' ? 'tr.zA.zE' : 'tr.zA');
          if (i >= currentRows.length) break;
          const row = currentRows[i];

          // Click the email
          await row.click();
          
          // Wait for email body to load
          await page.waitForSelector('.hP', { timeout: 5000 }); // Title
          await page.waitForSelector('.a3s', { timeout: 5000 }); // Body
          
          const emailData = await page.evaluate(() => {
              const titleEl = document.querySelector('.hP');
              const senderEl = document.querySelector('.gD');
              const bodyEl = document.querySelector('.a3s');
              const timeEl = document.querySelector('.g3'); // Timestamp
              
              const title = titleEl ? titleEl.innerText : 'Unknown Title';
              const sender = senderEl ? senderEl.innerText : 'Unknown Sender';
              const senderEmail = senderEl ? senderEl.getAttribute('email') : 'Unknown Email';
              const body = bodyEl ? bodyEl.innerText : 'Empty Body';
              const time = timeEl ? timeEl.innerText : 'Unknown Time';
              
              // Look for any links that might be confirmation codes or important actions
              const links = Array.from(document.querySelectorAll('.a3s a')).slice(0, 5).map(a => a.href);

              return { title, sender, senderEmail, time, body, links };
          });
          
          aggregatedContent += `\n[Email ${i + 1}]\n`;
          aggregatedContent += `From: ${emailData.sender} <${emailData.senderEmail}>\n`;
          aggregatedContent += `Time: ${emailData.time}\n`;
          aggregatedContent += `Subject: ${emailData.title}\n`;
          aggregatedContent += `Content:\n${emailData.body.substring(0, 3000)}\n`; // Limit body size
          
          if (emailData.links.length > 0) {
              aggregatedContent += `Links found:\n${emailData.links.join('\n')}\n`;
          }
          aggregatedContent += `-------------------------------------------\n`;

          console.log(`[READ_GMAIL] Extracted: ${emailData.title}`);

          // Go back to the list
          await page.goBack({ waitUntil: 'domcontentloaded' });
          
          // Wait a bit for the list to re-render
          await page.waitForTimeout(2000);

      } catch (e) {
          console.log(`[READ_GMAIL] Error reading email ${i + 1}: ${e.message}`);
          // Attempt to go back if stuck
          try {
             await page.goBack({ waitUntil: 'domcontentloaded' });
          } catch(err) {}
      }
  }

  console.log(`[READ_GMAIL] Extraction complete. Aggregated ${aggregatedContent.length} chars.`);
  return { content: aggregatedContent };
}
