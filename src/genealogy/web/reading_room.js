/* The family reading room: the tree page's "Branch cards" view. One band per generation, ancestors above the
   chosen person and descendants below; each person is an HTML card (so it can be read, searched and reached by
   keyboard) and the links between them are drawn in SVG behind the cards. tree.html loads this file before
   site.js; it only registers the view, and site.js hands it the shared data and helpers. Record values enter
   the DOM as text, never as markup. */
(() => {
'use strict';
const views = window.GENEALOGY_TREE_VIEWS = window.GENEALOGY_TREE_VIEWS || {};
views.branches = api => {
 const {personBy,placeBy,relationships,links,el,svgEl,name,lifespan,pe,year,assess,empty,PARENT_KINDS,PARTNER_KINDS,SIBLING_KINDS}=api;
 // Cards are this size in both directions; CHIPS is the least room above a card for the chips of its links.
 const CW=184,CH=74,CHIPS=36,PAD=28,CAP=120,MAX_UP=8,MAX_DOWN=6,RANK={documented:4,probable:3,possible:2};
 const kind=r=>String(r.kind||'').toLowerCase(),firm=r=>['documented','probable'].includes(assess(r).level);
 const rank=r=>(RANK[assess(r).level]||1)+(Number.isInteger(r.estimate)?r.estimate/1000:0);
 const birth=p=>pe(p).find(e=>e.kind==='birth'&&e.date)||pe(p).find(e=>e.kind==='baptism'&&e.date);
 const born=id=>year(birth(personBy.get(id))?.date);
 const order=(a,b)=>(born(a)??Infinity)-(born(b)??Infinity)||name(personBy.get(a)).localeCompare(name(personBy.get(b)))||a.localeCompare(b);
 const given=id=>{const n=personBy.get(id)?.names?.[0];return n?.given||String(name(personBy.get(id))).split(/\s+/)[0];};
 // Every parent link that is not rejected counts, so competing fathers or mothers are all drawn; a pair recorded
 // twice is one link at its firmer assessment. Rejected (disproved) links are kept apart for the strips.
 const parentsOf=new Map,childrenOf=new Map,partnersOf=new Map,siblingsOf=new Map,rejectedParents=new Map,rejectedChildren=new Map;
 const add=(m,a,row)=>{if(!m.has(a))m.set(a,[]);const list=m.get(a),old=list.find(x=>x.id===row.id);if(!old)list.push(row);else if(rank(row.r)>rank(old.r))old.r=row.r;};
 for(const r of relationships){
  const k=kind(r),out=assess(r).level==='disproved';if(r.subject_id===r.object_id||!personBy.has(r.subject_id)||!personBy.has(r.object_id))continue;
  if(PARENT_KINDS.includes(k)){add(out?rejectedParents:parentsOf,r.subject_id,{id:r.object_id,r});add(out?rejectedChildren:childrenOf,r.object_id,{id:r.subject_id,r});}
  else if(!out&&PARTNER_KINDS.includes(k)){add(partnersOf,r.subject_id,{id:r.object_id,r});add(partnersOf,r.object_id,{id:r.subject_id,r});}
  else if(!out&&SIBLING_KINDS.includes(k)){add(siblingsOf,r.subject_id,{id:r.object_id,r});add(siblingsOf,r.object_id,{id:r.subject_id,r});}}
 for(const m of [childrenOf,partnersOf,siblingsOf])m.forEach(list=>list.sort((a,b)=>order(a.id,b.id)));
 // A link both accepted and rejected (two records of one pair) is shown once, as accepted.
 const rejectedOf=(m,accepted,id)=>(m.get(id)||[]).filter(x=>!(accepted.get(id)||[]).some(y=>y.id===x.id));
 // A parent is a father or mother by the link's kind, else by their recorded sex, as the catalogue reads it.
 const role=(r,parent)=>{const k=kind(r),s=personBy.get(parent)?.sex;return k==='father'||k!=='mother'&&s==='M'?'father':k==='mother'||s==='F'?'mother':'parent';};
 const PED={adopted:'Adoptive ',adoptive:'Adoptive ',foster:'Foster ',step:'Step-'};
 const roleWord=(r,parent)=>{const w=role(r,parent),p=r.pedigree&&r.pedigree!=='birth'?PED[r.pedigree]||`${r.pedigree} `:'';return p?p+w:w[0].toUpperCase()+w.slice(1);};
 const ROLE_ORDER={father:0,parent:1,mother:2};
 // Parent sets: the best-assessed father and mother first, then each other candidate (with a recorded partner among
 // the candidates beside them), so competing hypotheses stand side by side rather than one hiding the other.
 const setsOf=id=>{
  const rows=[...(parentsOf.get(id)||[])].map(x=>({...x,role:role(x.r,x.id)})).sort((a,b)=>rank(b.r)-rank(a.r)||order(a.id,b.id));
  const count=w=>rows.filter(x=>x.role===w).length,competing=count('father')>1||count('mother')>1||rows.length>2,left=[...rows];
  const take=test=>{const i=left.findIndex(test);return i<0?null:left.splice(i,1)[0];};
  const first=[take(x=>x.role==='father'),take(x=>x.role==='mother')].filter(Boolean);while(first.length<2&&left.some(x=>x.role==='parent'))first.push(take(x=>x.role==='parent'));
  const sets=first.length?[first]:[];
  while(left.length){const a=left.shift(),partners=(partnersOf.get(a.id)||[]).map(p=>p.id),b=take(x=>x.role!==a.role&&partners.includes(x.id));sets.push(b?[a,b]:[a]);}
  sets.forEach(s=>s.sort((a,b)=>ROLE_ORDER[a.role]-ROLE_ORDER[b.role]));return {sets,competing};};
 const ordinal=n=>n+(n%10===1&&n%100!==11?'st':n%10===2&&n%100!==12?'nd':n%10===3&&n%100!==13?'rd':'th');
 const bandName=g=>g===0?'This generation':g>0?(['','Parents','Grandparents','Great-grandparents'][g]||`${ordinal(g-2)} great-grandparents`):(['','Children','Grandchildren','Great-grandchildren'][-g]||`${ordinal(-g-2)} great-grandchildren`);
 const many=(n,one,more)=>`${n} ${n===1?one:more}`;
 // The settings outlive a redraw, so centring on a relative keeps the generations and direction chosen.
 const settings={up:3,down:2,siblings:true,horizontal:false},openUp=new Set,shutUp=new Set,openDown=new Set,shutDown=new Set;let lastFocus=null;
 const chevron=up=>{const s=svgEl('svg',{viewBox:'0 0 16 16',width:14,height:14,'aria-hidden':'true',focusable:'false'});s.append(svgEl('path',{d:up?'M3 10l5-5 5 5':'M3 6l5 5 5-5',fill:'none',stroke:'currentColor','stroke-width':2,'stroke-linecap':'round'}));return s;};

 return function readingRoom(output,root,refocus){
  const id=root.value||[...personBy.keys()][0];if(!personBy.has(id)){output.append(empty('No public people available to draw.'));return {zoom(){},fit(){},dispose(){}};}
  if(id!==lastFocus){[openUp,shutUp,openDown,shutDown].forEach(s=>s.clear());lastFocus=id;}
  const host=el('section',undefined,'reading-room');host.dataset.readingRoom='';host.setAttribute('aria-labelledby','rr-title');
  const head=el('div',undefined,'rr-head'),title=el('h2',`${given(id)} & family`);title.id='rr-title';
  head.append(el('p','The family reading room','eyebrow'),title,el('p','Ancestors above, descendants below, one band per generation. Use − / + for more generations; the round buttons open or fold away one line.','hint'));
  const controls=el('div',undefined,'rr-controls'),status=el('p','','sr-only');status.setAttribute('role','status');
  const back=el('button','← Back to canopy');back.type='button';back.addEventListener('click',()=>document.querySelector('.tree-modes button')?.click());
  const stepper=(label,key,max)=>{const g=el('span',undefined,'rr-step');g.setAttribute('role','group');g.setAttribute('aria-label',label);const less=el('button','−'),more=el('button','+'),value=el('output',String(settings[key]));
   less.type=more.type='button';less.setAttribute('aria-label',`Fewer ${label.toLowerCase()} generations`);more.setAttribute('aria-label',`More ${label.toLowerCase()} generations`);
   const sync=()=>{value.textContent=String(settings[key]);less.disabled=settings[key]<=0;more.disabled=settings[key]>=max;};
   // A new count is the rule again: lines opened or folded one by one in that direction are reset.
   const step=d=>{settings[key]=Math.min(max,Math.max(0,settings[key]+d));(key==='up'?[openUp,shutUp]:[openDown,shutDown]).forEach(x=>x.clear());sync();build();status.textContent=`${label}: ${settings[key]} ${settings[key]===1?'generation':'generations'}.`;};
   less.addEventListener('click',()=>step(-1));more.addEventListener('click',()=>step(1));g.append(el('span',label),less,value,more);sync();return g;};
  const toggle=(label,on,act)=>{const b=el('button',label);b.type='button';b.setAttribute('aria-pressed',String(on));b.addEventListener('click',act);return b;};
  const siblings=toggle('Siblings',settings.siblings,()=>{settings.siblings=!settings.siblings;siblings.setAttribute('aria-pressed',String(settings.siblings));build();status.textContent=settings.siblings?'Siblings shown.':'Siblings hidden.';});
  const direction=el('span',undefined,'rr-direction');direction.setAttribute('role','group');direction.setAttribute('aria-label','Direction');
  const vertical=toggle('↕ Vertical',!settings.horizontal,()=>turn(false)),horizontal=toggle('↔ Horizontal',settings.horizontal,()=>turn(true));direction.append(vertical,horizontal);
  function turn(h){settings.horizontal=h;vertical.setAttribute('aria-pressed',String(!h));horizontal.setAttribute('aria-pressed',String(h));build();}
  controls.append(back,stepper('Ancestors','up',MAX_UP),stepper('Descendants','down',MAX_DOWN),siblings,direction);
  const viewport=el('div',undefined,'rr-viewport'),sizer=el('div',undefined,'rr-sizer'),stage=el('div');viewport.append(sizer);sizer.append(stage);
  const foot=el('div',undefined,'rr-foot'),count=el('strong'),zoomed=el('span','100%','rr-zoom'),note=el('p','','hint');
  foot.append(count,zoomed);
  const key=el('p','Solid lines: documented or probable parent links. Dashed: possible or unassessed links, and alternative parents. Dotted: partners and co-parents. Each chip gives a link\'s assessment; rejected links are listed under their band. Recorded connections are not proof.','hint rr-key');
  host.append(head,controls,viewport,foot,note,key,status);output.append(host);
  let scale=1,width=0,height=0,nodes=[];
  const apply=()=>{stage.style.transform=`scale(${scale})`;sizer.style.width=`${width*scale}px`;sizer.style.height=`${height*scale}px`;zoomed.textContent=`${Math.round(scale*100)}%`;};
  const zoom=f=>{scale=Math.min(2,Math.max(.3,scale*f));apply();};
  const fit=()=>{scale=Math.min(1,Math.max(.3,Math.min((viewport.clientWidth-4)/width,(window.innerHeight*.7)/height)));apply();};

  function build(keep){
   const seen=new Map,edges=[],joins=new Map;let over=0,maxUp=0,maxDown=0;
   const node=(pid,gen,side,from,r,extra={})=>{const n={id:pid,gen,side,from,r,sets:[],kids:[],partners:[],capped:0,...extra};seen.set(pid,n);return n;};
   const room=n=>{if(seen.size<CAP)return true;n.capped++;over++;return false;};
   const join=(a,b,r,cls)=>joins.set([a.id,b.id].sort().join('\n'),{a,b,r,cls});
   const focus=node(id,0,'focus',null,null),row=[focus];
   // This generation: the person and, with Siblings on, their parents' other children and recorded siblings.
   if(settings.siblings){const sib=new Map;for(const p of parentsOf.get(id)||[])for(const c of childrenOf.get(p.id)||[])if(c.id!==id)sib.set(c.id,null);
    for(const s of siblingsOf.get(id)||[])if(!sib.has(s.id))sib.set(s.id,s.r);
    for(const [sid,r] of sib)if(!seen.has(sid)&&room(focus))row.push(node(sid,0,'sibling',focus,r));row.sort((a,b)=>order(a.id,b.id));}
   const partnersFor=n=>{for(const {id:pid,r} of partnersOf.get(n.id)||[]){if(seen.has(pid)){join(n,seen.get(pid),r,'rr-partner');continue;}if(!room(n))continue;const m=node(pid,n.gen,'partner',n,r);n.partners.push(m);join(n,m,r,'rr-partner');}};
   partnersFor(focus);
   // Nearer generations fill the profile limit before farther ones, on both sides.
   let up=[focus],down=[...row];
   for(let g=1;g<=Math.max(MAX_UP,MAX_DOWN)&&(up.length||down.length);g++){const nextUp=[],nextDown=[];
    for(const n of up){const {sets,competing}=setsOf(n.id);n.above=sets.flat().length;n.rejected=rejectedOf(rejectedParents,parentsOf,n.id);n.competing=competing;
     n.canUp=(n.above||n.rejected.length)>0&&g<=MAX_UP;if(!n.canUp||!(openUp.has(n.id)||g<=settings.up&&!shutUp.has(n.id)))continue;
     n.openUp=true;maxUp=Math.max(maxUp,g);
     sets.forEach((set,i)=>{const drawn=[];for(const p of set){const alt=competing&&i>0;
      if(seen.has(p.id)){edges.push({parent:seen.get(p.id),child:n,r:p.r,role:p.role,alt});continue;}if(!room(n))continue;
      const m=node(p.id,g,'up',n,p.r,{role:p.role,alt});drawn.push(m);edges.push({parent:m,child:n,r:p.r,role:p.role,alt});nextUp.push(m);}
      if(drawn.length===2)join(drawn[0],drawn[1],null,'rr-coparent');if(drawn.length)n.sets.push(drawn);});}
    for(const n of down){const kids=childrenOf.get(n.id)||[];n.below=kids.length;n.rejectedKids=rejectedOf(rejectedChildren,childrenOf,n.id);
     // A sibling's line stays folded until asked for; the person's own descendants open to the chosen depth.
     n.canDown=(n.below||n.rejectedKids.length)>0&&g<=MAX_DOWN;if(!n.canDown||!(openDown.has(n.id)||n.side!=='sibling'&&g<=settings.down&&!shutDown.has(n.id)))continue;
     n.openDown=true;maxDown=Math.max(maxDown,g);
     for(const {id:cid,r} of kids){if(seen.has(cid)){edges.push({parent:n,child:seen.get(cid),r,role:role(r,n.id)});continue;}if(!room(n))continue;
      const c=node(cid,g,'down',n,r);n.kids.push(c);edges.push({parent:n,child:c,r,role:role(r,n.id)});
      for(const p of n.partners){const link=(parentsOf.get(cid)||[]).find(x=>x.id===p.id);if(link)edges.push({parent:p,child:c,r:link.r,role:role(link.r,p.id)});}
      partnersFor(c);nextDown.push(c);}}
    up=g<MAX_UP?nextUp:[];down=g<MAX_DOWN?nextDown:[];}
   // A sibling's links to the parents drawn above them.
   for(const s of row)if(s.side==='sibling')for(const p of parentsOf.get(s.id)||[]){const m=seen.get(p.id);if(m&&m.side==='up'&&m.gen===1)edges.push({parent:m,child:s,r:p.r,role:role(p.r,p.id)});}
   nodes=[...seen.values()];
   // Tidy layout along each band: a line is as wide as its widest generation and a card sits centred over the cards
   // it leads to. Parent sets are spaced apart so alternatives read as separate hypotheses.
   // Room above each card for its chips: a band is as tall as its most-linked card needs (in rows of chips).
   const chipCount=n=>edges.filter(e=>e.child===n).length+(n.side==='partner'&&n.r||n.side==='sibling'&&n.r?1:0),chipRoom=k=>Math.max(CHIPS,k*23+14);
   const S=settings.horizontal?chipRoom(Math.max(...nodes.map(chipCount)))+CH+12:CW,G=settings.horizontal?10:18,SG=G*3;
   const unit=n=>S+n.partners.length*(S+G);
   const dw=n=>n.dw=Math.max(unit(n),n.kids.reduce((s,k)=>s+dw(k),0)+G*Math.max(0,n.kids.length-1));
   const rowW=row.reduce((s,n)=>s+dw(n),0)+G*(row.length-1);
   const inner=n=>n.sets.reduce((s,set)=>s+set.reduce((t,m)=>t+m.uw,0)+G*(set.length-1),0)+SG*Math.max(0,n.sets.length-1);
   const uw=(n,u)=>{n.sets.flat().forEach(m=>uw(m,S));return n.uw=Math.max(u,inner(n));};
   const upW=uw(focus,rowW),total=Math.max(rowW,upW);
   const placeDown=(n,x0)=>{n.a=x0+(n.dw-unit(n))/2;n.partners.forEach((p,i)=>p.a=n.a+(i+1)*(S+G));let x=x0+(n.dw-(n.kids.reduce((s,k)=>s+k.dw,0)+G*Math.max(0,n.kids.length-1)))/2;for(const k of n.kids){placeDown(k,x);x+=k.dw+G;}};
   const placeUp=(n,x0,u)=>{if(n!==focus)n.a=x0+(n.uw-u)/2;let x=x0+(n.uw-inner(n))/2;n.sets.forEach((set,i)=>{if(i)x+=SG;set.forEach((m,j)=>{if(j)x+=G;placeUp(m,x,S);x+=m.uw;});});};
   {let x=(total-rowW)/2;for(const n of row){placeDown(n,x);x+=n.dw+G;}}placeUp(focus,(total-upW)/2,rowW);
   const band=n=>{const owner=n.side==='partner'?n.from:n;return owner.side==='up'?maxUp-owner.gen:maxUp+owner.gen;};
   const gens=[];for(let g=maxUp;g>=-maxDown;g--)gens.push(g);
   // The DOM: one section per band (a heading, a lane holding the cards, then any rejected links), lines behind.
   stage.className=`rr-stage ${settings.horizontal?'rr-horizontal':'rr-vertical'}`;
   const svg=svgEl('svg',{class:'rr-lines','aria-hidden':'true',focusable:'false'}),lanes=[],strips=gens.map(()=>[]);stage.replaceChildren(svg);
   const laneW=settings.horizontal?CW+PAD*2+24:total+PAD*2;
   for(const n of nodes){if(n.openUp)for(const x of n.rejected)strips[band(n)-1].push({parent:x.id,child:n.id,r:x.r});if(n.openDown)for(const x of n.rejectedKids)strips[band(n)+1].push({parent:n.id,child:x.id,r:x.r});}
   gens.forEach((g,b)=>{
    const members=nodes.filter(n=>band(n)===b),years=members.map(n=>born(n.id)).filter(y=>y!==null),label=bandName(g)+(years.length?` · born ${Math.min(...years)}${Math.max(...years)!==Math.min(...years)?`–${Math.max(...years)}`:''}`:'');
    const section=el('section',undefined,`rr-band${g===0?' rr-here':''}`),h=el('h3',label,'rr-band-label');h.id=`rr-band-${b}`;section.setAttribute('aria-labelledby',h.id);section.dataset.generation=String(g);
    const lane=el('div',undefined,'rr-lane'),top=settings.horizontal?S-CH-12:chipRoom(Math.max(0,...members.map(chipCount)));members.forEach(n=>n.top=settings.horizontal?PAD+n.a+top:top);
    lane.style.width=`${laneW}px`;lane.style.height=`${settings.horizontal?total+PAD*2:top+CH+22}px`;section.append(h,lane);lanes.push(lane);
    members.sort((x,y)=>x.a-y.a).forEach(n=>lane.append(card(n)));
    if(strips[b].length){const strip=el('div',undefined,'rr-rejected'),list=el('ul');strip.append(el('strong','Rejected'),list);
     for(const x of strips[b]){const li=el('li');li.append(link(x.parent),` as ${roleWord(x.r,x.parent).toLowerCase()} of `,link(x.child),' ');li.append(chip(assess(x.r)));list.append(li);}section.append(strip);}
    stage.append(section);});
   function link(pid){const p=personBy.get(pid);if(!links[pid])return document.createTextNode(name(p));const a=el('a',name(p));a.href=links[pid];return a;}
   function chip(a,text){return el('span',text||a.words,`badge badge-${a.family} rr-chip`);}
   function card(n){
    const p=personBy.get(n.id),wrap=el('div',undefined,`rr-person rr-${n.side}${n.alt?' rr-alt':''}${n.r&&!firm(n.r)&&n.side!=='sibling'?' rr-uncertain':''}`);wrap.dataset.person=n.id;
    wrap.style.left=`${settings.horizontal?PAD:PAD+n.a}px`;wrap.style.top=`${n.top}px`;wrap.style.width=`${CW}px`;wrap.style.height=`${CH}px`;
    // Chips: the person's links to the parents drawn above them, worded "Father: Probable · 84%".
    const chips=el('ul',undefined,'rr-links'),mine=edges.filter(e=>e.child===n).sort((a,b)=>ROLE_ORDER[a.role]-ROLE_ORDER[b.role]||rank(b.r)-rank(a.r));chips.setAttribute('aria-label',`Links of ${name(p)}`);
    const competing=n.competing||mine.filter(e=>e.role==='father').length>1||mine.filter(e=>e.role==='mother').length>1;
    for(const e of mine){const li=el('li'),a=assess(e.r),who=name(personBy.get(e.parent.id));li.append(chip(a,`${roleWord(e.r,e.parent.id)}${competing?` (${given(e.parent.id)})`:''}: ${a.words}`));if(!competing)li.firstChild.append(el('span',` (${who})`,'sr-only'));chips.append(li);}
    if(n.side==='partner'&&n.r){const a=assess(n.r),li=el('li');li.append(chip(a,`${['spouse','husband','wife','marriage'].includes(kind(n.r))?'Spouse':'Partner'}: ${a.words}`));li.firstChild.append(el('span',` (of ${name(personBy.get(n.from.id))})`,'sr-only'));chips.append(li);}
    if(n.side==='sibling'&&n.r){const a=assess(n.r),li=el('li');li.append(chip(a,`Sibling: ${a.words}`));chips.append(li);}
    if(chips.childElementCount)wrap.append(chips);
    const box=el('div',undefined,'rr-card'),focusCard=n.side==='focus';let title;
    if(focusCard){title=links[n.id]?el('a',name(p),'rr-name'):el('strong',name(p),'rr-name');if(links[n.id]){title.href=links[n.id];title.append(el('span',', open the dossier','sr-only'));}}
    else{title=el('button',name(p),'rr-name');title.type='button';title.append(el('span',', centre the reading room here','sr-only'));title.addEventListener('click',()=>refocus(n.id));}
    box.append(title,el('span',lifespan(p)||'Dates not recorded','rr-years'));
    const place=placeBy.get(birth(p)?.place_id)?.name;if(place)box.append(el('span',place,'rr-place'));
    const tag=n.alt?`Alternative ${n.role} of ${given(n.from.id)}`:n.side==='partner'?`Partner of ${given(n.from.id)}`:n.side==='sibling'?'Sibling':n.capped?`${n.capped} more not drawn`:'';
    if(tag)box.append(el('span',tag,'rr-tag'));wrap.append(box);
    // The round buttons open or fold one line: the parents above a card, or the children below it.
    const fold=(dir,open,hidden,noun)=>{const b=el('button',undefined,`rr-fold rr-fold-${dir}`);b.type='button';b.dataset.fold=dir;b.setAttribute('aria-expanded',String(open));
     b.setAttribute('aria-label',`${open?'Fold away':'Open'} the ${noun} of ${name(p)}${open?'':` (${hidden})`}`);b.append(chevron(dir==='up'?!open:open));
     b.addEventListener('click',()=>{const [o,s]=dir==='up'?[openUp,shutUp]:[openDown,shutDown];if(open){s.add(n.id);o.delete(n.id);}else{o.add(n.id);s.delete(n.id);}build(`${n.id}\n${dir}`);status.textContent=`${open?'Folded away':'Showing'} the ${noun} of ${name(p)}.`;});wrap.append(b);};
    if((n.side==='focus'||n.side==='up')&&n.canUp)fold('up',!!n.openUp,many(n.above,'parent','parents'),'parents');
    if(['focus','sibling','down'].includes(n.side)&&n.canDown)fold('down',!!n.openDown,many(n.below,'child','children'),'children');
    n.el=wrap;return wrap;}
   // Lines, from where the lanes landed (measured unscaled) and the card positions just laid out.
   stage.style.minWidth=`${viewport.clientWidth/scale}px`;width=stage.offsetWidth;height=stage.offsetHeight;
   const origin=stage.getBoundingClientRect(),at=lanes.map(l=>{const q=l.getBoundingClientRect();return {x:(q.left-origin.left)/scale,y:(q.top-origin.top)/scale};});
   svg.setAttribute('width',width);svg.setAttribute('height',height);svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
   const box=n=>{const lane=at[band(n)],x=lane.x+parseFloat(n.el.style.left),y=lane.y+parseFloat(n.el.style.top);return {x,y,cx:x+CW/2,cy:y+CH/2,r:x+CW,b:y+CH,lane};};
   const path=(d,cls)=>svg.append(svgEl('path',{d,class:cls}));
   const exit=n=>{const q=box(n);return settings.horizontal?{x:q.r,y:q.cy}:{x:q.cx,y:q.b};};
   const enter=(from,n)=>{const q=box(n);return settings.horizontal?`M${from.x},${from.y} H${q.lane.x+12} V${q.cy} H${q.x}`:`M${from.x},${from.y} V${q.lane.y+5} H${q.cx} V${q.y}`;};
   const middle=j=>{const a=box(j.a),b=box(j.b);if(settings.horizontal){const x=Math.max(a.r,b.r)+10;return {x,y:(a.cy+b.cy)/2,d:`M${a.r},${a.cy} H${x} V${b.cy} H${b.r}`};}const [l,r]=a.x<b.x?[a,b]:[b,a];return {x:(l.r+r.x)/2,y:l.cy,d:`M${l.r},${l.cy} H${r.x}`};};
   joins.forEach(j=>path(middle(j).d,`rr-join ${j.cls}${j.r&&!firm(j.r)?' rr-uncertain':''}`));
   for(const child of nodes){const mine=edges.filter(e=>e.child===child);while(mine.length){const e=mine.shift(),i=mine.findIndex(f=>joins.has([e.parent.id,f.parent.id].sort().join('\n'))),f=i<0?null:mine.splice(i,1)[0];
     const from=f?middle(joins.get([e.parent.id,f.parent.id].sort().join('\n'))):exit(e.parent),loose=[e,f].filter(Boolean).some(x=>!firm(x.r)),alt=[e,f].filter(Boolean).some(x=>x.alt);
     path(enter(from,child),`rr-link${loose||alt?' rr-uncertain':''}${alt?' rr-alt':''}`);}}
   const shown=nodes.length,parts=[`${shown} family ${shown===1?'profile':'profiles'}`];count.textContent=parts[0];
   note.textContent=over?`${over} more not drawn (${CAP}-profile limit); centre on a relative to see them.`:nodes.length===1?`No parents, partners, children or siblings of ${name(personBy.get(id))} are recorded publicly.`:'';note.hidden=!note.textContent;
   apply();
   if(keep){const [pid,dir]=keep.split('\n');stage.querySelector(`[data-person="${CSS.escape(pid)}"] [data-fold="${dir}"]`)?.focus();}
   else{const q=box(focus);viewport.scrollLeft=Math.max(0,q.cx*scale-viewport.clientWidth/2);viewport.scrollTop=Math.max(0,q.cy*scale-viewport.clientHeight/2);}
  }
  // Arrow keys move between cards: along a band, or to the nearest card in the band before or after.
  stage.addEventListener('keydown',e=>{const from=e.target.closest?.('.rr-name');if(!from||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;
   const cardOf=n=>n.el,me=nodes.find(n=>n.el.contains(from));if(!me)return;const bandOf=n=>Number(n.el.closest('.rr-band').dataset.generation);
   const along=settings.horizontal?['ArrowUp','ArrowDown']:['ArrowLeft','ArrowRight'],step=e.key===along[0]||e.key===(settings.horizontal?'ArrowLeft':'ArrowUp')?-1:1;
   let target;if(along.includes(e.key)){const same=nodes.filter(n=>bandOf(n)===bandOf(me)).sort((a,b)=>a.a-b.a);target=same[same.indexOf(me)+step];}
   else{const other=nodes.filter(n=>bandOf(n)===bandOf(me)-step);target=other.sort((a,b)=>Math.abs(a.a-me.a)-Math.abs(b.a-me.a))[0];}
   if(target){e.preventDefault();cardOf(target).querySelector('.rr-name')?.focus();}});
  build();
  // The address names this view and person, so it can be bookmarked or shared; leaving the view clears it.
  const address=`#view=branches&person=${encodeURIComponent(id)}`;try{if(location.hash!==address)history.replaceState(history.state,'',location.pathname+location.search+address);}catch(_){/* file:// pages may refuse */}
  return {zoom,fit,dispose(){try{if(/(^#|&)view=branches(&|$)/.test(location.hash))history.replaceState(history.state,'',location.pathname+location.search);}catch(_){/* as above */}}};
 };
};
})();
