const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname,'../desktop/plugin.js'),'utf8')
  .replace(/import \{[\s\S]*?from '@hermes\/plugin-sdk'\n/,'')
  .replace(/^import .*\n/gm,'').replace('export default {','const plugin = {');
let selected='chat-a', summaryOffline=false, chatResponse;
const state={profile:'tldr',connectionId:'local',gateway:'open',focusedStoredSessionId:'session',focusedSessionOwner:'owner',busy:false};
const queries=[];
const ctx={rest:async()=>({ok:true})};
const el=(type,props,key)=>({type,props,key});
const sandbox={host:{state},useValue:atom=>atom==='session'?selected:atom==='owner'?{connectionId:'local'}:atom,
 useState:value=>[value,()=>{}],useEffect:()=>{}, jsx:el,jsxs:el,Popover:'popover',PopoverTrigger:'trigger',PopoverContent:'content',STATUSBAR_AREAS:{right:'right'},icons:{ChevronUp:'chevron',RefreshCw:'refresh'},
 useQuery:opts=>{queries.push(opts);return opts.queryKey[1]==='chat'?{data:chatResponse,refetch:async()=>{},isError:false}:
 {data:summaryOffline?{ok:false,error:'Offline'}:{ok:true,periods:{total:{usd:'1',inr:'100'},today:{usd:'1',inr:'100'},week:{usd:'1',inr:'100'},month:{usd:'1',inr:'100'}},fx:{rate:'100'}},refetch:async()=>{},isError:false};}};
vm.createContext(sandbox);vm.runInContext(source+'\nthis.render=()=>SpendStatus({ctx: this.ctx}); this.analytics=Analytics; this.tableCost=tableCost; this.comparison=Comparison;',sandbox);sandbox.ctx=ctx;
const stringify=node=>JSON.stringify(node);
chatResponse={ok:true,session_id:'chat-a',usd:'0.035',partial:false};
let tree=sandbox.render(); let rendered=stringify(tree);
assert.match(rendered,/This chat/);assert.match(rendered,/\$0.0350/);assert.match(rendered,/≈₹3.50/);
assert.match(rendered,/OpenRouter total \$1.0000/);
selected='chat-b';rendered=stringify(sandbox.render());assert.doesNotMatch(rendered,/\$0.0350/);
chatResponse={ok:true,session_id:'chat-b',usd:null,partial:true};rendered=stringify(sandbox.render());assert.match(rendered,/\$—/);assert.doesNotMatch(rendered,/\$0.0000/);
summaryOffline=true;chatResponse={ok:true,session_id:'chat-b',usd:'0.04'};rendered=stringify(sandbox.render());assert.match(rendered,/\$0.0400/);assert.match(rendered,/This chat/);

const data={profiles:[{name:'Other',tokens:5,key_cost:{usd:'0.4',inr:'40'},outside_key_cost:{usd:'0.2'},unassigned_cost:{usd:'0.3'}}],models:[],average:{usd:null,inr:null},warnings:[],attribution:{other:{usd:'0.3'},pending:false}};
rendered=stringify(sandbox.analytics({ctx,refresh:()=>{},data}));
assert.match(rendered,/KEY SPEND/);assert.match(rendered,/\$0.4000/);
assert.match(rendered,/Outside key: \$0.2000/);assert.match(rendered,/\+ unknown/);
assert.doesNotMatch(rendered,/unassigned API spend|ors-unassigned/);
assert.equal(sandbox.tableCost(data.profiles[0],data.attribution).cost.usd,'0.4');
assert.equal(sandbox.tableCost(data.profiles[0],{pending:true}).pending,true);
assert.equal(sandbox.tableCost({name:'model-a',key_cost:{usd:'0.1'}},data.attribution).cost.usd,'0.1');
console.log('Spend UI checks passed: chat chip/popup, session switches, unknown costs, offline totals, and reconciled Other.');

rendered=stringify(sandbox.comparison({data:{label:'Budget',baseline:{usd:'40',inr:'4000'},spent:{usd:'20',inr:'2000'},fraction:'0.5',saved:{usd:'20',inr:'2000'}}}));
assert.match(rendered,/Monthly vs Budget/);assert.match(rendered,/\$40.00/);
assert.match(rendered,/"aria-valuemax":40/);assert.doesNotMatch(rendered,/110|10,699/);
console.log('Configurable baseline UI checks passed.');
