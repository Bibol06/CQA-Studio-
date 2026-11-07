const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname,'../static/app.js'),'utf8');
const code = source.slice(source.indexOf('let analyticsData = null'),source.indexOf('function analyticsEvidence('));
function app(){
  const pending=[],rendered=[],node={innerHTML:''};
  const ctx={view:'analytics',URLSearchParams,$:()=>node,esc:x=>x,
    api:()=>new Promise((resolve,reject)=>pending.push({resolve,reject})),
    renderAnalyticsData:()=>rendered.push(vm.runInContext('analyticsData',ctx))};
  vm.createContext(ctx);vm.runInContext(code,ctx);return {ctx,pending,rendered,node};
}
test('late analytics response cannot replace newer filter results',async()=>{
  const {ctx,pending,rendered}=app();
  const old=ctx.renderAnalytics(),current=ctx.renderAnalytics();
  pending[1].resolve({filter:'EN'});await current;
  pending[0].resolve({filter:'RU'});await old;
  assert.equal(rendered.length,1);assert.equal(rendered[0].filter,'EN');
});
test('analytics response after navigation does not overwrite hidden page',async()=>{
  const {ctx,pending,rendered}=app();const request=ctx.renderAnalytics();ctx.view='dialogs';
  pending[0].resolve({});await request;assert.equal(rendered.length,0);
});
