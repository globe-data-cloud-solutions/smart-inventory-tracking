// Open each logged verify-email link (dev email mode) in the browser, then report the page text.
const { chromium } = require(process.env.E2E_PLAYWRIGHT_MODULE || 'playwright');
const CHROME = process.env.E2E_CHROMIUM;
const fs = require('fs');
const SCR = process.argv[2];
const log = fs.readFileSync(process.env.E2E_TENANT_LOG || `${SCR}/logs/tenant-service.log`, 'utf8');
const links = {};
for (const m of log.matchAll(/\[DEV EMAIL\] verify (\S+): (\S+verify-email\?token=\S+)/g)) links[m[1]] = m[2];
(async () => {
  const b = await chromium.launch({ ...(CHROME ? { executablePath: CHROME } : {}), headless: true });
  const out = {};
  for (const email of ['admin@tc01.com', 'admin@tc02.com', 'admin@tc03.com']) {
    const p = await b.newPage();
    await p.goto(links[email], { waitUntil: 'networkidle', timeout: 90000 });
    await p.waitForTimeout(1500);
    out[email] = (await p.innerText('body')).replace(/\s+/g, ' ').slice(0, 160);
    await p.close();
  }
  await b.close();
  console.log(JSON.stringify(out, null, 2));
})().catch(e => { console.error('VERIFY FAIL', e.message); process.exit(1); });
