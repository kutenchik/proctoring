import test from 'node:test';
import assert from 'node:assert/strict';
import { validateCommand, PRODUCTION_CSP } from '../electron/security';

test('connected IPC accepts only specific bounded admission intents', () => {
  assert.equal(validateCommand('connected.verify', {server_url: 'https://school.example'}).command, 'connected.verify');
  assert.equal(validateCommand('connected.refresh', {}).command, 'connected.refresh');
  const identity = {exam_code:'DEMO',full_name:'Example Student',group:'A',student_id:'S1'};
  assert.equal(validateCommand('connected.admit', identity).command, 'connected.admit');
  for (const patch of [{credential:'secret'}, {url:'https://attacker.test'}, {full_name:''}, {student_id:'x'.repeat(129)}]) {
    assert.throws(() => validateCommand('connected.admit', {...identity,...patch}));
  }
  for (const name of ['connected.start', 'connected.finish', 'http.request', 'credential.get']) assert.throws(() => validateCommand(name, {}));
  assert.match(PRODUCTION_CSP, /connect-src 'none'/); // Renderer never owns HTTP/credentials.
});

test('multiple-choice IPC accepts unique index sets but never answer keys', () => {
  const valid = {question_index:0,option_indices:[0,2],revision:1};
  assert.equal(validateCommand('quiz.answer', valid).command, 'quiz.answer');
  assert.equal(validateCommand('quiz.answer', {...valid, option_indices:[]}).command, 'quiz.answer');
  for (const option_indices of [[1,1], [true], [1.1], [-1], [1001]]) assert.throws(() => validateCommand('quiz.answer', {...valid,option_indices}));
  assert.throws(() => validateCommand('quiz.answer', {...valid,correct_option_ids:['a']}));
});
