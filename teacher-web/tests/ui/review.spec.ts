import { test, expect, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import path from 'node:path';

const origin='http://127.0.0.1:5176';
const python=path.resolve('../.venv-server/Scripts/python.exe');
async function account(page: Page) {
  const email=`review-${randomUUID()}@example.invalid`, password='Only-synthetic-test-4839!';
  const token=execFileSync(python,[path.resolve('tests/issue_test_token.py'),'invite',email],{encoding:'utf8'}).trim();
  const accepted=await page.request.post('/api/v1/auth/accept-invite',{headers:{Origin:origin},data:{token,name:'Review Test Teacher',password}});
  expect(accepted.ok(),await accepted.text()).toBeTruthy();
  const login=await page.request.post('/api/v1/auth/login',{headers:{Origin:origin},data:{email,password}});
  expect(login.ok(),await login.text()).toBeTruthy();
  return email;
}
function seed(email:string,mode:'complete'|'pending'|'interrupted'):{attempt_id:string;exam_id:string} {
  return JSON.parse(execFileSync(python,[path.resolve('tests/seed_review_attempt.py'),email,mode],{encoding:'utf8'}));
}
async function read(page:Page,id:string) {
  const response=await page.request.get(`/api/v1/attempts/${id}/review`);
  expect(response.ok(),await response.text()).toBeTruthy();return response.json();
}
async function open(page:Page,id:string) {
  await page.goto(`/#/attempt/${id}`);
  await expect(page.getByRole('heading',{name:'Synthetic Review Student',exact:true})).toBeVisible();
}

test('incomplete receipt stays prominent and cannot finalize; saved technical records remain separate',async({page})=>{
  const email=await account(page), item=seed(email,'pending');await open(page,item.attempt_id);
  await expect(page.getByRole('heading',{name:'Evidence incomplete — review cannot be finalized'})).toBeVisible();
  await expect(page.getByText('Synthetic PDF generation failure')).toBeVisible();
  await expect(page.getByRole('heading',{name:'Technical records',exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'Behavioral observations',exact:true})).toBeVisible();
  await expect(page.getByLabel('Choose a conclusion',{exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Save conclusion & create reviewed PDF',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Delete completed-attempt materials',exact:true})).toBeDisabled();
  const detail=await read(page,item.attempt_id);
  expect(detail.sync.receipt_complete).toBe(false);expect(detail.can_finalize).toBe(false);
  expect(detail.groups.some((g:{category:string})=>g.category==='technical')).toBe(true);
  expect(detail.events).toHaveLength(4);
});

test('group review, individual exception, deliberate conclusion, manual history and versioned downloads use real persistence',async({page},info)=>{
  const email=await account(page),item=seed(email,'complete');await open(page,item.attempt_id);
  await expect(page.getByRole('heading',{name:'Complete receipt verified'})).toBeVisible();
  await expect(page.getByText('Result inconsistency recorded')).toBeVisible();
  await page.getByRole('button',{name:'Inspect saved reference'}).click();await expect(page.getByRole('img',{name:'Saved identity reference'})).toBeVisible();
  const phone=page.locator('.event-group').filter({has:page.getByRole('heading',{name:'Phone detected',exact:true})});
  await expect(phone.locator('.event-row')).toHaveCount(2);
  await phone.getByRole('button',{name:'Inspect saved snapshot'}).first().click();
  const snapshot=phone.getByRole('img',{name:'Saved snapshot · historical evidence, not live'});
  await expect(snapshot).toBeVisible();expect(await snapshot.evaluate((img:HTMLImageElement)=>img.complete&&img.naturalWidth>0)).toBe(true);
  await phone.getByRole('button',{name:'Review this group'}).click();
  await phone.getByLabel('Review decision',{exact:true}).selectOption('confirmed');
  await phone.getByLabel('Review comment').fill('Group reviewed against the saved snapshot');
  await phone.getByRole('button',{name:'Save review decision'}).click();
  await expect(phone.locator('.event-row .decision-confirmed')).toHaveCount(2);
  const second=phone.locator('.event-row').nth(1);
  await second.getByRole('button',{name:'Change individual decision'}).click();
  await second.getByLabel('Review decision',{exact:true}).selectOption('false_positive');
  await second.getByLabel('Review comment').fill('Individual exception retained');
  await second.getByRole('button',{name:'Save review decision'}).click();
  await expect(second.locator('.decision-false_positive')).toBeVisible();
  let detail=await read(page,item.attempt_id);
  expect(detail.events.find((e:{event_id:string})=>e.event_id==='event-2').history).toHaveLength(2);
  expect(detail.unreviewed_count).toBe(1);
  const conclusion=page.locator('section').filter({has:page.getByRole('heading',{name:'Final teacher conclusion',exact:true})});
  await conclusion.getByLabel('Choose a conclusion',{exact:true}).selectOption('none_confirmed');
  await expect(conclusion.getByRole('button',{name:'Save conclusion & create reviewed PDF',exact:true})).toBeDisabled();
  await conclusion.getByRole('checkbox').check();
  await conclusion.getByLabel('Final comment').fill('Explicit teacher conclusion; one observation not reviewed');
  await conclusion.getByRole('button',{name:'Save conclusion & create reviewed PDF',exact:true}).click();
  await expect(page.getByRole('status')).toHaveText('Review changes saved.');
  await expect.poll(async()=> (await read(page,item.attempt_id)).conclusion.report_status).toBe('ready');
  await page.getByRole('button',{name:'Refresh',exact:true}).click();
  const download=page.waitForEvent('download');await page.getByRole('button',{name:'Reviewed PDF 1',exact:true}).click();
  const downloaded=await download;expect(downloaded.suggestedFilename()).toBe('reviewed-report-v1.pdf');await downloaded.saveAs(info.outputPath('reviewed-v1.pdf'));
  const original=page.waitForEvent('download');await page.getByRole('button',{name:'Original local PDF',exact:true}).click();const originalFile=await original;expect(originalFile.suggestedFilename()).toBe('original-report.pdf');await originalFile.saveAs(info.outputPath('original-report.pdf'));
  await page.getByRole('button',{name:'Add observation'}).click();
  await page.getByLabel('Category',{exact:true}).fill('Operator context');await page.getByLabel('Description',{exact:true}).fill('Manually reviewed after the exam.');
  await page.locator('.inline-review-form').getByRole('button',{name:'Confirm action',exact:true}).click();
  await expect(page.getByText('Created during later review',{exact:true})).toBeVisible();
  await expect(page.locator('.current-conclusion .warning')).toBeVisible();
  await page.getByRole('button',{name:'Correct observation'}).click();await page.getByLabel('Description',{exact:true}).fill('Corrected operator context.');await page.locator('.inline-review-form').getByRole('button',{name:'Confirm action',exact:true}).click();
  await expect(page.getByText('Corrected operator context.',{exact:true}).first()).toBeVisible();
  await page.getByRole('button',{name:'Cancel observation',exact:true}).click();await page.locator('.inline-review-form').getByRole('checkbox').check();await page.locator('.inline-review-form').getByRole('button',{name:'Confirm action',exact:true}).click();
  await expect(page.getByText('Cancelled; retained in history',{exact:true}).first()).toBeVisible();
  detail=await read(page,item.attempt_id);expect(detail.manual_observations[0].history).toHaveLength(3);expect(detail.conclusion.needs_reconsideration).toBe(true);
  await conclusion.getByLabel('Choose a conclusion',{exact:true}).selectOption('insufficient_evidence');await conclusion.getByRole('checkbox').check();await conclusion.getByRole('button',{name:'Save conclusion & create reviewed PDF',exact:true}).click();
  await expect.poll(async()=> (await read(page,item.attempt_id)).conclusion.version).toBe(2);
  await expect.poll(async()=> (await read(page,item.attempt_id)).conclusion.report_status).toBe('ready');
  await page.getByRole('button',{name:'Refresh',exact:true}).click();await expect(page.getByRole('button',{name:'Reviewed PDF 1',exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'Reviewed PDF 2',exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:info.outputPath('review-en.png'),fullPage:true});
  await page.getByLabel('Language',{exact:true}).selectOption('ru');await expect(page.getByRole('heading',{name:'Полный приём подтверждён'})).toBeVisible();
  await page.setViewportSize({width:375,height:900});await page.getByLabel('Язык',{exact:true}).selectOption('kk');await expect(page.getByRole('heading',{name:'Толық қабылдау расталды'})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:info.outputPath('review-kk-mobile.png'),fullPage:true});
  await page.getByLabel('Тіл',{exact:true}).selectOption('en');await page.goto(`/#/exam/${item.exam_id}`);
  const xlsx=page.waitForEvent('download');await page.getByRole('button',{name:'Export exam XLSX'}).click();const xlsxFile=await xlsx;expect(xlsxFile.suggestedFilename()).toBe('exam-attempts.xlsx');await xlsxFile.saveAs(info.outputPath('exam-attempts.xlsx'));
});

test('interruption recovery is a narrow reasoned grant, with during-exam manual notes and no finalization',async({page})=>{
  const email=await account(page),item=seed(email,'interrupted');await open(page,item.attempt_id);
  await page.getByRole('button',{name:'Add observation'}).click();await page.getByLabel('Category',{exact:true}).fill('Setup interruption');await page.getByLabel('Description',{exact:true}).fill('Synthetic unexpected process closure under review');await page.locator('.inline-review-form').getByRole('button',{name:'Confirm action',exact:true}).click();await expect(page.getByText('Created during the exam',{exact:true})).toBeVisible();
  const recovery=page.locator('section').filter({has:page.getByRole('heading',{name:'Same-device recovery',exact:true})});
  await recovery.getByLabel('Required reason').fill('Original student device ready for recovery checks');await recovery.getByRole('button',{name:'Authorize recovery on original device'}).click();await expect(page.getByText('Recovery authorized; waiting for the student')).toBeVisible();
  const detail=await read(page,item.attempt_id);expect(detail.sync.recovery.grant_id).toBeTruthy();expect(detail.can_finalize).toBe(false);await expect(page.getByRole('button',{name:'Authorize recovery on original device'})).toHaveCount(0);
});

test('confirmed deletion removes materials only after complete receipt and leaves a clear tombstone',async({page})=>{
  const email=await account(page),item=seed(email,'complete');await open(page,item.attempt_id);
  const retention=page.locator('.retention-panel');const remove=retention.getByRole('button',{name:'Delete completed-attempt materials',exact:true});
  await expect(remove).toBeDisabled();await retention.getByLabel('Required reason').fill('Remove only this synthetic complete test bundle');await retention.getByRole('checkbox').check();await remove.click();
  await expect(page.getByRole('heading',{name:'Evidence materials deleted'})).toBeVisible();await expect(page.getByRole('status')).toContainText('minimal deletion audit remains');
  expect((await page.request.get(`/api/v1/attempts/${item.attempt_id}/evidence/snapshot`)).status()).toBe(410);
});
