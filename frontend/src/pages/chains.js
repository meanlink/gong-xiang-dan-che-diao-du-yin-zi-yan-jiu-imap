import {datasets,chains} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {table} from '../components/common/table.js';
import {esc,date,notify} from '../utils/dom.js';
import {ChainStatus,ChainNodeStatus} from '../constants/enums.js';

let draft=null,editingId=null,selectedKey=null,traceStation=null;
const LAGS=[0,1,2,3];
const canWrite=()=>['admin','analyst'].includes(session.user.role);
const newDraft=()=>({name:'',dataset_id:null,nodes:[],edges:[]});

function topoLayers(nodes,edges){
 const indeg={},adj={},depth={};
 nodes.forEach(n=>{indeg[n.key]=0;adj[n.key]=[];depth[n.key]=0;});
 edges.forEach(e=>{if(adj[e.from_key]&&indeg[e.to_key]!==undefined){adj[e.from_key].push(e.to_key);indeg[e.to_key]++;}});
 const queue=nodes.filter(n=>!indeg[n.key]).map(n=>n.key);const seen=new Set(queue);
 let layers=[],current=queue;
 while(current.length){
   layers.push(current);const next=[];
   current.forEach(k=>adj[k].forEach(t=>{depth[t]=Math.max(depth[t],depth[k]+1);if(--indeg[t]===0&&!seen.has(t)){seen.add(t);next.push(t);}}));
   current=next;
 }
 const cyclic=nodes.filter(n=>!seen.has(n.key)).map(n=>n.key);
 if(cyclic.length)layers.push(cyclic);
 return {layers,cyclic};
}

function composer(){
 const d=draft;
 const nodeRows=d.nodes.map((n,i)=>'<tr><td>'+esc(n.key)+'</td><td>'+esc(n.name)+'</td><td>'+n.lag+' 时段</td><td>'+n.threshold+'</td><td><button class="text-button" data-del-node="'+i+'">移除</button></td></tr>').join('');
 const edgeRows=d.edges.map((e,i)=>'<tr><td>'+esc(e.from_key)+'</td><td>→ '+esc(e.to_key)+'</td><td><button class="text-button" data-del-edge="'+i+'">移除</button></td></tr>').join('');
 const keys=d.nodes.map(n=>'<option value="'+esc(n.key)+'">'+esc(n.key)+' · '+esc(n.name)+'</option>').join('');
 const {cyclic}=topoLayers(d.nodes,d.edges);
 return '<section class="panel" id="composer"><div class="section-title"><h2>'+(editingId?'修改编排（草稿）':'编排新研究链')+'</h2><span>分支与汇合均为有向无环图</span></div>'
 +'<form id="chain-form"><div class="parameter-grid"><label>研究链名称<input name="name" required minlength="2" value="'+esc(d.name)+'" placeholder="例如：晚高峰补车候选复核"></label><label>数据批次<select name="dataset_id">'+workspace.datasets.map(x=>'<option value="'+x.id+'" '+(x.id===d.dataset_id?'selected':'')+'>'+esc(x.name)+' · '+x.rows+' 条</option>').join('')+'</select></label></div>'
 +'<div class="section-title"><h2>节点</h2><span>各节点设置提前量与偏相关门槛</span></div>'
 +'<div class="composer-row"><input id="node-key" placeholder="标识 a-z0-9_-" pattern="[A-Za-z0-9_\\-]+" maxlength="40"><input id="node-name" placeholder="节点名称，如 初筛 · 30 分钟"><select id="node-lag">'+LAGS.map(i=>'<option value="'+i+'"'+(i===1?' selected':'')+'>提前 '+i*30+' 分钟</option>').join('')+'</select><input id="node-threshold" type="number" min="0" max="1" step="0.05" value="0.3" title="偏相关门槛"><button type="button" class="button small" id="add-node">添加节点</button></div>'
 +(d.nodes.length?'<div class="table-wrap"><table><thead><tr><th>标识</th><th>名称</th><th>提前量</th><th>偏相关门槛</th><th></th></tr></thead><tbody>'+nodeRows+'</tbody></table></div>':'<p class="hint">尚无节点。后继节点只研究所有前置共同通过的站点。</p>')
 +'<div class="section-title"><h2>依赖边</h2><span>从前置指向后继，汇合即多条入边</span></div>'
 +'<div class="composer-row"><select id="edge-from">'+keys+'</select><select id="edge-to">'+keys+'</select><button type="button" class="button small" id="add-edge" '+(d.nodes.length<2?'disabled':'')+'>添加依赖</button></div>'
 +(d.edges.length?'<div class="table-wrap"><table><thead><tr><th>前置</th><th>后继</th><th></th></tr></thead><tbody>'+edgeRows+'</tbody></table></div>':'<p class="hint">尚无依赖边。无边节点为根节点，研究样本中的全部站点。</p>')
 +(cyclic.length?'<p class="warning">检测到环路（'+esc(cyclic.join('、'))+'）。草稿可保存，但启动将被拒绝。</p>':'')
 +'<button type="submit" class="primary" '+(canWrite()&&d.nodes.length?'':'disabled')+'>'+(editingId?'保存编排':'创建研究链')+'</button> '
 +(editingId?'<button type="button" class="button" id="cancel-edit">取消编辑</button>':'')
 +'<p class="hint">启动时冻结样本快照、参数与依赖；重复提交按名称幂等，不会重复建节点。</p></form></section>';
}

function listView(list){
 const rows=list.map(c=>{
   const n=c.counts||{},done=(n.completed||0)+(n.empty||0);
   return '<article class="chain-item"><div><strong>'+esc(c.name)+'</strong><p><span class="status '+esc(c.status)+'">'+esc(ChainStatus[c.status]||c.status)+'</span> · 节点 '+done+'/'+(n.total||0)+' · '+date(c.created_at)+'</p><small>'+(c.approved?'已批准 · 简报已固定':(c.status==='completed'?'待负责人批准':(c.status==='failed'?'存在失败节点，可补跑前置':'编排或推进中')))+'</small></div><a class="button small" href="#/chains/'+c.id+'">打开 ↗</a></article>';
 }).join('');
 return heading('05 / REVIEW CHAIN','研究链 · 多级复核','把筛选出的补车候选串成有向复核链：各节点设置提前量与偏相关门槛，后继只研究所有前置共同通过的站点。','<button class="button primary" id="toggle-composer" '+(canWrite()&&workspace.datasets.length?'':'disabled')+'>编排新研究链 ↗</button>')
 +(draft?composer():'')
 +'<section class="panel"><div class="section-title"><h2>研究链</h2><span>'+list.length+' 条</span></div>'+(list.length?'<div class="chain-list">'+rows+'</div>':'<div class="empty">尚无研究链。点击上方按钮编排第一条多级复核链。</div>')+'</section>';
}

function graph(c){
 const {layers}=topoLayers(c.nodes,c.edges);
 const W=Math.max(1,layers.length)*200+40,H=Math.max(...layers.map(l=>l.length),1)*86+40;
 const pos={};
 layers.forEach((layer,li)=>layer.forEach((k,i)=>{pos[k]={x:20+li*200,y:20+i*86};}));
 const byKey={};c.nodes.forEach(n=>byKey[n.key]=n);
 let svg='<defs><marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" class="arrow"/></marker></defs>';
 c.edges.forEach(e=>{const a=pos[e.from_key],b=pos[e.to_key];if(!a||!b)return;svg+='<line class="cedge" x1="'+(a.x+168)+'" y1="'+(a.y+30)+'" x2="'+b.x+'" y2="'+(b.y+30)+'" marker-end="url(#arrow)"/>';});
 c.nodes.forEach(n=>{const p=pos[n.key];if(!p)return;
   svg+='<g class="cnode '+esc(n.status)+(selectedKey===n.key?' selected':'')+'" data-node="'+esc(n.key)+'"><rect x="'+p.x+'" y="'+p.y+'" width="168" height="60" rx="2"/>'
   +'<text x="'+(p.x+12)+'" y="'+(p.y+22)+'" class="t">'+esc(n.name.slice(0,12))+'</text>'
   +'<text x="'+(p.x+12)+'" y="'+(p.y+40)+'" class="s">'+esc(ChainNodeStatus[n.status]||n.status)+' · 提前 '+(n.lag*30)+' 分 · 门槛 '+n.threshold+'</text>'
   +'<text x="'+(p.x+12)+'" y="'+(p.y+55)+'" class="s">'+(n.status==='completed'||n.status==='empty'?'通过 '+((n.result.passed||[]).length)+' 站':'')+'</text></g>';});
 return '<svg class="chain-graph" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="研究链依赖图">'+svg+'</svg>';
}

function nodePanel(c){
 const n=c.nodes.find(x=>x.key===selectedKey)||c.nodes[0];
 if(!n)return '<section class="panel empty">该链尚无节点。</section>';
 selectedKey=n.key;
 const r=n.result||{},stations=r.stations||[];
 const preds=(n.predecessors||[]).map(p=>'<span class="chip">'+esc(p.name)+' · '+esc(ChainNodeStatus[p.status]||p.status)+'</span>').join('')||'<span class="hint">根节点</span>';
 const passed=(r.passed||[]).map(s=>'<span class="chip ok">'+esc(s)+'</span>').join('');
 const cols=[{key:'station',label:'站点'},{key:'pairs',label:'有效配对'},{key:'raw',label:'原始 r'},{key:'partial',label:'偏相关 r'},{key:'p',label:'参考 p'},{key:'verdict',label:'判定'},{key:'note',label:'筛选原因'}];
 const rows=stations.map(s=>({...s,verdict:s.passed?'通过':'未通过'}));
 const rerun=canWrite()&&c.status!=='draft'&&['completed','empty','failed'].includes(n.status);
 return '<section class="panel" id="node-panel"><div class="section-title"><h2>'+esc(n.name)+'</h2><span>标识 '+esc(n.key)+' · 第 '+n.generation+' 代</span></div>'
 +'<div class="node-meta"><span class="status '+esc(n.status)+'">'+esc(ChainNodeStatus[n.status]||n.status)+'</span><span>提前量 '+(n.lag*30)+' 分钟</span><span>偏相关门槛 ≥ '+n.threshold+'</span>'+(n.finished_at?'<span>'+date(n.finished_at)+'</span>':'')+'</div>'
 +(n.error?'<p class="warning">'+esc(n.error)+'</p>':'')
 +'<p class="hint">前置：'+(n.predecessors||[]).length+' 个；后继：'+((n.successors||[]).join('、')||'无')+'</p><div class="chips">'+preds+'</div>'
 +(n.expected_candidates?'<p class="hint">待执行，当前候选：'+esc(n.expected_candidates.join('、'))+'</p>':'')
 +(r.reason?'<p class="warning">'+esc(r.reason)+'</p>':'')
 +(r.candidates?'<p class="hint">进入候选 '+r.candidates.length+' 站：'+esc(r.candidates.join('、'))+'</p>':'')
 +(passed?'<div class="chips">'+passed+'</div>':'')
 +(stations.length?table(cols,rows):'<p class="empty">'+(n.status==='pending'?'等待前置完成后执行。':n.status==='blocked'?'被前置失败阻塞，补跑前置后自动恢复。':'无逐站结果。')+'</p>')
 +(rerun?'<button class="button" id="rerun-node" data-node="'+n.id+'">补跑此节点（后代失效重算）↻</button>':'')
 +(n.status==='blocked'&&canWrite()?'<p class="hint">请先补跑失败的前置节点。</p>':'')
 +'</section>';
}

function tracePanel(c){
 const station=c.stations.includes(traceStation)?traceStation:c.stations[0];
 if(!station)return '';
 traceStation=station;
 const rows=c.nodes.map(n=>{
   const r=n.result||{};
   let fate='待执行';
   if(n.status==='completed'){const s=(r.stations||[]).find(x=>x.station===station);fate=s?(s.passed?'通过':'被筛除：'+(s.note||'未达门槛')):'未进入候选（前置未通过）';}
   else if(n.status==='empty')fate='未进入候选（'+(r.reason||'前置为空')+'）';
   else if(n.status==='failed')fate='节点失败：'+(n.error||'');
   else if(n.status==='blocked')fate='阻塞：'+(n.error||'前置失败');
   return {node:n.name,status:ChainNodeStatus[n.status]||n.status,fate};
 });
 return '<section class="panel"><div class="section-title"><h2>站点追查</h2><span>筛选与阻塞原因</span></div><label>选择站点<select id="trace-station">'+c.stations.map(s=>'<option '+(s===station?'selected':'')+'>'+esc(s)+'</option>').join('')+'</select></label>'
 +table([{key:'node',label:'节点'},{key:'status',label:'节点状态'},{key:'fate',label:'该站去向'}],rows)+'</section>';
}

function briefingPanel(c){
 const b=c.briefing;
 if(!b)return '';
 const levels=b.levels.map(l=>'<div class="brief-level"><strong>'+esc(l.name)+'</strong><span>提前 '+l.lead_minutes+' 分钟 · 门槛 '+l.threshold+' · '+esc(ChainNodeStatus[l.status]||l.status)+'</span><div class="chips">'+(l.passed.length?l.passed.map(s=>'<span class="chip ok">'+esc(s)+'</span>').join(''):'<span class="chip">无通过站点</span>')+'</div></div>').join('');
 return '<section class="panel"><div class="section-title"><h2>已固定简报</h2><span>'+esc(b.approved_by)+' · '+date(b.approved_at)+'</span></div><p class="hint">各级采用结果已固定，分发内容以此为准；补跑任一节点将撤销批准并需重新整链复核。</p>'+levels+'</section>';
}

function detailView(c){
 const counts=c.counts||{},done=(counts.completed||0)+(counts.empty||0);
 const failed=c.nodes.filter(n=>n.status==='failed'),blocked=c.nodes.filter(n=>n.status==='blocked');
 const actions=[];
 if(c.status==='draft'&&canWrite()){actions.push('<button class="button primary" id="start-chain">启动研究链 ↗</button>','<button class="button" id="edit-chain">修改编排</button>','<button class="button" id="delete-chain">删除草稿</button>');}
 if(c.status==='completed'&&!c.approved&&session.user.role==='admin')actions.push('<button class="button primary" id="approve-chain">批准整链（固定简报）</button>');
 if(c.approved)actions.push('<a class="button" href="#/reports">前往分发档案 ↗</a>');
 actions.push('<button class="button" id="refresh-chain">刷新 ↻</button>');
 return heading('05 / REVIEW CHAIN',c.name,'数据集 #'+c.dataset_id+' · 冻结样本 '+c.sample_rows+' 条 · SHA256 '+esc((c.dataset_checksum||'').slice(0,18))+'…',actions.join(' '))
 +'<div class="result-selector"><span class="status '+esc(c.status)+'">'+esc(ChainStatus[c.status]||c.status)+'</span><span>节点 '+done+'/'+(counts.total||0)+' 完成</span>'+(c.started_at?'<span>启动 '+date(c.started_at)+'</span>':'')+(c.finished_at?'<span>收尾 '+date(c.finished_at)+'</span>':'')+'<span class="approval">'+(c.approved?'已获业务批准 · 简报已固定':c.status==='completed'?'待负责人批准':'')+'</span></div>'
 +(failed.length?'<p class="warning">失败节点：'+failed.map(n=>esc(n.name)+'（'+esc(n.error)+'）').join('；')+'。前置失败只阻塞后代，其他分支已继续；可补跑失败节点使后代失效重算。</p>':'')
 +(blocked.length?'<p class="warning">被阻塞：'+blocked.map(n=>esc(n.name)+'（'+esc(n.error)+'）').join('；')+'</p>':'')
 +(draft?composer():'')
 +'<div class="chain-layout"><section class="panel"><div class="section-title"><h2>依赖图</h2><span>点击节点查看逐站结果</span></div>'+graph(c)+'</section>'+nodePanel(c)+'</div>'
 +'<div class="two-columns">'+tracePanel(c)+briefingPanel(c)+'</div>';
}

export async function chainsPage(id){
 workspace.datasets=await datasets.list();
 if(!id){
   const list=await chains.list();
   if(draft&&!editingId&&draft.dataset_id===null)draft.dataset_id=workspace.datasets[0]?.id;
   return listView(list);
 }
 const c=await chains.get(id);
 workspace.chainDetail=c;
 if(editingId===c.id&&draft===null){/* keep editing state */}
 return detailView(c);
}

function bindComposer(refresh,chainId){
 const syncDraft=()=>{const f=document.querySelector('#chain-form');if(!f)return;const fd=new FormData(f);draft.name=String(fd.get('name')||'').trim();draft.dataset_id=Number(fd.get('dataset_id'));};
 document.querySelector('#add-node')?.addEventListener('click',()=>{
   syncDraft();
   const key=document.querySelector('#node-key').value.trim(),name=document.querySelector('#node-name').value.trim();
   const lag=Number(document.querySelector('#node-lag').value),threshold=Number(document.querySelector('#node-threshold').value);
   if(!/^[A-Za-z0-9_-]{1,40}$/.test(key))return notify('节点标识须为 1-40 位字母数字_- ',true);
   if(name.length<2)return notify('节点名称至少两个字符',true);
   if(draft.nodes.some(n=>n.key===key))return notify('节点标识已存在；重试不会重复建节点',true);
   if(!(threshold>=0&&threshold<=1))return notify('偏相关门槛须在 0 与 1 之间',true);
   draft.nodes.push({key,name,lag,threshold});
   refresh();
 });
 document.querySelector('#add-edge')?.addEventListener('click',()=>{
   syncDraft();
   const from=document.querySelector('#edge-from').value,to=document.querySelector('#edge-to').value;
   if(!from||!to)return;
   if(from===to)return notify('节点不能依赖自身',true);
   if(draft.edges.some(e=>e.from_key===from&&e.to_key===to))return notify('依赖边已存在',true);
   draft.edges.push({from_key:from,to_key:to});
   refresh();
 });
 document.querySelectorAll('[data-del-node]').forEach(b=>b.onclick=()=>{syncDraft();const k=draft.nodes[Number(b.dataset.delNode)].key;draft.nodes.splice(Number(b.dataset.delNode),1);draft.edges=draft.edges.filter(e=>e.from_key!==k&&e.to_key!==k);refresh();});
 document.querySelectorAll('[data-del-edge]').forEach(b=>b.onclick=()=>{syncDraft();draft.edges.splice(Number(b.dataset.delEdge),1);refresh();});
 document.querySelector('#cancel-edit')?.addEventListener('click',()=>{draft=null;editingId=null;refresh();});
 const form=document.querySelector('#chain-form');
 form?.addEventListener('submit',async e=>{
   e.preventDefault();
   const fd=new FormData(form);
   draft.name=String(fd.get('name')||'').trim();
   draft.dataset_id=Number(fd.get('dataset_id'));
   if(draft.name.length<2)return notify('研究链名称至少两个字符',true);
   if(!draft.nodes.length)return notify('至少需要一个研究节点',true);
   const payload={name:draft.name,dataset_id:draft.dataset_id,nodes:draft.nodes,edges:draft.edges};
   try{
     const saved=editingId?await chains.update(editingId,payload):await chains.create(payload);
     notify(editingId?'编排已保存':'研究链已创建，可启动');
     draft=null;editingId=null;
     location.hash='#/chains/'+saved.id;
     await refresh();
   }catch(err){notify(err.message,true);}
 });
}

export function bindChains(refresh){
 const id=location.hash.replace(/^#\//,'').split('/')[1];
 document.querySelector('#toggle-composer')?.addEventListener('click',()=>{draft=newDraft();draft.dataset_id=workspace.datasets[0]?.id;editingId=null;refresh();});
 bindComposer(refresh,id);
 document.querySelector('#start-chain')?.addEventListener('click',async()=>{try{await chains.start(id);notify('研究链已启动，样本与参数已冻结');await refresh();}catch(e){notify(e.message,true);}});
 document.querySelector('#edit-chain')?.addEventListener('click',async()=>{
   const c=workspace.chainDetail;
   draft={name:c.name,dataset_id:c.dataset_id,nodes:c.nodes.map(n=>({key:n.key,name:n.name,lag:n.lag,threshold:n.threshold})),edges:c.edges.map(e=>({from_key:e.from_key,to_key:e.to_key}))};
   editingId=c.id;refresh();
 });
 document.querySelector('#delete-chain')?.addEventListener('click',async()=>{if(!confirm('删除该编排草稿？'))return;try{await chains.remove(id);notify('草稿已删除');location.hash='#/chains';}catch(e){notify(e.message,true);}});
 document.querySelector('#approve-chain')?.addEventListener('click',async()=>{try{await chains.approve(id);notify('整链已批准，简报已固定');await refresh();}catch(e){notify(e.message,true);}});
 document.querySelector('#refresh-chain')?.addEventListener('click',refresh);
 document.querySelectorAll('.cnode').forEach(g=>g.addEventListener('click',()=>{selectedKey=g.dataset.node;refresh();}));
 document.querySelector('#rerun-node')?.addEventListener('click',async e=>{if(!confirm('补跑该节点？其全部后代结果将失效并重算，已在途旧结果不会写回。'))return;try{await chains.rerun(id,e.target.dataset.node);notify('已补跑，后代结果失效并重算');await refresh();}catch(err){notify(err.message,true);}});
 document.querySelector('#trace-station')?.addEventListener('change',e=>{traceStation=e.target.value;refresh();});
}
