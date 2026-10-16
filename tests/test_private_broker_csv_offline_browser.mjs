import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import vm from 'node:vm';
import {TextDecoder} from 'node:util';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const html=fs.readFileSync(path.join(root,'downloads','READ_ONLY_BROKER_CSV_CHECK_OFFLINE.html'),'utf8');
const cmd=fs.readFileSync(path.join(root,'downloads','READ_ONLY_BROKER_CSV_CHECK_WIN.cmd'),'utf8');
const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
assert.equal(scripts.length,1);
const browser={};
vm.runInNewContext(scripts[0][1],{window:browser,TextDecoder,Set}, {timeout:3000});
const inspect=(bytes,name='synthetic.csv')=>browser.CsvHeaderClassifier.classify(bytes,name);
const header='約定日,銘柄コード,売買区分,数量［株］,単価［円］';
// Fixed Windows-932 bytes from the exact header text (no source account data).
const cp932hex='96f192e893fa2c96c195bf8352815b83682c948494838be695aa2c909497ca816d8a94816e2c925089bf816d897e816e';
const u8=s=>Buffer.from(s,'utf8');
test('UTF8-BOM synthetic header is candidate (no rows output)',()=>{
 const r=inspect(Buffer.concat([Buffer.from([0xef,0xbb,0xbf]),u8(header+'\r\nSECRET_ACCOUNT_123,private')]));
 assert.equal(r.status,'CANDIDATE_ONLY');assert.equal(r.encoding,'UTF8');assert.equal(r.columns,5);
 assert.equal(JSON.stringify(r).includes('SECRET'),false);
});
test('Windows-932 (CP932) synthetic header is candidate',()=>{
 const r=inspect(Buffer.from(cp932hex,'hex'));
 assert.equal(r.status,'CANDIDATE_ONLY');assert.equal(r.encoding,'CP932');assert.equal(r.columns,5);
});
test('unknown header blocks',()=>assert.equal(inspect(u8('UNKNOWN,ACCOUNTID\r\n1,2')).status,'BLOCKED'));
test('mixed family fails closed',()=>assert.equal(inspect(u8(header+',約定時刻')).status,'BLOCKED'));
test('duplicates fail closed',()=>assert.equal(inspect(u8(header+',約定日')).status,'BLOCKED'));
test('malformed quote fails closed',()=>assert.equal(inspect(u8('"約定日,銘柄コード')).status,'BLOCKED'));
test('wrong extension, empty and >8MiB blocked',()=>{
 assert.equal(inspect(u8(header),'real.txt').status,'BLOCKED');
 assert.equal(inspect(Buffer.alloc(0)).status,'BLOCKED');
 assert.equal(inspect(Buffer.alloc(8388609)).status,'BLOCKED');
});
test('HTML source is offline, no network transfer and script restriction',()=>{
 assert.match(html,/connect-src 'none'/);
 assert.match(html,/form-action 'none'/);
 assert.doesNotMatch(html,/\b(fetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon|localStorage|https?:\/\/)/);
 assert.match(html,/type="file"/);
});
test('CMD launches HTML without restricted PS1 or policy override',()=>{
 assert.match(cmd,/start "" "%HTML%"/);
 assert.doesNotMatch(cmd,/powershell|\.ps1|ExecutionPolicy|Bypass/i);
});
