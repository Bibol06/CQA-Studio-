const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8');
const code = source.slice(source.indexOf('const audioEventLabels ='),source.indexOf('function renderResults()'));
function app(){
  const nodes=new Map(),pending=[];
  const player={dataset:{cid:'call-one'},readyState:1,duration:100,currentTime:0,plays:0,play(){this.plays++;return Promise.resolve();},pause(){}};
  nodes.set('#audio-player',player);nodes.set('#audio-status',{textContent:'unchanged'});
  const ctx={selected:'call-one',selectionSerial:1,detail:{record:{conversation_id:'call-one',channel:'voice call'}},
    document:{addEventListener(){}},$:s=>nodes.get(s),api:()=>new Promise(resolve=>pending.push(resolve)),toast(){},
    resultsMode:'audio',activeJob:()=>null,settings:{provider:'gemini'},icon:()=>'',fmt:String,
    esc:x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))};
  vm.createContext(ctx);vm.runInContext(code,ctx);return {ctx,nodes,pending,player};
}
test('seeking an event uses audio seconds and a short pre-roll',()=>{
  const {ctx,player}=app();ctx.seekAudio(32,34);
  assert.equal(player.currentTime,31);assert.equal(player.plays,1);
  ctx.seekAudio(32,90);
  assert.equal(vm.runInContext('audioPreviewEnd',ctx)-player.currentTime,20);
});
test('stale events cannot play a different conversation',()=>{
  const {ctx,player}=app();ctx.selected='call-two';ctx.seekAudio(32,34);
  assert.equal(player.plays,0);assert.equal(player.currentTime,0);
});
test('late audio metadata cannot overwrite the next conversation',async()=>{
  const {ctx,nodes,pending}=app();const request=ctx.loadAudioInfo();ctx.selected='call-two';ctx.selectionSerial++;
  pending[0]({duration_seconds:120,channels:1,size_bytes:1000,analysis_matches_audio:false});await request;
  assert.equal(nodes.get('#audio-status').textContent,'unchanged');
});

test('enqueuing audio cannot replace a subsequently selected chat',async()=>{
  const {ctx,nodes,pending}=app();nodes.set('#results-panel',{innerHTML:'current chat'});
  ctx.pollJobs=async()=>{};
  const request=ctx.analyzeAudio();ctx.selected='chat-two';ctx.selectionSerial++;
  ctx.detail={record:{conversation_id:'chat-two',channel:'agent chat'}};
  pending[0]({created:[1],existing:[]});await request;
  assert.equal(nodes.get('#results-panel').innerHTML,'current chat');
});
test('unreviewed acoustic events remain candidates and descriptions are escaped',()=>{
  const {ctx,nodes}=app();nodes.set('#results-panel',{innerHTML:''});
  ctx.detail.audio_analysis={id:1,meta:{model:'fixture',prompt_version:'test',elapsed_seconds:1},event_reviews:{},
    result:{overview:'<script>bad</script>',audio:{duration_seconds:100},quality:{audibility:'clear',limitations:[]},delivery:[],checks:[{type:'cough',status:'not_detected',comment:'',consistency_warning:'Статус расходится с событиями.'}],events:[{type:'cough',speaker:'unknown',confidence:'low',start_seconds:2,end_seconds:3,description:'<img src=x>'}]}};
  ctx.detail.audio_history=[];ctx.renderAudioResults();const html=nodes.get('#results-panel').innerHTML;
  assert.ok(html.includes('Не проверено человеком'));assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<img src=x>'));
  assert.ok(html.includes('Противоречие'));assert.ok(html.includes('Исходный статус AI: Не замечено моделью'));
  assert.equal(ctx.detail.audio_analysis.event_reviews[0],undefined);
});
