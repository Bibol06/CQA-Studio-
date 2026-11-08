const {test}=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8');
const code=source.slice(source.indexOf('const asrReferences='),source.indexOf('async function loadAudioInfo()'));
test('WER CER require a reference and preserve mixed RU KZ words',()=>{
 const ctx={};vm.createContext(ctx);vm.runInContext(code,ctx);
 assert.equal(ctx.asrMetrics('','текст'),null);
 assert.equal(ctx.asrMetrics('Я бүгін жұмысқа бардым','Я бүгін жұмысқа бардым.').wer,0);
 assert.equal(ctx.asrMetrics('Мен бүгін жұмысқа бардым','Мен жұмысқа бардым').wer,.25);
 assert.ok(ctx.asrMetrics('Қазақша','Казакша').cer>0);
});
function app(){
 const panel={innerHTML:''},player={paused:false,pause(){this.paused=true;}};
 const data={audio_sha256:'fixture-hash',cloud_engine:'fixture-model',local:{engine:'fixture-local',processed_seconds:20,full_recording:true,chunks:[],preview:{end_seconds:20,enhanced_wav_base64:'AA=='},processing:{method:'test'}},cloud:{raw:{text:'<script>bad</script>',limitations:[],complete:true},enhanced:{text:'Сәлем! Здравствуйте.',limitations:[],complete:true}}};
 const ctx={selected:'call-one',detail:{asr_analysis:{result:data}},activeJob:()=>null,jobsState:{jobs:[]},jobLabels:{},resultModeTabs:()=>'',fmt:String,
  esc:x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  $:s=>s==='#audio-player'?player:panel,atob,downloadJson(value){this.exported=value;}};
 vm.createContext(ctx);vm.runInContext(code,ctx);return {ctx,panel,player};
}
test('ASR exposes the cloud comparison immediately and escapes recognized text',()=>{
 const {ctx,panel}=app();ctx.renderAsrResults();
 assert.ok(panel.innerHTML.includes('class="asr-case" open'));assert.ok(panel.innerHTML.includes('&lt;script&gt;'));
 assert.ok(!panel.innerHTML.includes('<script>bad'));
});
test('ASR export keeps provenance and leaves unreferenced accuracy absent',()=>{
 const {ctx}=app();ctx.downloadJson=value=>{ctx.exported=value;};ctx.exportAsr();
 assert.equal(ctx.exported.cloud_engine,'fixture-model');assert.equal(ctx.exported.source_transcript_sent,false);
 assert.equal(ctx.exported.cases[0].raw_metrics,null);assert.equal(ctx.exported.cases[0].reference_verified_by_system,false);
});
test('a decoded preview cannot start after selecting another conversation',async()=>{
 const {ctx,player}=app();let release,begin,created=0;const ready=new Promise(resolve=>{begin=resolve;});
 ctx.AudioContext=class{resume(){return Promise.resolve();}decodeAudioData(){return new Promise(resolve=>{release=resolve;begin();});}createBufferSource(){created++;return {connect(){},start(){},stop(){}};}};
 const promise=ctx.playAsrPreview();await ready;ctx.selected='call-two';release({});await promise;
 assert.equal(created,0);assert.equal(player.paused,true);
});
