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
test('blocked unknown does not reuse the candidate explanation',()=>{
 const note=browser.CsvHeaderClassifier.statusNote;
 const candidate=note('CANDIDATE_ONLY');
 assert.match(candidate,/CANDIDATE_ONLYはヘッダー形式の候補です/);
 assert.equal(note('BLOCKED').includes(candidate),false);
 assert.equal(note('FILE_NOT_SELECTED').includes('CANDIDATE_ONLYはヘッダー形式の候補です'),false);
 assert.equal(note('AMBIGUOUS'),note('FILE_NOT_SELECTED'));
 const warning=html.match(/<p id="status-note" class="warning">([\s\S]*?)<\/p>/);
 assert.ok(warning);
 assert.equal(warning[1],note('FILE_NOT_SELECTED'));
});
test('selecting an unknown CSV replaces the yellow note',async()=>{
 const nodes={};
 for (const id of ['status','family','encoding','columns','status-note']) nodes[id]={textContent:'',className:''};
 let onChange;
 nodes['csv-file']={
  files:[],
  addEventListener(type,fn){ if(type==='change') onChange=fn; }
 };
 const document={getElementById(id){return nodes[id];}};
 const local={};
 vm.runInNewContext(scripts[0][1],{window:local,document,TextDecoder,Set},{timeout:3000});
 assert.equal(nodes['status-note'].textContent,local.CsvHeaderClassifier.statusNote('FILE_NOT_SELECTED'));
 const bytes=u8('UNKNOWN,ACCOUNTID\r\nSECRET_ROW');
 nodes['csv-file'].files=[{
  name:'test_unknown.csv',
  size:bytes.length,
  arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)
 }];
 await onChange();
 assert.equal(nodes.status.textContent,'Status: BLOCKED');
 assert.equal(nodes.status.className,'blocked');
 assert.equal(nodes.family.textContent,'UNKNOWN');
 assert.equal(nodes.encoding.textContent,'UTF8');
 assert.equal(nodes.columns.textContent,'2');
 assert.equal(nodes['status-note'].textContent.includes('CANDIDATE_ONLYはヘッダー形式の候補です'),false);
 assert.match(nodes['status-note'].textContent,/BLOCKEDはヘッダー候補ではありません/);
 assert.equal(JSON.stringify(nodes).includes('SECRET_ROW'),false);
 const candidateBytes=Buffer.concat([Buffer.from([0xef,0xbb,0xbf]),u8(header+'\r\n')]);
 nodes['csv-file'].files=[{
  name:'test_utf8.csv',
  size:candidateBytes.length,
  arrayBuffer:async()=>candidateBytes.buffer.slice(candidateBytes.byteOffset,candidateBytes.byteOffset+candidateBytes.byteLength)
 }];
 await onChange();
 assert.equal(nodes.status.textContent,'Status: CANDIDATE_ONLY');
 assert.equal(nodes.status.className,'candidate');
 assert.equal(nodes.encoding.textContent,'UTF8');
 assert.equal(nodes.columns.textContent,'5');
 assert.equal(nodes['status-note'].textContent,local.CsvHeaderClassifier.statusNote('CANDIDATE_ONLY'));
});
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
