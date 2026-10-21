/* Offline progressive enhancements. All record values enter the DOM as text. */
(() => {
'use strict';
const scriptSource = document.currentScript?.src || location.href;
const raw = document.getElementById('site-data');
let page = {}; try { page = raw ? JSON.parse(raw.textContent) : {}; } catch (_) { page = {}; }
// Interactive pages load one shared data script; older builds embedded it here.
let data = window.GENEALOGY_SITE_DATA || page;
if (!data || typeof data !== 'object') data = {};
const root = page.site?.root ?? '';
const list = key => Array.isArray(data[key]) ? data[key] : Object.values(data[key] || {});
const people=list('people'), events=list('events'), places=list('places'), relationships=list('relationships'), claims=list('claims');
const personBy=new Map(people.map(p=>[p.id,p])), eventBy=new Map(events.map(e=>[e.id,e])), placeBy=new Map(places.map(p=>[p.id,p]));
// Only citations that state their quality or information are shipped.
const citationBy=new Map(list('citations').map(c=>[c.id,c]));
const links=Object.fromEntries(Object.entries(data.site?.people_urls||{}).map(([id,url])=>[id,window.GENEALOGY_SITE_DATA?root+url:url]));
const $=(s,r=document)=>r.querySelector(s);
const $$=(s,r=document)=>[...r.querySelectorAll(s)];
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=String(text);if(cls)n.className=cls;return n;};
const svgEl=(tag,attrs={})=>{const n=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,String(v)));return n;};
const name=p=>p?.names?.[0]?.value||p?.id||'Unknown person';
const norm=v=>String(v??'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
// [names.variants]: every listed spelling (casefolded) and its canonical surname.
const VARIANTS=new Map(Object.entries(data.site?.name_variants||{}));
const canonical=s=>VARIANTS.get(String(s||'').toLowerCase())||s||'';
// Search text and queries rewrite each listed spelling to the canonical one, so any spelling finds them all.
const FOLD=new Map([...VARIANTS].map(([k,v])=>[norm(k),norm(v)]).filter(([k,v])=>k&&k!==v));
const escapeRe=k=>k.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
const FOLD_RE=FOLD.size?new RegExp('(?<![\\p{L}\\p{N}])(?:'+[...FOLD.keys()].sort((a,b)=>b.length-a.length).map(escapeRe).join('|')+')(?![\\p{L}\\p{N}])','gu'):null;
const fold=v=>FOLD_RE?norm(v).replace(FOLD_RE,t=>FOLD.get(t)):norm(v);
const eventsByPerson=new Map,relationsByPerson=new Map,claimsByPerson=new Map;
for(const e of events)for(const id of e.participant_ids||[]){if(!eventsByPerson.has(id))eventsByPerson.set(id,new Map);eventsByPerson.get(id).set(e.id,e);}
for(const p of people)for(const id of p.event_ids||[]){if(!eventsByPerson.has(p.id))eventsByPerson.set(p.id,new Map);if(eventBy.has(id))eventsByPerson.get(p.id).set(id,eventBy.get(id));}
for(const r of relationships)for(const id of new Set([r.subject_id,r.object_id])){if(!relationsByPerson.has(id))relationsByPerson.set(id,[]);relationsByPerson.get(id).push(r);}
for(const c of claims){if(!claimsByPerson.has(c.subject_id))claimsByPerson.set(c.subject_id,[]);claimsByPerson.get(c.subject_id).push(c);}
const CONFIDENCE={documented:'Documented',probable:'Probable',possible:'Possible',disproved:'Disproved'};
const BROAD=new Set(['parish','district','county','region','country','approximate']);
const GRADES=data.site?.grades||{};
const relLabel=r=>[(GRADES[r?.grade]||CONFIDENCE[r?.confidence]||'Unassessed tree link')+(Number.isInteger(r?.estimate)?` (${r.estimate}%)`:''),r?.tree_status?`tree-marked ${r.tree_status}`:''].filter(Boolean).join(' · ');
// Recorded sibling links are drawn beside their sibling in the family view.
const SIBLING_KINDS=['sibling','brother','sister','half_sibling','half-sibling'];
const relKind=r=>r?.pedigree&&r.pedigree!=='birth'?`${r.kind} (${r.pedigree})`:(r?.kind||'relationship');
const pe=p=>[...(eventsByPerson.get(p.id)?.values()||[])];
const year=v=>{const m=String(v||'').match(/\b(\d{3,4})\b/);return m?Number(m[1]):null;};
// A person's events in date order, their surname and recorded lifespan, as the catalogue rows show them.
const byDate=(a,b)=>(year(a.date)??Infinity)-(year(b.date)??Infinity)||String(a.date||'').localeCompare(String(b.date||''))||a.id.localeCompare(b.id);
const surnameOf=p=>(p?.names||[]).find(n=>n.surname)?.surname||'';
const QUALIFIER={BEF:'bef. ',BEFORE:'bef. ',AFT:'aft. ',AFTER:'aft. '};
const lifespan=p=>{const ev=pe(p).sort(byDate);return [['birth','b.'],['death','d.']].map(([kind,label])=>{const e=ev.find(x=>x.kind===kind&&x.date);const y=e&&year(e.date);if(!y)return '';const q=/^\s*(ABOUT|ABT|EST|CAL|CIRCA|CA|C|BEF|BEFORE|AFT|AFTER|BET|FROM|INT)\b/i.exec(e.date);return `${label} ${q?(QUALIFIER[q[1].toUpperCase()]||'c. '):''}${y}`;}).filter(Boolean).join(' – ');};
const linkTo=(id,label)=>{if(!links[id])return document.createTextNode(label);const a=el('a',label);a.href=links[id];return a;};
const dates=p=>{const e=pe(p);return ['birth','death'].map(k=>e.find(x=>x.kind===k)?.date||'Unknown');};
const relativeIds=id=>[...new Set((relationsByPerson.get(id)||[]).map(r=>r.subject_id===id?r.object_id:r.subject_id))];
const personLink=p=>{const a=el('a',name(p));if(links[p.id])a.setAttribute('href',links[p.id]);return a;};
const announce=t=>{const s=$('#site-status');if(s)s.textContent=t;};
const empty=t=>el('p',t,'empty-state');
const field=(label,control)=>{const l=el('label',label);l.append(control);return l;};
const option=(value,text)=>{const n=el('option',text);n.value=value;return n;};
const select=(items)=>{const n=el('select');items.forEach(([v,t])=>n.append(option(v,t)));return n;};
const menu=$('#menu-toggle');if(menu)menu.addEventListener('click',()=>{const open=menu.getAttribute('aria-expanded')!=='true';menu.setAttribute('aria-expanded',String(open));$('#site-sidebar')?.classList.toggle('menu-open',open);});
const view=document.body.dataset.view;
$$('.site-sidebar a[data-view]').forEach(a=>{if(a.dataset.view===view)a.setAttribute('aria-current','page');});

// Catalogue: retain the complete server-rendered table and filter its rows.
// A large site writes only a placeholder into its person menus; fill them from the data.
function fillPeople(menu){if(menu.options.length>1)return;const sorted=[...people].sort((x,y)=>name(x).localeCompare(name(y))||x.id.localeCompare(y.id));const fragment=document.createDocumentFragment();sorted.forEach(p=>fragment.append(option(p.id,name(p))));menu.append(fragment);}
// ?a= and ?b= (a dossier's explore links) preselect people once the menus are filled; with only one chosen, the other menu takes focus.
function preselect(a,b){const params=new URLSearchParams(location.search);for(const [menu,key] of [[a,'a'],[b,'b']]){const id=params.get(key);if(id&&personBy.has(id))menu.value=id;}if(!a.value!==!b.value)(a.value?b:a).focus();}
// The catalogue's research filters, on public data only: recorded sex, recorded family links, birth and death years, and event places.
// A disproved link is set apart on the dossier and counts for nothing here (validation keeps a grade counted as disproved at that confidence).
const PARENT_KINDS=['parent','father','mother','biological_parent','adoptive_parent','parent_child'],PARTNER_KINDS=['spouse','partner','husband','wife','marriage'],SEX_LABEL={F:'Female',M:'Male'};
function researchFilters(records){
 const parents=new Set,children=new Set,partners=new Set;
 for(const r of relationships){if(r.confidence==='disproved')continue;const k=String(r.kind||'').toLowerCase();if(PARENT_KINDS.includes(k)){parents.add(r.subject_id);children.add(r.object_id);}else if(PARTNER_KINDS.includes(k)){partners.add(r.subject_id);partners.add(r.object_id);}}
 const first=(ev,kind)=>{const e=ev.find(x=>x.kind===kind&&year(x.date)!==null);return e?year(e.date):null;};
 records.forEach(r=>{const id=r.p?.id,ev=r.p?pe(r.p).sort(byDate):[];Object.assign(r,{sex:r.p?.sex||'',birth:first(ev,'birth'),death:first(ev,'death'),places:[...new Set(ev.map(e=>norm(placeBy.get(e.place_id)?.name)).filter(Boolean))],parent:parents.has(id),children:children.has(id),partner:partners.has(id)});});
 const sexCounts=new Map;records.forEach(r=>sexCounts.set(r.sex,(sexCounts.get(r.sex)||0)+1));
 const recorded=[...sexCounts.keys()].filter(Boolean).sort((a,b)=>(a in SEX_LABEL?0:1)-(b in SEX_LABEL?0:1)||a.localeCompare(b));
 const sex=select([['','Any'],...recorded.map(v=>[v,`${SEX_LABEL[v]||v} (${sexCounts.get(v).toLocaleString()})`]),['not-recorded',`Not recorded (${(sexCounts.get('')||0).toLocaleString()})`]]);
 const number=placeholder=>{const n=el('input');n.type='number';n.min='1';n.max='9999';n.placeholder=placeholder;return n;};
 const controls={...(recorded.length?{sex}:{}),birth_from:number('e.g. 1750'),birth_to:number('e.g. 1850'),death_from:number('e.g. 1800'),death_to:number('e.g. 1900'),place:el('input')};
 controls.place.type='search';controls.place.placeholder='Parish, town or county';
 const body=el('div',undefined,'toolbar');if(controls.sex)body.append(field('Recorded sex',sex));
 body.append(field('Birth year from',controls.birth_from),field('Birth year to',controls.birth_to),field('Death year from',controls.death_from),field('Death year to',controls.death_to));
 const placeLabel=field('Event place',controls.place);placeLabel.className='grow';body.append(placeLabel);
 const family=el('fieldset');family.append(el('legend','Family links'));
 for(const [key,label] of [['no_parent','No parent recorded'],['has_children','Has recorded children'],['no_spouse','No recorded spouse or partner']]){const box=el('input'),l=el('label',undefined,'check');box.type='checkbox';box.value='1';l.append(box,label);family.append(l);controls[key]=box;}
 body.append(family);
 const panel=el('details',undefined,'catalogue-filters'),summary=el('summary','Research filters');panel.append(summary,body);
 const on=n=>n.type==='checkbox'?n.checked:n.value.trim()!=='';
 const active=()=>Object.values(controls).filter(on).length;
 const num=n=>n.value?Number(n.value):null,within=(y,lo,hi)=>lo===null&&hi===null||y!==null&&(lo===null||y>=lo)&&(hi===null||y<=hi);
 // Built once per render: the place words and year bounds, then a test for each record.
 const test=()=>{const words=norm(controls.place.value).trim().split(/\s+/).filter(Boolean),b=[num(controls.birth_from),num(controls.birth_to)],d=[num(controls.death_from),num(controls.death_to)],c=controls;const n=active(),s=controls.sex?.value||'';summary.textContent=n?`Research filters · ${n} on`:'Research filters';
  return r=>(!s||(s==='not-recorded'?!r.sex:r.sex===s))&&within(r.birth,...b)&&within(r.death,...d)&&(!words.length||r.places.some(p=>words.every(w=>p.includes(w))))&&(!c.no_parent.checked||!r.parent)&&(!c.has_children.checked||r.children)&&(!c.no_spouse.checked||!r.partner);};
 return {panel,controls,active,test};
}
function catalogue(){
 const host=$('[data-catalogue]');if(!host)return;
 let rows=$$('tbody tr',host);if(!rows.length)rows=$$('[data-person-id]',host);
 // A large site writes out the first page only; everyone else comes from the shared data.
 const compact=rows.length>0&&Number(host.dataset.total||0)>rows.length&&people.length>rows.length;
 if(!rows.length)return;
 if(compact)$('[data-catalogue-pages]')?.setAttribute('hidden','');
 const search=$('[data-search]')||el('input');search.type='search';search.placeholder='Name, place, relative or record…';search.setAttribute('aria-label','Search people');
 const bar=el('div',undefined,'toolbar');const oldLabel=search.closest('label');if(oldLabel&&oldLabel.childElementCount===1)oldLabel.remove();const queryLabel=field('Search the catalogue',search);queryLabel.className='grow';bar.append(queryLabel);
 const from=el('input');from.type='number';from.placeholder='e.g. 1750';from.min='1';from.max='9999';const to=el('input');to.type='number';to.placeholder='e.g. 1900';to.min='1';to.max='9999';
 // Offered only when some citation is recorded as an original record.
 const originals=[...citationBy.values()].some(c=>c.quality==='original');
 const evidence=select([['','Any evidence'],['supported','Supported claim'],...(originals?[['original','Backed by an original record']]:[]),['unassessed','Unassessed / imported']]);
 const tbody=rows[0].parentElement;let page=0;const size=40;
 const imported=new Set(list('imports').concat(list('import_provenance')).flatMap(i=>i.entity_ids||[]));
 const summary=p=>pe(p).sort(byDate).map(e=>`${e.kind}: ${e.date||'date unknown'}`).join('; ');
 const rowFor=p=>{const tr=el('tr'),first=el('td'),s=surnameOf(p),span=lifespan(p);tr.dataset.personId=p.id;tr.dataset.surname=canonical(s);first.append(linkTo(p.id,name(p)));if(span)first.append(el('br'),el('span',span,'meta'));tr.append(first,el('td',s||'—'),el('td',summary(p)||'No events recorded.'),el('td',p.id));return tr;};
 // A record filters and groups under its canonical surname; the row keeps the spelling as recorded.
 const record=(p,id,row,text)=>{const ev=p?pe(p):[];const related=p?relativeIds(p.id).map(id=>name(personBy.get(id))).join(' '):'';const cs=claimsByPerson.get(id)||[];const recorded=p?surnameOf(p):row?.dataset.surname||'';return{row,p,recorded,surname:canonical(row?row.dataset.surname||'':recorded),norm:fold([text,p?.notes,related,...ev.map(e=>[e.date,placeBy.get(e.place_id)?.name,e.description].join(' ')),...cs.map(c=>`${c.predicate} ${c.value}`)].join(' ')),years:ev.map(e=>year(e.date)).filter(n=>n!==null),supported:cs.some(c=>c.status==='supported'),original:cs.some(c=>c.status==='supported'&&(c.citation_ids||[]).some(id=>citationBy.get(id)?.quality==='original')),imported:imported.has(id)};};
 const records=compact?people.map(p=>{const r=record(p,p.id,null,[name(p),...(p.names||[]).map(n=>n.value),p.id,summary(p)].join(' '));Object.defineProperty(r,'row',{get(){return this._row||(this._row=rowFor(p));}});return r;})
  :rows.map((row,i)=>{const id=row.dataset.personId||row.dataset.id||people[i]?.id;return record(personBy.get(id),id,row,[row.dataset.searchText,row.textContent].join(' '));});
 // One option per canonical surname, naming the other spellings recorded under it.
 const surnameCounts=new Map,spellings=new Map;records.forEach(r=>{if(!r.surname)return;surnameCounts.set(r.surname,(surnameCounts.get(r.surname)||0)+1);if(r.recorded&&r.recorded!==r.surname){if(!spellings.has(r.surname))spellings.set(r.surname,new Set);spellings.get(r.surname).add(r.recorded);}});
 const surname=select([['','All surnames'],...[...surnameCounts].sort((a,b)=>a[0].localeCompare(b[0])).map(([s,n])=>{const other=[...(spellings.get(s)||[])].sort((a,b)=>a.localeCompare(b));return[s,other.length?`${s} (${n}, incl. ${other.join(', ')})`:`${s} (${n})`];})]);
 const sort=select([['name','Name · A–Z'],['name-desc','Name · Z–A'],['birth','Birth · earliest'],['death','Death · earliest']]);
 bar.append(field('Event year from',from),field('Event year to',to));if(surnameCounts.size)bar.append(field('Surname',surname));bar.append(field('Evidence',evidence),field('Sort by',sort));
 host.before(bar);const count=el('p',undefined,'result-count');count.setAttribute('role','status');host.before(count);
 const research=researchFilters(records);bar.after(research.panel);
 const pager=el('div',undefined,'pagination'),info=el('span'),buttons=el('div'),prev=el('button','← Previous'),next=el('button','Next →');buttons.append(prev,next);pager.append(info,buttons);host.after(pager);
 function render(){const q=fold(search.value).trim().split(/\s+/).filter(Boolean),lo=from.value?Number(from.value):null,hi=to.value?Number(to.value):null,matches=research.test();const filtered=records.filter(r=>q.every(v=>r.norm.includes(v))&&matches(r)&&(lo===null&&hi===null||r.years.some(y=>(lo===null||y>=lo)&&(hi===null||y<=hi)))&&(!surname.value||r.surname===surname.value)&&(!evidence.value||(evidence.value==='supported'?r.supported:evidence.value==='original'?r.original:!r.supported)));filtered.sort((a,b)=>{if(sort.value==='birth'||sort.value==='death'){const k=sort.value==='birth'?0:1;return(year(dates(a.p||{})[k])??Infinity)-(year(dates(b.p||{})[k])??Infinity)||name(a.p).localeCompare(name(b.p));}const n=name(a.p).localeCompare(name(b.p));return sort.value==='name-desc'?-n:n;});const pages=Math.max(1,Math.ceil(filtered.length/size));page=Math.min(page,pages-1);const current=filtered.slice(page*size,(page+1)*size);if(compact)tbody.replaceChildren(...current.map(r=>r.row));else{const shown=new Set(current);records.forEach(r=>r.row.hidden=!shown.has(r));const fragment=document.createDocumentFragment();filtered.forEach(r=>fragment.append(r.row));tbody.append(fragment);}count.textContent=`${filtered.length.toLocaleString()} of ${records.length.toLocaleString()} people · search includes recorded relatives and places`;info.textContent=`Page ${page+1} of ${pages}`;prev.disabled=page===0;next.disabled=page===pages-1;}
 // Every filter lives in the page address (?q=&surname=&sex=&birth_from=…), so a filtered view can be shared; other parameters are kept.
 const state=[['q',search],['surname',surname],...Object.entries(research.controls),['year_from',from],['year_to',to],['evidence',evidence],['sort',sort]];
 const value=n=>n.type==='checkbox'?(n.checked?'1':''):n.value,defaults=new Map(state.map(([,n])=>[n,value(n)]));
 const put=(n,v)=>{if(n.type==='checkbox')n.checked=v==='1';else if(n.tagName!=='SELECT'||[...n.options].some(o=>o.value===v))n.value=v;};
 const params=new URLSearchParams(location.search);for(const [key,n] of state){const v=params.get(key);if(v!==null)put(n,key==='surname'?canonical(v):v);}
 research.panel.open=research.active()>0;
 const clear=el('button','Clear search and filters');clear.type='button';bar.append(clear);
 const idle=()=>state.every(([key,n])=>key==='sort'||value(n).trim()===defaults.get(n));
 const keep=()=>{clear.hidden=idle();try{const u=new URL(location.href);state.forEach(([key])=>u.searchParams.delete(key));for(const [key,n] of state){const v=value(n);if(v.trim()!==''&&v!==defaults.get(n))u.searchParams.append(key,v);}if(u.href!==location.href)history.replaceState(history.state,'',u.href);}catch(_){/* file:// pages may refuse a new address; the filters still work */}};
 const changed=()=>{page=0;render();keep();};
 state.forEach(([,n])=>n.addEventListener(n.tagName==='INPUT'?'input':'change',changed));clear.addEventListener('click',()=>{state.forEach(([key,n])=>{if(key!=='sort')put(n,defaults.get(n));});changed();search.focus();});
 clear.hidden=idle();prev.addEventListener('click',()=>{page--;render();});next.addEventListener('click',()=>{page++;render();});render();
}

function tree(){
 const output=$('#tree-output'),root=$('#tree-root');if(!output||!root)return;
 fillPeople(root);
 const requested=new URLSearchParams(location.search).get('person');if(requested&&personBy.has(requested))root.value=requested;
 const controls=el('div',undefined,'tree-controls'),out=el('button','−'),inn=el('button','+'),reset=el('button','Fit tree'),help=el('span','Drag to pan · wheel or buttons to zoom','hint');out.setAttribute('aria-label','Zoom out');inn.setAttribute('aria-label','Zoom in');controls.append(out,inn,reset,help);output.before(controls);
 let tx=0,ty=0,scale=1,group,svg,initial,mode=new URLSearchParams(location.search).get('person')&&personBy.has(new URLSearchParams(location.search).get('person'))?'family':'whole',wholeController;
 const modes=el('div',undefined,'tree-modes');modes.setAttribute('role','group');modes.setAttribute('aria-label','Tree view');const modeButtons=new Map;for(const [value,label] of [['whole','Whole tree'],['family','Focus family'],['branches','Branch cards']]){const button=el('button',label);button.dataset.treeView=value;button.setAttribute('aria-pressed',String(mode===value));button.addEventListener('click',()=>{mode=value;modeButtons.forEach((b,v)=>b.setAttribute('aria-pressed',String(v===mode)));draw();});modes.append(button);modeButtons.set(value,button);}controls.before(modes);
 function transform(){group?.setAttribute('transform',`translate(${tx} ${ty}) scale(${scale})`);}
 function draw(){wholeController?.dispose();wholeController=null;output.replaceChildren();if(mode==='whole'){wholeController=wholeTree(output,root,()=>{mode='family';modeButtons.forEach((b,v)=>b.setAttribute('aria-pressed',String(v===mode)));draw();});return;}const id=root.value||people[0]?.id;if(!personBy.has(id)){output.append(empty('No public people available to draw.'));return;}
 const nodes=new Map([[id,{id,depth:0}]]),edges=[];let frontier=[id];for(let depth=0;depth<3;depth++){const next=[];for(const n of frontier){for(const r of relationships){const sibling=SIBLING_KINDS.includes(r.kind);if(r.confidence==='disproved'||!(sibling||['parent','father','mother','parent_child','child','biological_parent','adoptive_parent'].includes(r.kind)))continue;if(r.subject_id!==n&&r.object_id!==n)continue;const other=r.subject_id===n?r.object_id:r.subject_id;if(!personBy.has(other))continue;const d=nodes.get(n).depth+(sibling?0:r.subject_id===n?-1:1);if(!nodes.has(other)&&nodes.size<70){nodes.set(other,{id:other,depth:d});next.push(other);}if(nodes.has(other)&&!edges.some(e=>e.id===r.id))edges.push(r);}}frontier=next;}
 const columns=new Map;nodes.forEach(n=>{if(!columns.has(n.depth))columns.set(n.depth,[]);columns.get(n.depth).push(n);});let minD=Math.min(...columns.keys());columns.forEach((col,depth)=>col.forEach((n,i)=>{n.x=(depth-minD)*235+25;n.y=i*82+30;}));const width=(Math.max(...columns.keys())-minD+1)*235+25,height=Math.max(1,...[...columns.values()].map(c=>c.length))*82+30;
 const viewport=el('div',undefined,'tree-viewport');svg=svgEl('svg',{viewBox:`0 0 ${width} ${Math.max(height,270)}`,role:'img','aria-label':`Family connections around ${name(personBy.get(id))}`});group=svgEl('g');svg.append(group);edges.forEach(r=>{const a=nodes.get(r.subject_id),b=nodes.get(r.object_id);if(!a||!b)return;const side=a.x===b.x;group.append(svgEl('path',{d:side?`M${a.x+200},${a.y+27} C${a.x+228},${a.y+27} ${b.x+228},${b.y+27} ${b.x+200},${b.y+27}`:`M${a.x+100},${a.y+25} C${(a.x+b.x)/2+100},${a.y+25} ${(a.x+b.x)/2+100},${b.y+25} ${b.x+100},${b.y+25}`,class:`tree-edge ${SIBLING_KINDS.includes(r.kind)?'sibling':''} ${['documented','probable'].includes(r.confidence)?'':'uncertain'}`}));});nodes.forEach(n=>{const p=personBy.get(n.id),g=svgEl('g',{class:`tree-node ${n.id===id?'focus':''}`,transform:`translate(${n.x} ${n.y})`,tabindex:0,role:'button','aria-label':`Focus on ${name(p)}`});g.append(svgEl('rect',{width:200,height:55,rx:6}));const t=svgEl('text',{x:12,y:23});t.textContent=name(p).length>25?name(p).slice(0,24)+'…':name(p);const m=svgEl('text',{x:12,y:42,class:'node-meta'});m.textContent=dates(p).join(' – ');g.append(t,m);const focus=()=>{root.value=p.id;draw();};g.addEventListener('click',focus);g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();focus();}});group.append(g);});viewport.append(svg);output.append(viewport);const note=el('p',`Showing ${nodes.size} people within three connection steps. Dashed lines mark uncertain relationships. Recorded connections are not proof.`,'hint');output.append(note);
 const branches=el('div',undefined,'branch-grid');relativeIds(id).forEach(rid=>{const p=personBy.get(rid);if(!p)return;const r=relationships.find(r=>(r.subject_id===id&&r.object_id===rid)||(r.object_id===id&&r.subject_id===rid));const c=el('div',undefined,'card');c.append(personLink(p),el('p',`${relKind(r)} · ${relLabel(r)}`,'meta'));branches.append(c);});output.append(branches);if(mode==='branches'){viewport.hidden=true;note.textContent=`${branches.childElementCount} recorded relatives of ${name(personBy.get(id))}. Follow a dossier to inspect its sources and relationships.`;if(!branches.childElementCount)branches.append(empty('No public relatives are recorded for this person.'));}
 initial={tx:0,ty:0,scale:1};({tx,ty,scale}=initial);transform();let drag;svg.addEventListener('pointerdown',e=>{if(e.target.closest('.tree-node'))return;drag={x:e.clientX,y:e.clientY,tx,ty};svg.setPointerCapture(e.pointerId);});svg.addEventListener('pointermove',e=>{if(!drag)return;const rect=svg.getBoundingClientRect();tx=drag.tx+(e.clientX-drag.x)*width/rect.width;ty=drag.ty+(e.clientY-drag.y)*Math.max(height,270)/rect.height;transform();});svg.addEventListener('pointerup',()=>drag=null);svg.addEventListener('wheel',e=>{e.preventDefault();scale=Math.min(4,Math.max(.3,scale*(e.deltaY>0?.9:1.1)));transform();},{passive:false});
 }
 out.addEventListener('click',()=>{if(wholeController){wholeController.zoom(.8);return;}scale=Math.max(.3,scale/1.2);transform();});inn.addEventListener('click',()=>{if(wholeController){wholeController.zoom(1.25);return;}scale=Math.min(4,scale*1.2);transform();});reset.addEventListener('click',()=>{if(wholeController){wholeController.fit();return;}({tx,ty,scale}=initial);transform();});root.addEventListener('change',draw);draw();
}
function wholeTree(output,root,focusFamily){
 if(!people.length){output.append(empty('No public people available to draw.'));return {dispose(){},zoom(){},fit(){}};}
 const nodes=people.map(p=>({p,id:p.id,birth:year(dates(p)[0]),x:0,y:0})),byId=new Map(nodes.map(n=>[n.id,n])),parents=new Map(nodes.map(n=>[n.id,n.id]));
 const find=id=>{let r=id;while(parents.get(r)!==r)r=parents.get(r);while(parents.get(id)!==id){const next=parents.get(id);parents.set(id,r);id=next;}return r;};
 const edges=relationships.filter(r=>r.confidence!=='disproved'&&byId.has(r.subject_id)&&byId.has(r.object_id));for(const r of edges){const a=find(r.subject_id),b=find(r.object_id);if(a!==b)parents.set(b,a);}
 const components=new Map;for(const n of nodes){const id=find(n.id);if(!components.has(id))components.set(id,[]);components.get(id).push(n);}const ordered=[...components.values()].sort((a,b)=>b.length-a.length||a[0].id.localeCompare(b[0].id));
 const target=Math.max(300,Math.sqrt(nodes.length)*24);let shelfX=25,shelfY=25,shelfH=0,maxX=0,maxY=0;
 for(const component of ordered){component.sort((a,b)=>(a.birth??Infinity)-(b.birth??Infinity)||name(a.p).localeCompare(name(b.p))||a.id.localeCompare(b.id));const radius=Math.max(18,Math.sqrt(component.length)*11),size=radius*2+40;if(shelfX>25&&shelfX+size>target){shelfX=25;shelfY+=shelfH;shelfH=0;}component.forEach((n,i)=>{const angle=i*2.3999632297,r=10*Math.sqrt(i);n.x=shelfX+radius+20+Math.cos(angle)*r;n.y=shelfY+radius+20+Math.sin(angle)*r;});shelfX+=size;shelfH=Math.max(shelfH,size);maxX=Math.max(maxX,shelfX);maxY=Math.max(maxY,shelfY+size);}
 const viewport=el('div',undefined,'tree-viewport whole-tree-viewport'),canvas=el('canvas');canvas.dataset.wholeTree='';canvas.tabIndex=0;canvas.setAttribute('role','img');canvas.setAttribute('aria-label',`Whole public tree: ${nodes.length} people in ${components.size} recorded relationship groups. Use the person selector and Focus family for an accessible alternative.`);viewport.append(canvas);
 const detail=el('div',undefined,'whole-tree-detail'),legend=el('p',`${nodes.length.toLocaleString()} people · ${edges.length.toLocaleString()} recorded relationships · ${components.size.toLocaleString()} connected groups. Each group uses a spiral ordered by recorded birth year; position is not a generation or date scale. Gold dots have unknown birth dates. Dashed lines indicate uncertain relationships. Disproved relationships are omitted.`,'hint');
 const instructions=el('p','Drag to pan; zoom with the wheel or buttons. Select a dot to inspect a person. Keyboard: arrows pan, +/− zoom. The person selector, Focus family view and recorded lists below provide text alternatives.','hint');instructions.id='whole-tree-instructions';canvas.setAttribute('aria-describedby',instructions.id);output.append(viewport,detail,legend,instructions);
 const known=nodes.filter(n=>n.birth!==null).map(n=>n.birth);let cutoff=Infinity;
 if(known.length){const bar=el('div',undefined,'toolbar'),slider=el('input');slider.type='range';slider.min=String(Math.min(...known));slider.max=String(Math.max(...known));slider.value=slider.max;slider.dataset.treeBirthYear='';const value=el('span',`Through ${slider.max} · unknown birth dates included`,'hint');bar.append(field('Recorded birth year',slider),value);output.insertBefore(bar,viewport);slider.addEventListener('input',()=>{cutoff=Number(slider.value);value.textContent=`Through ${cutoff} · unknown birth dates included`;schedule();});}
 let selected=byId.get(root.value)||nodes[0],scale=1,tx=0,ty=0,width=0,height=0,frame=0,dead=false;
 const context=canvas.getContext('2d');if(!context){viewport.replaceChildren(empty('Canvas is unavailable. Use Focus family or the recorded lists below.'));return{dispose(){},zoom(){},fit(){}};}
 const visible=n=>n.birth===null||n.birth<=cutoff;
 function inspect(n){selected=n;root.value=n.id;detail.replaceChildren();const c=el('div',undefined,'connection-person');c.append(personLink(n.p),el('span',` · ${dates(n.p).join(' – ')}`,'meta'));const button=el('button','Focus this family');button.addEventListener('click',focusFamily);detail.append(c,button);schedule();}
 function paint(){frame=0;if(dead)return;const dpr=Math.min(window.devicePixelRatio||1,2);width=viewport.clientWidth||800;height=viewport.clientHeight||520;if(canvas.width!==Math.round(width*dpr)||canvas.height!==Math.round(height*dpr)){canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);}context.setTransform(dpr,0,0,dpr,0,0);context.clearRect(0,0,width,height);context.save();context.translate(tx,ty);context.scale(scale,scale);
 for(const uncertain of [false,true]){context.beginPath();context.strokeStyle=uncertain?'#a9b09c':'#7d9581';context.lineWidth=.7/Math.max(scale,.4);context.setLineDash(uncertain?[4/scale,3/scale]:[]);for(const r of edges){if((!['documented','probable'].includes(r.confidence))!==uncertain)continue;const a=byId.get(r.subject_id),b=byId.get(r.object_id);if(!visible(a)||!visible(b))continue;context.moveTo(a.x,a.y);context.lineTo(b.x,b.y);}context.stroke();}context.setLineDash([]);
 for(const n of nodes){if(!visible(n))continue;const x=n.x*scale+tx,y=n.y*scale+ty;if(x< -100||x>width+100||y< -25||y>height+25)continue;context.beginPath();context.fillStyle=n===selected?'#8e5e19':n.birth===null?'#af934f':'#234f3b';context.arc(n.x,n.y,(n===selected?5:3)/Math.max(.7,scale),0,Math.PI*2);context.fill();if(scale>2.2||n===selected){context.font=`${11/scale}px system-ui,sans-serif`;context.fillStyle='#233b32';context.fillText(name(n.p),n.x+7/scale,n.y-6/scale);}}
 context.restore();}
 function schedule(){if(!frame&&!dead)frame=requestAnimationFrame(paint);}
 function fit(){width=viewport.clientWidth||800;height=viewport.clientHeight||520;scale=Math.min((width-30)/maxX,(height-30)/maxY);tx=(width-maxX*scale)/2;ty=(height-maxY*scale)/2;schedule();}
 function zoom(factor,cx=width/2,cy=height/2){const next=Math.min(20,Math.max(.02,scale*factor)),ratio=next/scale;tx=cx-(cx-tx)*ratio;ty=cy-(cy-ty)*ratio;scale=next;schedule();}
 let drag;canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,tx,ty,moved:false};canvas.setPointerCapture(e.pointerId);});canvas.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>4)drag.moved=true;tx=drag.tx+dx;ty=drag.ty+dy;schedule();});canvas.addEventListener('pointerup',e=>{if(drag&&!drag.moved){const rect=canvas.getBoundingClientRect(),x=(e.clientX-rect.left-tx)/scale,y=(e.clientY-rect.top-ty)/scale;let nearest=null,distance=(12/scale)**2;for(const n of nodes){if(!visible(n))continue;const d=(n.x-x)**2+(n.y-y)**2;if(d<distance){nearest=n;distance=d;}}if(nearest)inspect(nearest);}drag=null;});canvas.addEventListener('pointercancel',()=>drag=null);canvas.addEventListener('wheel',e=>{e.preventDefault();const rect=canvas.getBoundingClientRect();zoom(e.deltaY>0?.88:1.14,e.clientX-rect.left,e.clientY-rect.top);},{passive:false});canvas.addEventListener('keydown',e=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-'].includes(e.key)){e.preventDefault();if(e.key==='ArrowLeft')tx+=35;if(e.key==='ArrowRight')tx-=35;if(e.key==='ArrowUp')ty+=35;if(e.key==='ArrowDown')ty-=35;if(e.key==='+'||e.key==='=')zoom(1.25);if(e.key==='-')zoom(.8);schedule();}});
 const observer=typeof ResizeObserver==='function'?new ResizeObserver(schedule):null;observer?.observe(viewport);inspect(selected);fit();return{zoom,fit,dispose(){dead=true;if(frame)cancelAnimationFrame(frame);observer?.disconnect();}};
}
function comparison(){
 const a=$('[data-compare-a]'),b=$('[data-compare-b]'),out=$('#compare-result');if(!a||!b||!out)return;fillPeople(a);fillPeople(b);preselect(a,b);
 function draw(){out.replaceChildren();const pa=personBy.get(a.value),pb=personBy.get(b.value);if(!pa||!pb){out.append(empty('Choose two people to compare the recorded details.'));return;}const grid=el('div',undefined,'comparison');for(const p of [pa,pb]){const card=el('section',undefined,'card');card.append(el('h2',name(p)));const dl=el('dl');const add=(k,v)=>dl.append(el('dt',k),el('dd',v));add('Birth',dates(p)[0]);add('Death',dates(p)[1]);add('Names',(p.names||[]).map(n=>n.value).join('; ')||'No name recorded');add('Places',[...new Set(pe(p).map(e=>placeBy.get(e.place_id)?.name).filter(Boolean))].join('; ')||'No place recorded');add('Relatives',relativeIds(p.id).map(id=>name(personBy.get(id))).join('; ')||'No public relationships recorded');const cs=claimsByPerson.get(p.id)||[];add('Claims',`${cs.length} recorded · ${cs.filter(c=>c.status==='supported').length} supported`);card.append(dl,personLink(p));grid.append(card);}out.append(grid,el('p','Similar details are research leads. Comparison does not establish identity or authorize a merge.','note'));}
 a.addEventListener('change',draw);b.addEventListener('change',draw);draw();
}
function connections(){
 const a=$('[data-connection-a]'),b=$('[data-connection-b]'),out=$('#connection-result');if(!a||!b||!out)return;fillPeople(a);fillPeople(b);preselect(a,b);
 const adjacency=new Map;for(const r of relationships){if(r.confidence==='disproved'||!personBy.has(r.subject_id)||!personBy.has(r.object_id))continue;for(const [x,y] of [[r.subject_id,r.object_id],[r.object_id,r.subject_id]]){if(!adjacency.has(x))adjacency.set(x,[]);adjacency.get(x).push({id:y,relation:r});}}
 function draw(){out.replaceChildren();if(!personBy.has(a.value)||!personBy.has(b.value)){out.append(empty('Choose two people to explore their recorded connections.'));return;}const queue=[a.value],seen=new Map([[a.value,null]]);let found=false;for(let i=0;i<queue.length;i++){const id=queue[i];if(id===b.value){found=true;break;}for(const n of adjacency.get(id)||[]){if(!seen.has(n.id)){seen.set(n.id,{previous:id,relation:n.relation});queue.push(n.id);}}}if(!found){out.append(empty('No connection found in the public records in this project. This does not establish that the people are unrelated.'));return;}const path=[];let id=b.value;while(id!==null){const step=seen.get(id);path.unshift({id,relation:step?.relation});id=step?.previous??null;}out.append(el('p',`${path.length-1} recorded connection${path.length===2?'':'s'} · shortest available path`,'result-count'));const row=el('div',undefined,'connection-path');path.forEach((n,i)=>{if(i)row.append(el('span',`→ ${relKind(n.relation)} (${relLabel(n.relation)}) →`,'connection-step'));const box=el('div',undefined,'connection-person');box.append(personLink(personBy.get(n.id)));row.append(box);});out.append(row,el('p','This path follows recorded relationships, including uncertain connections. It is not a proof of kinship.','note'));}
 a.addEventListener('change',draw);b.addEventListener('change',draw);draw();
}
function timeline(){
 const host=$('[data-timeline]');if(!host)return;const rows=$$('[data-event-id]',host);
 // A large site lists its decades here; the search covers every event in the shared data.
 const compact=!rows.length&&Number(host.dataset.total||0)>0&&events.length>0;if(!rows.length&&!compact)return;
 const search=el('input');search.type='search';search.placeholder='Person, date, event or place';const kinds=[...new Set(events.map(e=>e.kind))].sort();const kind=select([['','All event types'],...kinds.map(k=>[k,k])]);const bar=el('div',undefined,'toolbar');bar.append(field('Search timeline',search),field('Event type',kind));host.before(bar);const status=el('p',undefined,'result-count');host.before(status);
 if(compact){const index=[...host.children],results=el('ul',undefined,'record-list timeline'),LIMIT=100;results.hidden=true;host.append(results);status.setAttribute('role','status');
  const sorted=[...events].sort(byDate),texts=new Map;const text=e=>{if(!texts.has(e.id))texts.set(e.id,norm([e.date,e.kind,placeBy.get(e.place_id)?.name,e.description,...(e.participant_ids||[]).map(id=>name(personBy.get(id)))].join(' ')));return texts.get(e.id);};
  const item=e=>{const li=el('li'),who=el('p'),place=placeBy.get(e.place_id);li.append(el('strong',`${e.date||'Date unknown'} · ${e.kind}`));if(place)li.append(` — ${place.name}`);if(e.description)li.append(el('p',e.description));(e.participant_ids||[]).forEach((id,i)=>{if(i)who.append(', ');who.append(linkTo(id,name(personBy.get(id))));});li.append(who);return li;};
  const show=()=>{const words=norm(search.value).trim().split(/\s+/).filter(Boolean);if(!words.length&&!kind.value){results.hidden=true;index.forEach(n=>n.hidden=false);status.textContent=`${events.length.toLocaleString()} events, one page per decade. Search to find events across every decade.`;return;}
   const found=sorted.filter(e=>(!kind.value||e.kind===kind.value)&&words.every(w=>text(e).includes(w)));results.replaceChildren(...found.slice(0,LIMIT).map(item));results.hidden=false;index.forEach(n=>n.hidden=true);
   status.textContent=found.length>LIMIT?`The first ${LIMIT} of ${found.length.toLocaleString()} matching events, in date order. Refine the search to see the others.`:`${found.length.toLocaleString()} of ${events.length.toLocaleString()} events shown`;};
  search.addEventListener('input',show);kind.addEventListener('change',show);show();return;}
 const render=()=>{let count=0;rows.forEach(row=>{const event=eventBy.get(row.dataset.eventId),text=norm([row.textContent,...(event?.participant_ids||[]).map(id=>name(personBy.get(id)))].join(' '));row.hidden=!(text.includes(norm(search.value))&&(!kind.value||event?.kind===kind.value));if(!row.hidden)count++;});status.textContent=`${count} of ${rows.length} events shown`;};search.addEventListener('input',render);kind.addEventListener('change',render);render();
}
function sourceSearch(){
 const host=$('[data-sources]');if(!host)return;const rows=$$('[data-source-id]',host);if(!rows.length)return;const input=el('input');input.type='search';input.placeholder='Title, repository or source type';const bar=el('div',undefined,'toolbar');bar.append(field('Search sources',input));host.before(bar);const count=el('p',undefined,'result-count');host.before(count);
 // A large site writes out the first page only; the search covers every source in the shared data.
 const all=list('sources'),urls=Object.fromEntries(Object.entries(data.site?.source_urls||{}).map(([id,url])=>[id,window.GENEALOGY_SITE_DATA?root+url:url]));
 if(Number(host.dataset.total||0)>rows.length&&all.length>rows.length){const pages=$('[data-source-pages]'),results=el('ul',undefined,'record-list'),LIMIT=100;results.hidden=true;host.after(results);count.setAttribute('role','status');
  const text=new Map(all.map(s=>[s.id,norm([s.title,s.author,s.publication,s.source_type,s.repository].join(' '))]));const sorted=[...all].sort((a,b)=>String(a.title).localeCompare(String(b.title))||a.id.localeCompare(b.id));
  const item=s=>{const li=el('li'),a=el('a',s.title||s.id);if(urls[s.id])a.href=urls[s.id];li.append(a);const meta=[s.author,s.publication,s.source_type,s.repository].filter(Boolean).join(' · ');if(meta)li.append(el('p',meta,'meta'));return li;};
  const show=()=>{const words=norm(input.value).trim().split(/\s+/).filter(Boolean);const searching=words.length>0;host.hidden=searching;if(pages)pages.hidden=searching;results.hidden=!searching;if(!searching){count.textContent=`${all.length.toLocaleString()} sources, ${rows.length} on this page. Search to find any source.`;return;}
   const found=sorted.filter(s=>words.every(w=>text.get(s.id).includes(w)));results.replaceChildren(...found.slice(0,LIMIT).map(item));
   count.textContent=found.length>LIMIT?`The first ${LIMIT} of ${found.length.toLocaleString()} matching sources. Refine the search to see the others.`:`${found.length.toLocaleString()} of ${all.length.toLocaleString()} sources shown`;};
  input.addEventListener('input',show);show();return;}
 const draw=()=>{let shown=0;rows.forEach(r=>{r.hidden=!norm(r.textContent).includes(norm(input.value));if(!r.hidden)shown++;});$$('[data-source-type]',host).forEach(s=>{s.hidden=$$('[data-source-id]',s).every(r=>r.hidden);});count.textContent=`${shown} of ${rows.length} sources shown`;};input.addEventListener('input',draw);draw();
}
// Study statuses as the pages word them (labels.CLAIM_STATUS and RESEARCH_STATUS).
const STUDY_STATUS={asserted:'Asserted',supported:'Supported',disputed:'Disputed',rejected:'Rejected',open:'Open',draft:'Draft',closed:'Closed',resolved:'Resolved',final:'Final',abandoned:'Set aside',superseded:'Superseded',confirmed:'Confirmed',reviewed:'Reviewed',published:'Published','in progress':'In progress','in-progress':'In progress'};
function studySearch(){
 const host=$('[data-studies]');if(!host)return;const cards=$$('[data-study-id]',host);if(!cards.length)return;const input=el('input');input.type='search';input.placeholder='Title, summary or person';const bar=el('div',undefined,'toolbar');bar.append(field('Search studies',input));host.before(bar);const count=el('p',undefined,'result-count');host.before(count);
 // Titles, summaries and the names of the people each study links; never the study's body.
 const all=list('studies'),studyBy=new Map(all.map(s=>[s.id,s])),urls=Object.fromEntries(Object.entries(data.site?.study_urls||{}).map(([id,url])=>[id,window.GENEALOGY_SITE_DATA?root+url:url]));
 const linked=s=>(s?.related_ids||[]).filter(id=>personBy.has(id)).map(id=>name(personBy.get(id)));
 // A large site writes out the most recently updated studies only; the search covers every study in the shared data.
 if(Number(host.dataset.total||0)>cards.length&&all.length>cards.length){const pages=$('[data-study-pages]'),results=el('ul',undefined,'record-list'),LIMIT=100;results.hidden=true;host.after(results);count.setAttribute('role','status');
  const text=new Map(all.map(s=>[s.id,norm([s.title,s.summary,...linked(s)].join(' '))]));const sorted=[...all].sort((a,b)=>String(b.updated_on||'').localeCompare(String(a.updated_on||''))||String(b.title).localeCompare(String(a.title)));
  const item=s=>{const li=el('li'),a=el('a',s.title||s.id),meta=el('p');if(urls[s.id])a.href=urls[s.id];li.append(a);const badge=el('span',STUDY_STATUS[String(s.status||'').toLowerCase()]||s.status||'Draft','badge');badge.dataset.status=s.status||'';meta.append(badge);if(s.updated_on)meta.append(' ',el('span',`Updated ${s.updated_on}`,'meta'));li.append(meta);return li;};
  const show=()=>{const words=norm(input.value).trim().split(/\s+/).filter(Boolean);const searching=words.length>0;host.hidden=searching;if(pages)pages.hidden=searching;results.hidden=!searching;if(!searching){count.textContent=`${all.length.toLocaleString()} studies, the ${cards.length} most recently updated on this page. Search to find any study.`;return;}
   const found=sorted.filter(s=>words.every(w=>text.get(s.id).includes(w)));results.replaceChildren(...found.slice(0,LIMIT).map(item));
   count.textContent=found.length>LIMIT?`The first ${LIMIT} of ${found.length.toLocaleString()} matching studies, most recently updated first. Refine the search to see the others.`:`${found.length.toLocaleString()} of ${all.length.toLocaleString()} studies shown`;};
  input.addEventListener('input',show);show();return;}
 const texts=new Map(cards.map(c=>[c,norm([c.textContent,...linked(studyBy.get(c.dataset.studyId))].join(' '))]));
 const draw=()=>{const words=norm(input.value).trim().split(/\s+/).filter(Boolean);let shown=0;cards.forEach(c=>{c.hidden=!words.every(w=>texts.get(c).includes(w));if(!c.hidden)shown++;});count.textContent=`${shown} of ${cards.length} studies shown`;};input.addEventListener('input',draw);draw();
}
function map(){
 const host=$('#map-output');if(!host)return;
 const located=places.filter(p=>typeof p.latitude==='number'&&typeof p.longitude==='number'&&Number.isFinite(p.latitude)&&Number.isFinite(p.longitude)&&Math.abs(p.latitude)<=90&&Math.abs(p.longitude)<=180);
 if(!located.length)return;
 const panel=el('div',undefined,'map-panel'),svg=svgEl('svg',{viewBox:'0 0 900 470',role:'group',tabindex:0,'aria-label':'Interactive recorded places on a Natural Earth world overview','aria-describedby':'map-instructions'});const xy=(lon,lat)=>[(lon+180)*2.5,(90-lat)*2.5];
 for(let lon=-180;lon<=180;lon+=30){const [x]=xy(lon,0);svg.append(svgEl('path',{d:`M${x} 0V450`,class:'map-grid'}));}for(let lat=-60;lat<=60;lat+=30){const [,y]=xy(0,lat);svg.append(svgEl('path',{d:`M0 ${y}H900`,class:'map-grid'}));}
 // Bundled public-domain Natural Earth geometry; no external tiles or network service.
 svg.append(svgEl('image',{href:new URL('world.svg',scriptSource).href,x:0,y:0,width:900,height:450,'pointer-events':'none'}));
 const info=el('p','Select a marker to inspect its recorded place.','map-caption');info.setAttribute('aria-live','polite');const markers=[];
 const placeUrls=Object.fromEntries(Object.entries(data.site?.place_urls||{}).map(([id,url])=>[id,window.GENEALOGY_SITE_DATA?root+url:url]));
 // An event's people are its participants and anyone listing it among their own events; each counts under its canonical surname.
 const who=new Map;for(const [pid,evs] of eventsByPerson)for(const id of evs.keys()){if(!who.has(id))who.set(id,new Set);who.get(id).add(pid);}
 const atPlace=new Map(located.map(p=>[p.id,[]])),surnamePlaces=new Map,spellings=new Map;
 for(const e of events){const here=atPlace.get(e.place_id);if(!here)continue;const surnames=new Set;for(const pid of who.get(e.id)||[]){const s=surnameOf(personBy.get(pid)),c=canonical(s);if(!c)continue;surnames.add(c);if(!surnamePlaces.has(c)){surnamePlaces.set(c,new Set);spellings.set(c,new Set);}surnamePlaces.get(c).add(e.place_id);if(s!==c)spellings.get(c).add(s);}here.push({e,y:year(e.date),surnames});}
 let filtered=false,version=0,listed='';const list=el('ul',undefined,'map-cluster-places');list.hidden=true;
 located.forEach(p=>{const [cx,cy]=xy(p.longitude,p.latitude),group=svgEl('g',{class:'map-marker'}),hit=svgEl('circle',{cx,cy,r:12,fill:'transparent','pointer-events':'all'}),node=svgEl('circle',{cx,cy,r:5,class:`map-point${BROAD.has(p.precision)?' broad':''}`,tabindex:0,role:'button','aria-label':p.name});const title=svgEl('title');title.textContent=p.name;node.append(title);const m={p,group,node,hit,x:cx,y:cy,on:true,text:fold(p.name),all:atPlace.get(p.id),matched:atPlace.get(p.id)};const inspect=()=>{const n=m.matched.length,total=m.all.length;listed='';list.hidden=true;list.replaceChildren();info.textContent=`${p.name} · ${filtered&&n!==total?`${n} of ${total} recorded events match the filters`:`${total} recorded event${total===1?'':'s'}`} · ${p.latitude}, ${p.longitude}${p.precision?` · located to ${p.precision} level`:''}`;};group.addEventListener('click',inspect);node.addEventListener('focus',inspect);node.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();inspect();}});group.append(hit,node);svg.append(group);markers.push(m);});
 // Places closer than about 12 screen pixels merge into one counted marker, regrouped whenever the zoom or the filters change.
 const layer=svgEl('g',{class:'map-clusters'});svg.append(layer);let grouping='';
 function cluster(factor){const key=`${factor}|${version}`;if(key===grouping)return;grouping=key;const active=document.activeElement,inside=active!==svg&&svg.contains(active),reach=12*factor,cells=new Map,shown=markers.filter(m=>m.on),groups=[];
  for(const m of shown){const k=`${Math.floor(m.x/reach)},${Math.floor(m.y/reach)}`;if(!cells.has(k))cells.set(k,[]);cells.get(k).push(m);m.taken=false;}
  for(const m of shown){if(m.taken)continue;const g=[],gx=Math.floor(m.x/reach),gy=Math.floor(m.y/reach);for(let i=-1;i<=1;i++)for(let j=-1;j<=1;j++)for(const o of cells.get(`${gx+i},${gy+j}`)||[])if(!o.taken&&Math.hypot(o.x-m.x,o.y-m.y)<reach){o.taken=true;g.push(o);}groups.push(g);}
  // Markers that would still overlap on screen merge too, so no badge hides another.
  let gs=groups.map(g=>({g,x:g.reduce((s,m)=>s+m.x,0)/g.length,y:g.reduce((s,m)=>s+m.y,0)/g.length}));
  for(let pass=0;pass<8;pass++){const span=30*factor,grid=new Map;let changed=false;gs.forEach(a=>{const k=`${Math.floor(a.x/span)},${Math.floor(a.y/span)}`;if(!grid.has(k))grid.set(k,[]);grid.get(k).push(a);});
   for(const a of gs){if(a.dead)continue;const ax=Math.floor(a.x/span),ay=Math.floor(a.y/span);for(let i=-1;i<=1;i++)for(let j=-1;j<=1;j++)for(const b of grid.get(`${ax+i},${ay+j}`)||[])if(b!==a&&!b.dead&&Math.hypot(a.x-b.x,a.y-b.y)<(markerRadius(a.g)+markerRadius(b.g))*factor){a.x=(a.x*a.g.length+b.x*b.g.length)/(a.g.length+b.g.length);a.y=(a.y*a.g.length+b.y*b.g.length)/(a.g.length+b.g.length);a.g.push(...b.g);b.dead=true;changed=true;}}
   gs=gs.filter(a=>!a.dead);if(!changed)break;}
  markers.forEach(m=>{m.group.style.display=m.on?'':'none';});
  const merged=gs.filter(a=>a.g.length>1);layer.replaceChildren(...merged.map(a=>{a.g.forEach(m=>{m.group.style.display='none';});return clusterMarker(a,factor);}));
  // The place list describes one cluster; once that cluster has split or changed it is withdrawn.
  if(listed&&!merged.some(a=>JSON.stringify(a.g.map(m=>m.p.id).sort())===listed)){listed='';list.hidden=true;list.replaceChildren();info.textContent='Select a marker to inspect its recorded place.';}
  // A marker that merges or is filtered away while focused hands focus back to the map.
  if(inside&&(!active.isConnected||active.closest('.map-marker')?.style.display==='none'))svg.focus();}
 // Screen radius in pixels: a place's own marker, or a cluster's badge growing slowly with its count.
 const markerRadius=g=>g.length>1?9+Math.min(6,Math.log2(g.length)*1.5):g[0].node.classList.contains('broad')?10:5;
 function clusterMarker({g,x:cx,y:cy},factor){const sorted=[...g].sort((a,b)=>a.p.name.localeCompare(b.p.name)||a.p.id.localeCompare(b.p.id)),LIMIT=50;
  const label=`${g.length} places: ${sorted.slice(0,5).map(m=>m.p.name).join('; ')}${g.length>5?` and ${g.length-5} more`:''}`;
  const group=svgEl('g',{class:'map-marker map-cluster'}),hit=svgEl('circle',{cx,cy,r:16*factor,fill:'transparent','pointer-events':'all'}),node=svgEl('circle',{cx,cy,r:markerRadius(g)*factor,class:'map-cluster-point',tabindex:0,role:'button','aria-label':label,'stroke-width':1.5*factor}),badge=svgEl('text',{x:cx,y:cy,class:'map-cluster-count','font-size':10*factor,'aria-hidden':'true'}),title=svgEl('title');title.textContent=label;node.append(title);badge.textContent=String(g.length);
  const inspect=()=>{const n=g.reduce((s,m)=>s+m.matched.length,0);info.textContent=`${g.length} places close together at this zoom · ${n} ${filtered?'matching ':''}event${n===1?'':'s'}. Zoom in to separate them${g.length>LIMIT?`; the first ${LIMIT} by name are listed`:''}.`;
   list.replaceChildren(...sorted.slice(0,LIMIT).map(m=>{const li=el('li'),url=placeUrls[m.p.id];if(url){const a=el('a',m.p.name);a.href=url;li.append(a);}else li.append(m.p.name);li.append(` · ${m.matched.length} event${m.matched.length===1?'':'s'}`);return li;}));list.hidden=false;listed=JSON.stringify(g.map(m=>m.p.id).sort());};
  group.addEventListener('click',inspect);node.addEventListener('focus',inspect);node.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();inspect();}});group.append(hit,node,badge);return group;}
 // Filters: a place stays on the map while one of its events falls in the year range, is of the chosen type and names someone of the chosen surname.
 const search=el('input'),from=el('input'),to=el('input');search.type='search';search.placeholder='Place name';for(const [n,hint] of [[from,'e.g. 1750'],[to,'e.g. 1900']]){n.type='number';n.min='1';n.max='9999';n.placeholder=hint;}
 const kinds=[...new Set([...atPlace.values()].flat().map(r=>r.e.kind).filter(Boolean))].sort(),kind=select([['','All event types'],...kinds.map(k=>[k,k])]);
 const surname=select([['','All surnames'],...[...surnamePlaces].sort((a,b)=>a[0].localeCompare(b[0])).map(([s,at])=>{const other=[...spellings.get(s)].sort((a,b)=>a.localeCompare(b));return[s,`${s} (${at.size} place${at.size===1?'':'s'}${other.length?`, incl. ${other.join(', ')}`:''})`];})]);
 const bar=el('div',undefined,'toolbar map-filters'),status=el('p',undefined,'result-count'),query=field('Search places',search);status.setAttribute('role','status');query.className='grow';bar.append(query,field('Event year from',from),field('Event year to',to));if(kinds.length)bar.append(field('Event type',kind));if(surnamePlaces.size)bar.append(field('Surname',surname));
 const num=v=>v===''||!Number.isFinite(Number(v))?null:Number(v);
 function apply(){const words=fold(search.value).trim().split(/\s+/).filter(Boolean),lo=num(from.value),hi=num(to.value),k=kind.value,s=surname.value;filtered=lo!==null||hi!==null||!!k||!!s;let shown=0,count=0;
  for(const m of markers){m.matched=filtered?m.all.filter(r=>(lo===null||r.y!==null&&r.y>=lo)&&(hi===null||r.y!==null&&r.y<=hi)&&(!k||r.e.kind===k)&&(!s||r.surnames.has(s))):m.all;m.on=words.every(w=>m.text.includes(w))&&(!filtered||m.matched.length>0);if(m.on){shown++;count+=m.matched.length;}}
  status.textContent=`${shown.toLocaleString()} of ${markers.length.toLocaleString()} places shown · ${count.toLocaleString()} event${count===1?'':'s'}`;version++;render();}
 [search,from,to].forEach(n=>n.addEventListener('input',apply));[kind,surname].forEach(n=>n.addEventListener('change',apply));
 let box={x:0,y:0,w:900,h:470};
 function render(){svg.setAttribute('viewBox',`${box.x} ${box.y} ${box.w} ${box.h}`);const factor=box.w/(svg.clientWidth||900);markers.forEach(({node,hit})=>{node.setAttribute('r',(node.classList.contains('broad')?10:5)*factor);node.style.strokeWidth=String(1.5*factor);hit.setAttribute('r',12*factor);});cluster(factor);}
 const point=e=>{const p=svg.createSVGPoint();p.x=e.clientX;p.y=e.clientY;const matrix=svg.getScreenCTM();return matrix?p.matrixTransform(matrix.inverse()):{x:box.x+box.w/2,y:box.y+box.h/2};};
 function zoom(factor,center={x:box.x+box.w/2,y:box.y+box.h/2}){const w=Math.min(1800,Math.max(12.5,box.w*factor)),ratio=w/box.w;box={x:center.x-(center.x-box.x)*ratio,y:center.y-(center.y-box.y)*ratio,w,h:box.h*ratio};render();}
 const controls=el('div',undefined,'tree-controls map-controls'),minus=el('button','−'),plus=el('button','+'),fit=el('button','Fit places'),world=el('button','World');minus.setAttribute('aria-label','Zoom map out');plus.setAttribute('aria-label','Zoom map in');fit.dataset.mapFit='';world.dataset.mapWorld='';controls.append(minus,plus,fit,world);minus.addEventListener('click',()=>zoom(1.3));plus.addEventListener('click',()=>zoom(1/1.3));world.addEventListener('click',()=>{box={x:0,y:0,w:900,h:470};render();});fit.addEventListener('click',()=>{const on=markers.filter(m=>m.on),positions=(on.length?on:markers).map(m=>[m.x,m.y]),xs=positions.map(p=>p[0]),ys=positions.map(p=>p[1]),minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys),w=Math.min(900,Math.max(35,(maxX-minX)*1.3,(maxY-minY)*1.3*900/470));box={x:(minX+maxX-w)/2,y:(minY+maxY-w*470/900)/2,w,h:w*470/900};render();});
 let drag;svg.addEventListener('pointerdown',e=>{if(e.target.closest('.map-marker'))return;const p=point(e);drag={p};svg.setPointerCapture(e.pointerId);});svg.addEventListener('pointermove',e=>{if(!drag)return;const p=point(e);box.x+=drag.p.x-p.x;box.y+=drag.p.y-p.y;render();});svg.addEventListener('pointerup',()=>drag=null);svg.addEventListener('pointercancel',()=>drag=null);svg.addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY>0?1.15:1/1.15,point(e));},{passive:false});svg.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-','Home'].includes(e.key))return;e.preventDefault();if(e.key==='ArrowLeft')box.x-=box.w*.08;if(e.key==='ArrowRight')box.x+=box.w*.08;if(e.key==='ArrowUp')box.y-=box.h*.08;if(e.key==='ArrowDown')box.y+=box.h*.08;if(e.key==='+'||e.key==='=')zoom(1/1.3);if(e.key==='-')zoom(1.3);if(e.key==='Home')box={x:0,y:0,w:900,h:470};render();});
 const instructions=el('p','Drag to pan; use the wheel or +/− to zoom. Keyboard: arrows pan, +/− zoom, Home returns to the world. Markers keep their screen size; places closer together than a marker merge into one counted marker until you zoom in. The filters keep a place while one of its events matches; Fit places frames the places shown, keeping a minimum regional span. Coordinates are the supplied values.','hint');instructions.id='map-instructions';panel.append(svg,info,list);host.replaceChildren(bar,status,controls,panel,instructions,el('p',`${located.length} of ${places.length} places have supplied coordinates. Natural Earth overview; no geocoding or online map services. Places without coordinates remain in the list below.`,'hint'));apply();if(typeof ResizeObserver==='function')new ResizeObserver(render).observe(svg);
}
function overview(){
 if(view!=='overview')return;const main=$('#main-content')||$('main');if(!main)return;
 const panel=el('section',undefined,'overview-explore');panel.append(el('p','PEOPLE · PLACES · PROOF','eyebrow'),el('h2','Follow the threads of a family history'));
 const grid=el('div',undefined,'card-grid');for(const [title,description,href] of [['People & their stories','Search names, recorded places, dates and relatives.','catalogue.html'],['Connections across generations','Trace recorded family lines and their confidence.','tree.html'],['A history in time & place','Explore life events and supplied map coordinates.','timeline.html'],['The evidence behind the story','Keep original sources, citations and assessments in view.','sources.html']]){const card=el('article',undefined,'card');const a=el('a',title);a.href=href;const heading=el('h3');heading.append(a);card.append(heading,el('p',description,'meta'));grid.append(card);}panel.append(grid);
 const rel=relationships.find(r=>r.confidence!=='disproved'&&personBy.has(r.subject_id)&&personBy.has(r.object_id));if(rel){const preview=el('div',undefined,'overview-tree-preview');preview.append(el('p','A CONNECTION IN THE COLLECTION','eyebrow'));const path=el('div',undefined,'connection-path');for(const [i,id] of [rel.object_id,rel.subject_id].entries()){if(i)path.append(el('span',`→ ${relKind(rel)} · ${relLabel(rel)} →`,'connection-step'));const c=el('div',undefined,'connection-person');c.append(personLink(personBy.get(id)),el('div',dates(personBy.get(id)).join(' – '),'meta'));path.append(c);}preview.append(path);const a=el('a','Explore the family tree →');a.href='tree.html';preview.append(a);panel.append(preview);}
 const stats=$('.stats',main);if(stats)stats.after(panel);else main.append(panel);
}
function bookmarks(){
 if(view!=='person')return;const id=document.body.dataset.personId;if(!id)return;try{const key='genealogy-workbench-bookmarks',saved=new Set(JSON.parse(localStorage.getItem(key)||'[]'));const button=el('button');const render=()=>{button.textContent=saved.has(id)?'★ Saved on this device':'☆ Save on this device';button.setAttribute('aria-pressed',String(saved.has(id)));};render();button.addEventListener('click',()=>{saved.has(id)?saved.delete(id):saved.add(id);try{localStorage.setItem(key,JSON.stringify([...saved]));render();announce('Saved people updated on this device.');}catch(_){announce('Browser storage is unavailable.');}});($('.page-header')||$('main'))?.append(button);}catch(_){} }
// Site search in the sidebar: people, places, studies, sources, findings and questions by title.
// The index (a title and one short line per record) loads on first use as a script, which works from file:// as well.
const SEARCH_KINDS={person:'People',place:'Places',study:'Studies',source:'Sources',finding:'Findings',question:'Research questions'};
function siteSearch(){
 const form=$('form.site-search');if(!form)return;const input=$('input[name=q]',form),results=$('.site-search-results',form),count=$('.site-search-count',form);if(!input||!results||!count)return;
 const LIMIT=12;let index=null,loading=false;
 const hint=el('span','Use the down arrow to reach the results and Escape to close them.','sr-only');hint.id='site-search-hint';form.append(hint);input.setAttribute('aria-describedby',hint.id);input.setAttribute('aria-controls',results.id);
 const words=v=>v.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
 function load(){if(index||loading)return;loading=true;
  const ready=()=>{const raw=window.GENEALOGY_SEARCH_INDEX;index=(Array.isArray(raw)?raw:[]).filter(e=>e&&e.t&&e.u).map(e=>{const n=norm(e.t);return{...e,n,w:words(n),h:norm([e.t,e.s].join(' '))};});show();};
  if(window.GENEALOGY_SEARCH_INDEX){ready();return;}
  const script=document.createElement('script');script.src=root+'data/search-index.js';script.async=true;script.addEventListener('load',ready);
  script.addEventListener('error',()=>{loading=false;script.remove();count.textContent='The site search could not be loaded.';});document.head.append(script);if(input.value.trim())count.textContent='Loading the search…';}
 // Title starting with the query, then every word starting a title word, then within the title, then within its line.
 const rank=(e,q,terms)=>!terms.every(t=>e.h.includes(t))?-1:e.n.startsWith(q)?0:terms.every(t=>e.w.some(w=>w.startsWith(t)))?1:terms.every(t=>e.n.includes(t))?2:3;
 const close=()=>{results.hidden=true;results.replaceChildren();count.textContent='';};
 const links=()=>$$('a',results);
 function line(e){
  // A place's name ends with its jurisdictions: the first part is shown as the title, the rest beneath it.
  if(e.k==='place'){const parts=String(e.t).split(',').map(x=>x.trim()).filter(Boolean);return[parts[0]||e.t,parts.slice(1).join(', ')];}
  const dated=/^\d{4}(-\d\d){0,2}$/.test(e.s||'');return[e.t,e.k==='study'&&dated?`Updated ${e.s}`:e.k==='finding'&&dated?`Recorded ${e.s}`:e.s||''];}
 function show(){
  const typed=input.value.trim(),q=norm(typed).replace(/\s+/g,' '),terms=words(q);
  if(!terms.length){close();return;}
  if(!index){load();return;}
  const found=[];for(const e of index){const r=rank(e,q,terms);if(r>=0)found.push([r,e]);}
  found.sort((a,b)=>a[0]-b[0]||a[1].n.localeCompare(b[1].n));
  // The best matches, grouped by kind in the order their best match appears.
  const groups=new Map;for(const [,e] of found.slice(0,LIMIT)){if(!groups.has(e.k))groups.set(e.k,[]);groups.get(e.k).push(e);}
  const nodes=[];for(const [kind,rows] of groups){const group=el('li',undefined,'site-search-group'),label=el('p',SEARCH_KINDS[kind]||kind,'site-search-kind'),list=el('ul');label.id=`site-search-kind-${kind}`;list.setAttribute('aria-labelledby',label.id);
   for(const e of rows){const item=el('li'),a=el('a'),[title,sub]=line(e);a.href=root+e.u;a.append(el('span',title,'site-search-title'));if(sub)a.append(el('span',sub,'site-search-line'));item.append(a);list.append(item);}
   group.append(label,list);nodes.push(group);}
  const more=el('li',undefined,'site-search-more'),all=el('a',`Search the people catalogue for “${typed}”`);all.href=`${root}catalogue.html?q=${encodeURIComponent(typed)}`;more.append(all);nodes.push(more);
  results.replaceChildren(...nodes);results.hidden=false;
  count.textContent=!found.length?'No titles match. Press Enter to search the people catalogue.':found.length>LIMIT?`The best ${LIMIT} of ${found.length.toLocaleString()} matches`:`${found.length} match${found.length===1?'':'es'}`;}
 input.addEventListener('focus',()=>{load();if(results.hidden&&input.value.trim())show();});
 input.addEventListener('input',show);
 input.addEventListener('keydown',e=>{
  if(e.key==='ArrowDown'&&!results.hidden){const first=links()[0];if(first){e.preventDefault();first.focus();}}
  else if(e.key==='Escape'){if(!results.hidden){e.preventDefault();close();}else if(input.value){e.preventDefault();input.value='';}}
  // Enter opens the best match; with none (or before the index loads) the form searches the catalogue.
  else if(e.key==='Enter'&&!results.hidden){const first=$('.site-search-group a',results);if(first){e.preventDefault();location.href=first.href;}}});
 results.addEventListener('keydown',e=>{const all=links(),at=all.indexOf(document.activeElement);if(at<0)return;
  if(e.key==='ArrowDown'){e.preventDefault();all[Math.min(at+1,all.length-1)].focus();}
  else if(e.key==='ArrowUp'){e.preventDefault();(at?all[at-1]:input).focus();}
  else if(e.key==='Home'||e.key==='End'){e.preventDefault();all[e.key==='Home'?0:all.length-1].focus();}
  else if(e.key==='Escape'){e.preventDefault();close();input.focus();}});
 // Closes when focus or a click goes elsewhere; a click on a result is inside the form.
 form.addEventListener('focusout',e=>{if(e.relatedTarget&&!form.contains(e.relatedTarget))close();});
 document.addEventListener('pointerdown',e=>{if(!form.contains(e.target))close();});
}
const tasks=[overview,catalogue,tree,comparison,connections,timeline,sourceSearch,studySearch,map,bookmarks];for(const task of tasks){try{task();}catch(error){console.warn('Optional genealogy enhancement unavailable:',task.name,error);}}
try{siteSearch();}catch(error){console.warn('Optional genealogy enhancement unavailable: siteSearch',error);}
})();
