const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8');
const functions=source.slice(source.indexOf('function readableEdition()'),source.indexOf('function renderTranscript()'));
const jump=source.slice(source.indexOf('function jumpEvidence('),source.indexOf('async function evaluateSelected('));
function app(){
  const ctx={detail:{record:{conversation_id:'call-one'}},roles:{operator:'Оператор',system:'Событие'},
    esc:x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))};
  vm.createContext(ctx);vm.runInContext(functions,ctx);return ctx;
}
test('readable rendering preserves message identity and escapes model text',()=>{
  const ctx=app(),turn={speaker:'operator',timestamp:'source-time',text:'исходный текст'};
  const edits=new Map([[3,{text:'<img src=x>Исправлено.',uncertain:true}]]);
  const edited=ctx.transcriptMessage(turn,2,edits),original=ctx.transcriptMessage(turn,2,null);
  assert.ok(edited.includes('id="message-3"'));assert.ok(edited.includes('source-time'));
  assert.ok(edited.includes('&lt;img src=x&gt;'));assert.ok(edited.includes('Сверьте с записью'));
  assert.ok(original.includes('исходный текст'));assert.equal(turn.text,'исходный текст');
});
test('editions from another conversation cannot appear in the selected call',()=>{
  const ctx=app();ctx.detail.audio_analysis={result:{readable_transcript:{conversation_id:'other-call'}}};
  assert.equal(ctx.readableEdition(),null);
});
test('evidence opens original source even when readable edition is selected',()=>{
  const ctx=app();ctx.showContext=true;ctx.transcriptMode='readable';ctx.renders=0;
  ctx.renderTranscript=()=>ctx.renders++;ctx.document={querySelectorAll:()=>[]};ctx.$=()=>null;
  vm.runInContext(jump,ctx);ctx.jumpEvidence(3,3);
  assert.equal(ctx.transcriptMode,'original');assert.equal(ctx.renders,1);
});
