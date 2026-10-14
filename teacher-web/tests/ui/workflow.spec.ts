import { test, expect, type Page, type APIRequestContext } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import path from 'node:path';

const password = 'Test-only-password-9382!';
const origin = 'http://127.0.0.1:5174';
const root = path.resolve('..');
function accountToken(kind: 'invite' | 'reset', email: string) {
  return execFileSync(path.join(root,'.venv-server','Scripts','python.exe'), [path.resolve('tests/issue_test_token.py'),kind,email], {encoding:'utf8'}).trim();
}
async function createAccount(request: APIRequestContext) {
  const email = `test-${randomUUID()}@example.invalid`;
  const accepted = await request.post('/api/v1/auth/accept-invite',{headers:{Origin:origin},data:{token:accountToken('invite',email),name:'Test Teacher',password}});
  expect(accepted.status()).toBe(200);
  const response = await request.post('/api/v1/auth/login',{headers:{Origin:origin},data:{email,password}});
  expect(response.status()).toBe(200);
  return {email,...await response.json()};
}
async function mutate(request: APIRequestContext, csrf: string, endpoint: string, data: unknown) {
  const response = await request.post(`/api/v1${endpoint}`, {headers:{Origin:origin,'X-CSRF-Token':csrf},data});
  expect(response.ok(), await response.text()).toBeTruthy(); return response.json();
}
async function nativeExam(request: APIRequestContext, csrf: string, title = 'Biology · autumn assessment') {
  const library = await mutate(request,csrf,'/libraries',{title:'Biology questions',questions:[{id:'q1',type:'single_choice',prompt:'Which part carries genetic information?',options:[{id:'a',text:'DNA'},{id:'b',text:'Water'}],correct_option_ids:['a']}]});
  return mutate(request,csrf,'/exams',{title,exam_type:'native',library_id:library.id,admission_start:new Date(Date.now()-60_000).toISOString(),admission_close:new Date(Date.now()+3600_000).toISOString(),duration_seconds:1800,timezone:'Asia/Qyzylorda',shuffle_questions:true,shuffle_options:true,audio_monitoring:true,save_snapshots:true,protection_mode:'unprotected'});
}
async function noOverflow(page: Page) {expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();}

test('invitation, cookie login, password reset and logout use the real service', async ({page}) => {
  const email = `invite-${randomUUID()}@example.invalid`; const token = accountToken('invite',email);
  await page.goto(`/#/invite?token=${token}`);
  await expect(page.getByRole('heading',{name:'Set up your teacher account'})).toBeVisible();
  await expect(page).toHaveURL(/#\/invite$/);
  await page.getByLabel('Your name').fill('Invited Teacher'); await page.getByLabel('Password',{exact:true}).fill(password);
  await page.getByRole('button',{name:'Create invited account'}).click();
  await expect(page.getByRole('status')).toContainText('Saved. Sign in');
  await page.getByLabel('Email address').fill(email); await page.getByLabel('Password',{exact:true}).fill(password);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Exams',exact:true})).toBeVisible();
  const cookie = (await page.context().cookies()).find(c => c.name === 'proctor_teacher_session');
  expect(cookie?.httpOnly).toBe(true); expect(cookie?.sameSite).toBe('Strict');
  expect(await page.evaluate(() => Object.keys(localStorage))).not.toContain('csrf_token');
  const reset = accountToken('reset',email);
  await page.goto(`/#/reset?token=${reset}`); await page.getByLabel('Password',{exact:true}).fill(`${password}-new`);
  await page.getByRole('button',{name:'Save password'}).click();
  await expect(page.getByRole('status')).toContainText('Saved. Sign in');
  expect((await page.request.get('/api/v1/auth/me')).status()).toBe(401);
  await page.getByLabel('Email address').fill(email); await page.getByLabel('Password',{exact:true}).fill(`${password}-new`);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Exams',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Sign out'}).click();
  await expect(page.getByRole('heading',{name:'Sign in',exact:true})).toBeVisible();
  expect((await page.request.get('/api/v1/exams')).status()).toBe(401);
});

test('JSON and XLSX imports require preview and explicit save; invalid data stays unsaved', async ({page}) => {
  await createAccount(page.request); await page.goto('/#/library');
  await page.getByLabel('Question file').setInputFiles(path.join(root,'server','samples','questions.json'));
  await page.getByRole('button',{name:'Validate & preview'}).click();
  await expect(page.getByText('Preview — not saved')).toBeVisible();
  expect((await (await page.request.get('/api/v1/libraries')).json()).items).toHaveLength(0);
  await expect(page.getByText('Multiple choice',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Save to my library'}).click();
  await expect(page.getByRole('status')).toHaveText('Saved to your library.');
  expect((await (await page.request.get('/api/v1/libraries')).json()).items).toHaveLength(1);
  await page.getByLabel('Question file').setInputFiles(path.join(root,'server','samples','questions.xlsx'));
  await page.getByRole('button',{name:'Validate & preview'}).click();
  await expect(page.getByText('Preview — not saved')).toBeVisible();
  await page.getByRole('button',{name:'Save to my library'}).click();
  await expect(page.getByRole('status')).toHaveText('Saved to your library.');
  expect((await (await page.request.get('/api/v1/libraries')).json()).items).toHaveLength(2);
  await page.getByLabel('Question file').setInputFiles({name:'broken.json',mimeType:'application/json',buffer:Buffer.from('{"title":"bad","questions":[]}')});
  await page.getByRole('button',{name:'Validate & preview'}).click(); await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('button',{name:'Save to my library'})).toHaveCount(0);
  expect((await (await page.request.get('/api/v1/libraries')).json()).items).toHaveLength(2);
});

test('native creation uses explicit timezone and immutable settings, reasoned attempt actions use real persistence', async ({page}) => {
  const auth = await createAccount(page.request); const seed = await nativeExam(page.request,auth.csrf_token,'Reference exam');
  await page.goto('/#/create'); await page.getByLabel('Title',{exact:true}).fill('Teacher-created quiz');
  await page.getByLabel('Timezone (IANA)').fill('Asia/Qyzylorda');
  const now = new Date(); const date = now.toISOString().slice(0,10);
  await page.getByLabel('Admission opens',{exact:true}).fill(`${date}T00:00`); await page.getByLabel('Admission closes',{exact:true}).fill(`${date}T23:59`);
  const library = (await (await page.request.get('/api/v1/libraries')).json()).items[0];
  await page.getByLabel('Question set',{exact:true}).selectOption(library.id);
  await page.getByRole('button',{name:'Create exam',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Teacher-created quiz',exact:true})).toBeVisible();
  const examId = page.url().split('/exam/')[1]; const exam = await (await page.request.get(`/api/v1/exams/${examId}`)).json();
  expect(exam.admission_start).toContain('19:00:00'); expect(exam.policy.protection_mode).toBe('unprotected'); expect(exam.quiz.questions).toHaveLength(1);
  const admit = await page.request.post('/api/v1/student/admit',{data:{exam_code:seed.code,full_name:'Synthetic Student',group:'BIO-01',student_id:'TEST-101'}}); expect(admit.ok()).toBeTruthy(); const attempt = await admit.json();
  await page.goto(`/#/exam/${seed.id}`); await page.getByRole('button',{name:'Add 5 minutes of preparation'}).click();
  const reason = page.getByLabel('Required reason'); await expect(reason).toBeFocused();
  await page.getByRole('button',{name:'Confirm action'}).click(); await expect(reason).toHaveAttribute('required','');
  await reason.fill('Operator assistance with initial setup'); await page.getByRole('button',{name:'Confirm action'}).click();
  await expect(page.getByRole('status')).toHaveText('Action saved.');
  const attempts = await (await page.request.get(`/api/v1/exams/${seed.id}/attempts`)).json();
  expect(new Date(attempts.items[0].preparation_deadline).getTime()-new Date(attempt.preparation_deadline).getTime()).toBe(300_000);
  const headers = {Authorization:`Bearer ${attempt.credential}`};
  expect((await page.request.post('/api/v1/student/start',{headers})).ok()).toBeTruthy();
  expect((await page.request.post('/api/v1/student/finish',{headers,data:{score:1,total:1,end_reason:'submitted'}})).ok()).toBeTruthy();
  await page.getByRole('button',{name:'Refresh',exact:true}).click();
  await expect(page.getByText('Client-reported result: 1 / 1')).toBeVisible();
  await page.getByRole('button',{name:'Allow one repeat attempt'}).click(); await page.getByLabel('Required reason').fill('Authorized practice retry');
  await page.getByRole('button',{name:'Confirm action'}).click(); await expect(page.getByText('Repeat authorized',{exact:true})).toBeVisible();
});

test('external creation and exam sections use stored data, other teacher sees no records', async ({page,browser}) => {
  await createAccount(page.request); await page.goto('/#/create');
  await page.getByLabel('Title',{exact:true}).fill('External assessment'); await page.getByLabel('Exam type',{exact:true}).selectOption('external');
  await page.getByLabel('Timezone (IANA)').fill('UTC'); await page.getByLabel('Admission opens',{exact:true}).fill('2099-01-01T10:00'); await page.getByLabel('Admission closes',{exact:true}).fill('2099-01-01T11:00');
  await page.getByLabel('Exam URL (HTTPS)').fill('https://example.edu/exams/one'); await expect(page.getByText('Ending local proctoring does not submit answers on the external website.')).toBeVisible();
  await page.getByRole('button',{name:'Create exam',exact:true}).click(); await expect(page.getByRole('heading',{name:'External assessment'})).toBeVisible();
  const examId = page.url().split('/exam/')[1]; await page.getByRole('link',{name:'Back to exams'}).click();
  await page.getByRole('button',{name:/Upcoming/}).click(); await expect(page.getByRole('heading',{name:'External assessment'})).toBeVisible();
  await expect(page.getByText('0 Saved participants',{exact:true})).toBeVisible();
  const second = await browser.newContext({baseURL:origin}); try {await createAccount(second.request); const other=await second.newPage(); await other.goto(`/#/exam/${examId}`); await expect(other.getByRole('alert')).toContainText('unavailable to your account');} finally {await second.close();}
});

test('EN/RU/KK, narrow layout and keyboard focus remain usable with real exam data', async ({page}, info) => {
  const auth = await createAccount(page.request); await nativeExam(page.request,auth.csrf_token); await page.goto('/');
  await expect(page.getByRole('heading',{name:'Biology · autumn assessment'})).toBeVisible();
  await noOverflow(page); await page.screenshot({path:info.outputPath('teacher-exams-en.png'),fullPage:true});
  await page.getByLabel('Language',{exact:true}).selectOption('ru'); await expect(page.getByRole('heading',{name:'Экзамены',exact:true})).toBeVisible();
  await noOverflow(page); await page.screenshot({path:info.outputPath('teacher-exams-ru.png'),fullPage:true});
  await page.getByLabel('Язык',{exact:true}).selectOption('kk'); await expect(page.getByRole('heading',{name:'Емтихандар',exact:true})).toBeVisible();
  await page.setViewportSize({width:375,height:812}); await noOverflow(page); await page.screenshot({path:info.outputPath('teacher-exams-kk-mobile.png'),fullPage:true});
  await expect(page.getByRole('button',{name:'Шығу',exact:true})).toBeVisible();
  await page.keyboard.press('Tab'); expect(await page.evaluate(() => document.activeElement !== document.body)).toBeTruthy();
  await page.emulateMedia({reducedMotion:'reduce'}); expect(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches)).toBeTruthy();
});
