// Sign up TenantC01..C03 through the public 3-step wizard (Enterprise, monthly).
const { chromium } = require(process.env.E2E_PLAYWRIGHT_MODULE || 'playwright');
const CHROME = process.env.E2E_CHROMIUM;
const WEB = process.env.E2E_WEB_BASE || 'http://localhost:3000';
const fs = require('fs');
const SCR = process.argv[2];
const TENANTS = [
  { n: 'C01', name: 'TenantC01', email: 'admin@tc01.com' },
  { n: 'C02', name: 'TenantC02', email: 'admin@tc02.com' },
  { n: 'C03', name: 'TenantC03', email: 'admin@tc03.com' },
];
const PASSWORD = 'smart1026';
(async () => {
  const b = await chromium.launch({ ...(CHROME ? { executablePath: CHROME } : {}), headless: true });
  const results = [];
  for (const t of TENANTS) {
    const p = await b.newPage();
    const errs = []; p.on('pageerror', e => errs.push(e.message));
    await p.goto(`${WEB}/signup`, { waitUntil: 'networkidle', timeout: 90000 });
    await p.waitForSelector('[data-testid=package-card-ENTERPRISE]', { timeout: 60000 });
    // Step 1: plan
    await p.click('[data-testid=package-card-ENTERPRISE] button');
    await p.click('button:text-is("Monthly")');
    await p.click('button:text-is("Continue")');
    // Step 2: details
    await p.waitForSelector('input[name=company_name]', { timeout: 30000 });
    await p.fill('input[name=company_name]', t.name);
    await p.selectOption('select[name=organisation_type]', 'HYBRID');
    await p.fill('input[name=industry]', 'FMCG distribution');
    await p.fill('input[name=admin_full_name]', `TA ${t.name}`);
    await p.fill('input[name=admin_email]', t.email);
    await p.fill('input[name=admin_password]', PASSWORD);
    await p.fill('input[name=admin_password_confirm]', PASSWORD);
    await p.check('input[name=accept_terms]');
    await p.screenshot({ path: `${SCR}/signup-${t.n}-step2.png`, fullPage: true });
    await p.click('button[type=submit]');
    // Step 3: review and submit
    await p.waitForSelector('button.bg-brand-600', { timeout: 30000 });
    await p.screenshot({ path: `${SCR}/signup-${t.n}-step3.png`, fullPage: true });
    await p.click('button:text-is("Create account")');
    await p.waitForLoadState('networkidle');
    await p.waitForTimeout(1500);
    await p.screenshot({ path: `${SCR}/signup-${t.n}-done.png`, fullPage: true });
    const body = (await p.innerText('body')).replace(/\s+/g, ' ').slice(0, 400);
    results.push({ tenant: t.name, url: p.url(), page: body, pageErrors: errs.slice(0, 3) });
    await p.close();
  }
  await b.close();
  console.log(JSON.stringify(results, null, 2));
})().catch(e => { console.error('SIGNUP FAIL', e.message); process.exit(1); });
