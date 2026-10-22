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
// Readable dates, worded as dates.display_date words them in the pages: "24 May 1731",
// "1754" for a year-precision date, "c. 1754", "before 1800"; free text as recorded.
const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'],MON3=MON.map(m=>m.toUpperCase());
const MONTH_WORDS={JANUARY:'JAN',FEBRUARY:'FEB',MARCH:'MAR',APRIL:'APR',JUNE:'JUN',JULY:'JUL',AUGUST:'AUG',SEPT:'SEP',SEPTEMBER:'SEP',OCTOBER:'OCT',NOVEMBER:'NOV',DECEMBER:'DEC'};
const QWORD={ABOUT:'c.',ABT:'c.',CIRCA:'c.',CA:'c.',C:'c.',EST:'c.',ESTIMATED:'c.',CAL:'c.',CALCULATED:'c.',BEF:'before',BEFORE:'before',AFT:'after',AFTER:'after',FROM:'from',TO:'to',INT:''};
const QNOTE={EST:'estimated',ESTIMATED:'estimated',CAL:'calculated',CALCULATED:'calculated'},APPROX=['approximate','about','circa','estimated'];
const monthDays=(y,m)=>m?new Date(Date.UTC(y,m,0)).getUTCDate():31;
const dateParts=t=>{t=t.trim();let m=/^([1-9]\d{2,3})(?:-(\d{2})(?:-(\d{2}))?)?$/.exec(t);
 if(m){const y=+m[1],mo=+(m[2]||0),d=mo?+(m[3]||0):0;return mo<=12&&d<=monthDays(y,mo)?[y,mo,d,'']:null;}
 t=t.replace(/\b(\d{1,2})(?:ST|ND|RD|TH)\b/g,'$1');for(const [w,s] of Object.entries(MONTH_WORDS))t=t.replace(new RegExp(`\\b${w}\\b`,'g'),s);
 const Y='([1-9]\\d{2,3})(/\\d{1,4})?';
 m=new RegExp(`^(?:(\\d{1,2})\\s+)?([A-Z]{3})\\s+${Y}$`).exec(t);if(m&&MON3.includes(m[2])&&+(m[1]||0)<=monthDays(+m[3],MON3.indexOf(m[2])+1))return [+m[3],MON3.indexOf(m[2])+1,+(m[1]||0),m[4]||''];
 m=new RegExp(`^([A-Z]{3})\\s+(\\d{1,2})\\s+${Y}$`).exec(t);if(m&&MON3.includes(m[1])&&+m[2]<=monthDays(+m[3],MON3.indexOf(m[1])+1))return [+m[3],MON3.indexOf(m[1])+1,+m[2],m[4]||''];
 m=new RegExp(`^${Y}$`).exec(t);return m?[+m[1],0,0,m[2]||'']:null;};
const dateWords=([y,mo,d,dual],pr)=>{if(pr==='decade')return `${Math.floor(y/10)*10}s`;if(pr==='year')mo=0;if(pr==='year'||pr==='month')d=0;return [d&&mo?String(d):'',mo?MON[mo-1]:'',`${y}${dual}`].filter(Boolean).join(' ');};
const showDate=(value,precision)=>{const original=String(value??'').trim().split(/\s+/).join(' ');if(!original)return '';const pr=String(precision||'').trim().toLowerCase(),notes=[];let t=original.toUpperCase().replace(/,/g,' ');
 const cal=/^@#D([A-Z ]+?)\s*@\s*/.exec(t);if(cal){t=t.slice(cal[0].length);if(cal[1].trim()!=='GREGORIAN')notes.push(cal[1].trim().toLowerCase().replace(/\b\w/g,c=>c.toUpperCase()));}
 const phrase=/\s*\((.*)\)\s*$/.exec(original);if(phrase){t=t.slice(0,t.lastIndexOf('('));notes.push(phrase[1].trim());}
 t=t.split(/\s+/).filter(Boolean).join(' ');let approx=APPROX.includes(pr),words;if(pr==='estimated')notes.push('estimated');
 const b=/^(?:BET|BETWEEN)\s+(.+?)\s+AND\s+(.+)$/.exec(t)||/^FROM\s+(.+?)\s+TO\s+(.+)$/.exec(t);
 if(b){const ends=[dateParts(b[1]),dateParts(b[2])];if(!ends[0]||!ends[1])return original;const bet=t.startsWith('BET');words=`${bet?'between':'from'} ${dateWords(ends[0],pr)} ${bet?'and':'to'} ${dateWords(ends[1],pr)}`;}
 else{const q=/^(ABOUT|ABT|CIRCA|CA|C|ESTIMATED|EST|CALCULATED|CAL|BEFORE|BEF|AFTER|AFT|FROM|TO|INT)(?:\.\s*|\s+|(?=\d))/.exec(t);const parts=dateParts(q?t.slice(q[0].length):t);if(!parts)return original;words=dateWords(parts,pr);
  if(q){if(QWORD[q[1]])words=`${QWORD[q[1]]} ${words}`;if(QNOTE[q[1]])notes.unshift(QNOTE[q[1]]);approx=false;}if(approx)words=`c. ${words}`;}
 for(const n of new Set(notes))words+=` (${n})`;return words;};
const eventDate=(e,missing='Date unknown')=>showDate(e?.date,e?.date_precision)||missing;
// Birth and death as a reader writes them; dates() keeps the recorded values for sorting.
const shownDates=p=>{const e=pe(p);return ['birth','death'].map(k=>{const x=e.find(x=>x.kind===k);return x?.date?eventDate(x):'Unknown';});};
// One rule for every printed count: "1 study", "2 studies", "1 person".
const PLURALS={person:'people',study:'studies',family:'families',search:'searches',match:'matches',child:'children'};
const plural=(n,word)=>`${Number(n).toLocaleString()} ${n===1?word:PLURALS[word]||word+'s'}`;
// A family link read the right way round from one side: "is the daughter of", "is the spouse of".
const ROLE={child:{M:'son',F:'daughter'},parent:{M:'father',F:'mother'}},PED={adopted:'adopted ',adoptive:'adoptive ',foster:'foster ',step:'step-'};
const relPhrase=(r,id)=>{const k=String(r?.kind||'').toLowerCase(),sex=String(personBy.get(id)?.sex||'').toUpperCase();
 if(PARENT_KINDS.includes(k)){const side=r.subject_id===id?'child':'parent',ped=r.pedigree&&r.pedigree!=='birth'?(side==='parent'&&r.pedigree==='adopted'?'adoptive ':PED[r.pedigree]||`${r.pedigree} `):'';
  const role=side==='parent'&&(k==='father'||k==='mother')?k:ROLE[side][sex]||side;return `is the ${ped}${role} of`;}
 if(PARTNER_KINDS.includes(k))return k==='partner'?'is the partner of':'is the spouse of';
 if(SIBLING_KINDS.includes(k))return k.includes('half')||String(r.pedigree||'').includes('half')?'is a half-sibling of':'is a sibling of';
 return r.subject_id===id?`— ${relKind(r)} →`:`← ${relKind(r)} —`;};
const pillList=items=>{const ul=el('ul',undefined,'pills');for(const item of items){const li=el('li');li.append(item);ul.append(li);}return ul;};
const relativeIds=id=>[...new Set((relationsByPerson.get(id)||[]).map(r=>r.subject_id===id?r.object_id:r.subject_id))];
const personLink=p=>{const a=el('a',name(p));if(links[p.id])a.setAttribute('href',links[p.id]);return a;};
const announce=t=>{const s=$('#site-status');if(s)s.textContent=t;};
const empty=t=>el('p',t,'empty-state');
const field=(label,control)=>{const l=el('label',label);l.append(control);return l;};
const option=(value,text)=>{const n=el('option',text);n.value=value;return n;};
const select=(items)=>{const n=el('select');items.forEach(([v,t])=>n.append(option(v,t)));return n;};
const menu=$('#menu-toggle');if(menu)menu.addEventListener('click',()=>{const open=menu.getAttribute('aria-expanded')!=='true';menu.setAttribute('aria-expanded',String(open));$('#site-sidebar')?.classList.toggle('menu-open',open);});
const view=document.body.dataset.view;

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
// Type-to-find over a person menu (combobox and listbox). The menu stays the real control: a choice sets it and fires change.
// Past 300 people (site.py's INLINE_LIMIT) a full menu is a long scroll, so it folds away under a details.
let pickerCount=0;
const VALUE=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value');
function picker(menu,label){
 if(!menu||'picker' in menu.dataset||!people.length)return;menu.dataset.picker='';fillPeople(menu);
 const n=++pickerCount,large=people.length>300,focused=document.activeElement===menu,holder=menu.closest('label')||menu;
 const box=el('div',undefined,'person-picker'),wrap=el('div',undefined,'picker-field'),input=el('input'),list=el('ul',undefined,'picker-list'),status=el('p',undefined,'picker-status');
 input.type='search';input.id=`picker-${n}`;list.id=`picker-${n}-list`;list.hidden=true;list.setAttribute('role','listbox');list.setAttribute('aria-label',`Matches for ${label.toLowerCase()}`);status.setAttribute('role','status');
 for(const [k,v] of [['role','combobox'],['aria-autocomplete','list'],['aria-expanded','false'],['aria-controls',list.id],['autocomplete','off'],['spellcheck','false'],['placeholder','Type a name or ID']])input.setAttribute(k,v);
 holder.before(box);wrap.append(field(label,input),list);box.append(wrap,status);
 if(large){const more=el('details',undefined,'picker-menu');more.append(el('summary','or choose from the list'),holder);box.append(more);}else box.append(holder);
 if(focused)(large?input:menu).focus();
 // Names, the ID and each name's canonical surname, folded, so any listed spelling finds the person.
 let index,matches=[],active=-1;
 const entries=()=>index||(index=[...people].sort((x,y)=>name(x).localeCompare(name(y))||x.id.localeCompare(y.id)).map(p=>({p,first:fold(name(p)),text:fold([...(p.names||[]).map(x=>x.value),name(p),p.id,...(p.names||[]).map(x=>canonical(x.surname))].join(' '))})));
 const sync=()=>{const p=personBy.get(VALUE.get.call(menu));input.value=p?name(p):'';};
 // The tree sets the menu directly when a person is chosen in the drawing; keep the box in step.
 Object.defineProperty(menu,'value',{configurable:true,get(){return VALUE.get.call(this);},set(v){VALUE.set.call(this,v);sync();}});
 const close=()=>{list.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');active=-1;};
 const move=i=>{active=i;[...list.children].forEach((li,j)=>li.setAttribute('aria-selected',String(j===i)));const li=list.children[i];if(li){input.setAttribute('aria-activedescendant',li.id);li.scrollIntoView?.({block:'nearest'});}};
 const choose=p=>{menu.value=p.id;menu.dispatchEvent(new Event('change',{bubbles:true}));close();status.textContent=`${name(p)} chosen.`;};
 function search(){const words=fold(input.value).trim().split(/\s+/).filter(Boolean);if(!words.length){matches=[];list.replaceChildren();close();status.textContent='';return;}
  // Names starting with the first word come first, then names with a word starting with it, each alphabetical.
  const rank=e=>e.first.startsWith(words[0])?0:e.first.split(/\s+/).some(t=>t.startsWith(words[0]))?1:2;
  const found=entries().filter(e=>words.every(w=>e.text.includes(w))).map(e=>[rank(e),e]).sort((x,y)=>x[0]-y[0]).map(([,e])=>e);matches=found.slice(0,12);
  const names=new Map;matches.forEach(e=>names.set(name(e.p),(names.get(name(e.p))||0)+1));
  list.replaceChildren(...matches.map((e,i)=>{const li=el('li');li.id=`${list.id}-${i}`;li.setAttribute('role','option');const span=lifespan(e.p),meta=[span,names.get(name(e.p))>1||!span?e.p.id:''].filter(Boolean).join(' · ');li.append(el('span',name(e.p)));if(meta)li.append(el('span',meta,'meta'));
   li.addEventListener('mousedown',ev=>ev.preventDefault());li.addEventListener('click',()=>choose(e.p));return li;}));
  if(matches.length){list.hidden=false;input.setAttribute('aria-expanded','true');move(0);}else close();
  status.textContent=!found.length?'No public person matches.':`${found.length.toLocaleString()} match${found.length===1?'':'es'}${found.length>matches.length?`, the first ${matches.length} shown; keep typing to narrow`:''}. Up and down arrows to move, Enter to choose.`;}
 input.addEventListener('input',search);input.addEventListener('blur',close);
 input.addEventListener('keydown',e=>{if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();if(list.hidden){search();return;}if(matches.length)move((active+(e.key==='ArrowDown'?1:-1)+matches.length)%matches.length);}
  else if(e.key==='Enter'&&!list.hidden&&matches[active]){e.preventDefault();choose(matches[active].p);}
  else if(e.key==='Escape'&&!list.hidden){e.preventDefault();close();}});
 menu.addEventListener('change',sync);sync();
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
 const summary=p=>pe(p).sort(byDate).map(e=>`${e.kind}: ${eventDate(e,'date unknown')}`).join('; ');
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
 const modes=el('div',undefined,'tree-modes');modes.setAttribute('role','group');modes.setAttribute('aria-label','Tree view');const modeButtons=new Map;for(const [value,label] of [['whole','Whole tree'],['family','Focus family'],['branches','Branch cards'],['hourglass','Hourglass'],['sun','Family sun'],['lanes','Lanes']]){const button=el('button',label);button.dataset.treeView=value;button.setAttribute('aria-pressed',String(mode===value));button.addEventListener('click',()=>{mode=value;modeButtons.forEach((b,v)=>b.setAttribute('aria-pressed',String(v===mode)));draw();});modes.append(button);modeButtons.set(value,button);}controls.before(modes);
 // ?view=hourglass, sun or lanes opens that view (with ?person=, around that person).
 {const asked=new URLSearchParams(location.search).get('view');if(TREE_VIEWS[asked]){mode=asked;modeButtons.forEach((b,v)=>b.setAttribute('aria-pressed',String(v===mode)));}}
 function transform(){group?.setAttribute('transform',`translate(${tx} ${ty}) scale(${scale})`);}
 function draw(){wholeController?.dispose();wholeController=null;output.replaceChildren();if(mode==='whole'){wholeController=wholeTree(output,root,()=>{mode='family';modeButtons.forEach((b,v)=>b.setAttribute('aria-pressed',String(v===mode)));draw();});return;}if(TREE_VIEWS[mode]){wholeController=TREE_VIEWS[mode](output,root,id=>{root.value=id;draw();});return;}const id=root.value||people[0]?.id;if(!personBy.has(id)){output.append(empty('No public people available to draw.'));return;}
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
 function inspect(n){selected=n;root.value=n.id;detail.replaceChildren();const c=el('div',undefined,'connection-person');c.append(personLink(n.p),el('span',` · ${shownDates(n.p).join(' – ')}`,'meta'));const button=el('button','Focus this family');button.addEventListener('click',focusFamily);detail.append(c,button);schedule();}
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
// Hourglass, family sun and lanes read parent, child and partner links as the dossier does; disproved links are left out.
// The tree views share the catalogue's kind lists above.
const firm=r=>['documented','probable'].includes(r?.confidence);
const bornIn=id=>year(dates(personBy.get(id))[0])??Infinity;
const byBirth=(a,b)=>bornIn(a)-bornIn(b)||name(personBy.get(a)).localeCompare(name(personBy.get(b)))||a.localeCompare(b);
let KIN=null;
function kin(){
 if(KIN)return KIN;const parents=new Map,children=new Map,partners=new Map;
 // A pair recorded twice is one link, shown at its firmer assessment.
 const add=(m,a,b,r)=>{if(!m.has(a))m.set(a,[]);const row=m.get(a),old=row.find(x=>x.id===b);if(!old)row.push({id:b,r});else if(!firm(old.r)&&firm(r))old.r=r;};
 for(const r of relationships){const k=String(r.kind||'').toLowerCase();if(r.confidence==='disproved'||r.subject_id===r.object_id||!personBy.has(r.subject_id)||!personBy.has(r.object_id))continue;if(PARENT_KINDS.includes(k)){add(parents,r.subject_id,r.object_id,r);add(children,r.object_id,r.subject_id,r);}else if(PARTNER_KINDS.includes(k)){add(partners,r.subject_id,r.object_id,r);add(partners,r.object_id,r.subject_id,r);}}
 for(const m of [parents,children,partners])m.forEach(row=>row.sort((a,b)=>byBirth(a.id,b.id)));
 return KIN={parents,children,partners};
}
// More than two parent links means the parents compete; an unconfirmed one among them is a candidate.
const candidate=(child,r)=>!firm(r)&&(kin().parents.get(child)||[]).length>2;
const NO_VIEW={zoom(){},fit(){},dispose(){}};
const ordinal=n=>n+(n%10===1&&n%100!==11?'st':n%10===2&&n%100!==12?'nd':n%10===3&&n%100!==13?'rd':'th');
const generationName=(g,up)=>g<4?(up?['Focus person','Parents','Grandparents','Great-grandparents']:['Focus person','Children','Grandchildren','Great-grandchildren'])[g]:`${ordinal(g-2)} great-${up?'grandparents':'grandchildren'}`;
const singular=s=>s.toLowerCase().replace(/ren$/,'').replace(/s$/,'');
const shorten=(s,n)=>s.length>n?s.slice(0,n-1)+'…':s;
// Pan and zoom for the SVG views, driven by the same −, + and Fit buttons as the whole tree; a drag starts off the people.
function svgPanZoom(svg,group,width,height){
 let tx=0,ty=0,scale=1,drag;const set=()=>group.setAttribute('transform',`translate(${tx} ${ty}) scale(${scale})`);
 const zoom=f=>{const next=Math.min(4,Math.max(.3,scale*f)),ratio=next/scale;tx=width/2-(width/2-tx)*ratio;ty=height/2-(height/2-ty)*ratio;scale=next;set();};
 svg.addEventListener('pointerdown',e=>{if(e.button||e.target.closest('[tabindex],a'))return;drag={x:e.clientX,y:e.clientY,tx,ty};svg.setPointerCapture(e.pointerId);});
 svg.addEventListener('pointermove',e=>{if(!drag)return;const rect=svg.getBoundingClientRect(),k=Math.max(width/rect.width,height/rect.height);tx=drag.tx+(e.clientX-drag.x)*k;ty=drag.ty+(e.clientY-drag.y)*k;set();});
 const stop=()=>drag=null;svg.addEventListener('pointerup',stop);svg.addEventListener('pointercancel',stop);
 svg.addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY>0?.9:1.1);},{passive:false});
 return {zoom,fit(){tx=ty=0;scale=1;set();},dispose(){}};
}
// The text version of a view: one list per heading, each person linked to their dossier with a button to centre the view on them.
function viewText(summary,groups,refocus){
 const d=el('details',undefined,'tree-text');d.append(el('summary',summary));
 for(const [heading,rows] of groups){if(!rows.length)continue;d.append(el('h2',heading));const ul=el('ul');for(const {id,note} of rows){const p=personBy.get(id),li=el('li');li.append(personLink(p));if(note)li.append(el('span',` · ${note}`,'meta'));if(refocus){const b=el('button','Centre here');b.setAttribute('aria-label',`Centre here on ${name(p)}`);b.addEventListener('click',()=>refocus(id));li.append(' ',b);}ul.append(li);}d.append(ul);}
 return d;
}
const activate=(node,act)=>{node.addEventListener('click',act);node.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();act();}});};

// Hourglass: ancestors above the focus person, descendants below, one row per generation; a person's card opens or folds their line.
function hourglassTree(output,root,refocus){
 const id=root.value||people[0]?.id;if(!personBy.has(id)){output.append(empty('No public people available to draw.'));return NO_VIEW;}
 const {parents,children,partners}=kin(),CAP=60,MAX=5,SHOWN=2,W=184,H=60,GAP=16,ROW=104,open=new Set,shut=new Set,host=el('div'),status=el('p','','sr-only');status.setAttribute('role','status');output.append(host,status);let pz=NO_VIEW;
 function build(keep){
  const focus={id,gen:0,side:'focus',up:[],down:[],partners:[],capped:0},seen=new Map([[id,focus]]),edges=[];let over=0;
  const want=n=>n.gen<MAX&&(open.has(n.id)||n.gen<SHOWN&&!shut.has(n.id));
  const take=(owner,rows,side,list)=>{for(const {id:pid,r} of rows){if(seen.has(pid)){edges.push({side,a:owner,b:seen.get(pid),r});continue;}if(seen.size>=CAP){owner.capped++;over++;continue;}const m={id:pid,gen:owner.gen+(side==='partner'?0:1),side,up:[],down:[],partners:[],capped:0,r,from:owner};seen.set(pid,m);list.push(m);edges.push({side,a:owner,b:m,r});}};
  take(focus,partners.get(id)||[],'partner',focus.partners);
  // Nearer generations on both sides fill the 60-person limit before farther ones.
  let up=[focus],down=[focus];
  for(let g=0;g<MAX&&(up.length||down.length);g++){const nu=[],nd=[];
   for(const n of up){n.above=(parents.get(n.id)||[]).length;if(n.above&&want(n)){n.openUp=true;take(n,parents.get(n.id),'up',n.up);nu.push(...n.up);}}
   for(const n of down){n.below=(children.get(n.id)||[]).length;if(n.below&&want(n)){n.openDown=true;take(n,children.get(n.id),'down',n.down);for(const c of n.down)take(c,partners.get(c.id)||[],'partner',c.partners);nd.push(...n.down);}}
   up=nu;down=nd;}
  for(const n of down)n.below=(children.get(n.id)||[]).length;for(const n of up)n.above=(parents.get(n.id)||[]).length;
  // Tidy layout: each line is as wide as its widest generation and a card sits centred over the cards it leads to.
  const measure=(n,key,u)=>{const inner=n[key].reduce((s,k)=>s+measure(k,key,u),0)+GAP*Math.max(0,n[key].length-1);return n['w'+key]=Math.max(u(n),inner);};
  const place=(n,key,u,x0,pos)=>{const inner=n[key].reduce((s,k)=>s+k['w'+key],0)+GAP*Math.max(0,n[key].length-1);pos.set(n,x0+(n['w'+key]-u(n))/2);let x=x0+(n['w'+key]-inner)/2;for(const k of n[key]){place(k,key,u,x,pos);x+=k['w'+key]+GAP;}};
  const unit=n=>W+n.partners.length*(W+GAP),card=()=>W,downPos=new Map,upPos=new Map;measure(focus,'down',unit);measure(focus,'up',card);place(focus,'down',unit,0,downPos);place(focus,'up',card,0,upPos);
  const shift=downPos.get(focus)-upPos.get(focus),all=[...seen.values()],maxUp=Math.max(0,...all.filter(n=>n.side==='up').map(n=>n.gen)),maxDown=Math.max(0,...all.filter(n=>n.side==='down').map(n=>n.gen));
  upPos.forEach((x,n)=>{if(n!==focus)n.x=x+shift;});downPos.forEach((x,n)=>{n.x=x;n.partners.forEach((s,i)=>s.x=x+(i+1)*(W+GAP));});
  all.forEach(n=>{const owner=n.side==='partner'?n.from:n;n.y=(owner.side==='up'?maxUp-owner.gen:maxUp+owner.gen)*ROW+20;});
  const minX=Math.min(...all.map(n=>n.x));all.forEach(n=>n.x+=20-minX);
  const width=Math.max(...all.map(n=>n.x))+W+20,height=Math.max(270,(maxUp+maxDown)*ROW+H+40),count=side=>all.filter(n=>n.side===side).length;
  const plural=(n,one,many)=>`${n} ${n===1?one:many}`,label=`Hourglass tree for ${name(personBy.get(id))}: ${plural(count('up'),'ancestor','ancestors')} in ${plural(maxUp,'generation','generations')} above, ${plural(count('down'),'descendant','descendants')} in ${plural(maxDown,'generation','generations')} below, ${plural(count('partner'),'spouse or partner','spouses or partners')} beside.`;
  const viewport=el('div',undefined,'tree-viewport hourglass-viewport'),svg=svgEl('svg',{viewBox:`0 0 ${width} ${height}`,role:'group','aria-label':label}),group=svgEl('g');svg.dataset.hourglass='';svg.append(group);
  for(const {side,a,b,r} of edges){const dashed=!firm(r),cls=`tree-edge ${dashed?'uncertain':''} ${side==='partner'?'partner':''}`;if(side==='partner'){const [l,rr]=a.x<b.x?[a,b]:[b,a];group.append(svgEl('path',{d:`M${l.x+W},${l.y+H/2} H${rr.x}`,class:cls}));continue;}const [parent,child]=side==='up'?[b,a]:[a,b],px=parent.x+W/2,py=parent.y+H,cx=child.x+W/2,cy=child.y;group.append(svgEl('path',{d:`M${px},${py} V${(py+cy)/2} H${cx} V${cy}`,class:cls+(candidate(child.id,r)?' candidate':'')}));}
  for(const n of all){
   const p=personBy.get(n.id),side=n.side==='focus'?null:n.side==='partner'?'partner':n.side,relation=side==='partner'?`spouse or partner of ${name(personBy.get(n.from.id))}`:side?singular(generationName(n.gen,side==='up')):'focus person';
   const cand=side==='up'&&candidate(n.from.id,n.r),open_=side==='up'?n.openUp:n.openDown,hidden=side==='up'?n.above:side==='down'?n.below:0,canToggle=(side==='up'||side==='down')&&hidden>0&&(open_||n.gen<MAX);
   const extra=n.capped?`${n.capped} more not drawn`:cand?'Candidate parent':side&&side!=='partner'&&hidden&&!open_?`${hidden} ${side==='up'?(hidden===1?'parent':'parents'):(hidden===1?'child':'children')} ${canToggle?'folded':'beyond this view'}`:side&&n.r&&!firm(n.r)?relLabel(n.r):'';
   const g=svgEl(!side&&links[id]?'a':'g',{class:`tree-node hourglass-node ${side?'':'focus'} ${cand?'candidate':''} ${n.r&&!firm(n.r)?'uncertain':''}`,transform:`translate(${n.x} ${n.y})`});g.dataset.person=n.id;
   g.append(svgEl('rect',{width:W,height:H,rx:6}));const t=svgEl('text',{x:12,y:20});t.textContent=shorten(name(p),26);const m=svgEl('text',{x:12,y:36,class:'node-meta'});m.textContent=lifespan(p)||'Dates not recorded';g.append(t,m);if(extra){const x=svgEl('text',{x:12,y:51,class:'node-meta node-extra'});x.textContent=extra;g.append(x);}
   const assessed=n.r?` (${relLabel(n.r)}${cand?', candidate parent':''})`:'',who=`${name(p)}, ${relation}${assessed}, ${lifespan(p)||'dates not recorded'}`;
   if(!side){if(links[id]){g.setAttribute('href',links[id]);g.setAttribute('aria-label',`${who}. Open the dossier`);}else{g.setAttribute('role','img');g.setAttribute('aria-label',who);}}
   else{g.setAttribute('tabindex',0);g.setAttribute('role','button');
    if(canToggle){const noun=side==='up'?(hidden===1?'parent':'parents'):(hidden===1?'child':'children');g.setAttribute('aria-expanded',String(!!open_));g.setAttribute('aria-label',`${who}. ${open_?'Fold':'Show'} ${hidden} ${noun}`);const badge=svgEl('g',{class:'hourglass-toggle','aria-hidden':'true',transform:`translate(${W/2} ${side==='up'?0:H})`});badge.append(svgEl('circle',{r:8}));const s=svgEl('text',{y:4,'text-anchor':'middle'});s.textContent=open_?'−':'+';badge.append(s);g.append(badge);
     activate(g,()=>{if(open_){shut.add(n.id);open.delete(n.id);}else{open.add(n.id);shut.delete(n.id);}build(n.id);status.textContent=`${open_?'Folded':'Showing'} the ${noun} of ${name(p)}.`;});}
    else{g.setAttribute('aria-label',`${who}. Centre the tree here`);activate(g,()=>refocus(n.id));}}
   group.append(g);}
  viewport.append(svg);
  const note=el('p',`Showing ${all.length} people. Select a card to show or fold that line, up to ${MAX} generations each way; a card with nothing to open centres the tree on that person. Dashed lines and outlines mark uncertain or candidate parents. Recorded connections are not proof.`+(over?` ${over} more not drawn (${CAP}-person limit); centre on a relative to see them.`:''),'hint');
  const groups=[[generationName(0,true),[{id,note:lifespan(personBy.get(id))}]]];
  const row=n=>({id:n.id,note:[n.side==='partner'?`spouse or partner of ${name(personBy.get(n.from.id))}`:`${n.side==='up'?'parent':'child'} of ${name(personBy.get(n.from.id))}`,n.r?relLabel(n.r):'',n.side==='up'&&candidate(n.from.id,n.r)?'candidate parent':'',lifespan(personBy.get(n.id))].filter(Boolean).join(' · ')});
  for(let g=1;g<=maxUp;g++)groups.push([generationName(g,true),all.filter(n=>n.side==='up'&&n.gen===g).map(row)]);
  groups.push(['Spouses and partners',all.filter(n=>n.side==='partner').map(row)]);
  for(let g=1;g<=maxDown;g++)groups.push([generationName(g,false),all.filter(n=>n.side==='down'&&n.gen===g).map(row)]);
  const text=viewText('Text version of this hourglass tree',groups,refocus),wasOpen=host.querySelector('details')?.open;text.open=!!wasOpen;
  host.replaceChildren(viewport,note,text);pz=svgPanZoom(svg,group,width,height);
  if(keep)svg.querySelector(`[data-person="${CSS.escape(keep)}"]`)?.focus();
 }
 build();return {zoom:f=>pz.zoom(f),fit:()=>pz.fit(),dispose(){}};
}

// Family sun: the focus person's descendants as rings, one per generation; a slice's angle is its share of the descendants.
function familySun(output,root,refocus){
 const id=root.value||people[0]?.id;if(!personBy.has(id)){output.append(empty('No public people available to draw.'));return NO_VIEW;}
 const {children}=kin(),R0=66,T=58,MAXG=12,LINES=6,seen=new Set,rings=[];let maxGen=0;
 // A person reached by a second line is drawn again as an outline and not followed further.
 const make=(pid,gen,from,r)=>{const again=seen.has(pid);seen.add(pid);const n={id:pid,gen,kids:[],size:1,again,from,r};maxGen=Math.max(maxGen,gen);if(!again&&gen<MAXG)for(const c of children.get(pid)||[]){const k=make(c.id,gen+1,n,c.r);n.kids.push(k);n.size+=k.size;}return n;};
 const sun=make(id,0,null),focusName=name(personBy.get(id));
 if(!sun.kids.length){output.append(empty(`No descendants of ${focusName} are recorded. Choose someone with recorded children to draw a family sun.`));return NO_VIEW;}
 const lay=(n,a0,a1,line)=>{n.a0=a0;n.a1=a1;n.line=line;(rings[n.gen]||(rings[n.gen]=[])).push(n);let a=a0;for(const [i,c] of n.kids.entries()){const w=(a1-a0)*c.size/(n.size-1);lay(c,a,a+w,n.gen?line:i%LINES);a+=w;}};lay(sun,-Math.PI/2,Math.PI*1.5,null);
 const S=R0+maxGen*T+12,viewport=el('div',undefined,'tree-viewport sun-viewport'),unique=seen.size-1;
 const svg=svgEl('svg',{viewBox:`0 0 ${2*S} ${2*S}`,role:'group','aria-label':`Family sun for ${focusName}: ${unique} recorded descendants in ${maxGen} generations. Each ring is a generation; a slice's width is its share of the descendants. Select a slice to centre the sun on that person.`}),pan=svgEl('g'),group=svgEl('g',{transform:`translate(${S} ${S})`});svg.dataset.sun='';pan.append(group);svg.append(pan);
 const readout=el('p','Hover over or focus a slice to see who it is.','sun-readout');readout.setAttribute('aria-live','polite');
 const pt=(r,a)=>`${(r*Math.cos(a)).toFixed(2)},${(r*Math.sin(a)).toFixed(2)}`;
 const arc=(r0,r1,a0,a1)=>{if(a1-a0>Math.PI*2-1e-6)return `M${r1},0A${r1},${r1} 0 1 1 ${-r1},0A${r1},${r1} 0 1 1 ${r1},0ZM${r0},0A${r0},${r0} 0 1 0 ${-r0},0A${r0},${r0} 0 1 0 ${r0},0Z`;const large=a1-a0>Math.PI?1:0;return `M${pt(r1,a0)}A${r1},${r1} 0 ${large} 1 ${pt(r1,a1)}L${pt(r0,a1)}A${r0},${r0} 0 ${large} 0 ${pt(r0,a0)}Z`;};
 const describe=n=>{const p=personBy.get(n.id);return `${name(p)}${lifespan(p)?` (${lifespan(p)})`:''}, generation ${n.gen}, ${singular(generationName(n.gen,false))} of ${name(personBy.get(n.from.id))}${firm(n.r)?'':` (${relLabel(n.r)})`}, ${n.again?'also descends through another line':`${n.size-1} descendant${n.size===2?'':'s'}`}`;};
 const centre=svgEl('circle',{r:R0-4,class:'sun-centre'});group.append(centre);
 const words=focusName.split(' '),half=Math.ceil(words.length/2);[words.slice(0,half).join(' '),words.slice(half).join(' ')].filter(Boolean).forEach((line,i,all)=>{const t=svgEl('text',{y:(i-(all.length-1)/2)*14+4,'text-anchor':'middle',class:'sun-centre-label','aria-hidden':'true'});t.textContent=shorten(line,14);group.append(t);});
 for(let g=1;g<=maxGen;g++)for(const n of rings[g]||[]){const r0=R0+(g-1)*T,r1=R0+g*T,s=svgEl('path',{d:arc(r0,r1,n.a0,n.a1),'fill-rule':'evenodd',class:`sun-slice sun-line-${n.line} ${n.again?'again':''} ${firm(n.r)?'':'uncertain'}`,tabindex:0,role:'button','aria-label':`${describe(n)}. Centre the sun here`,'fill-opacity':Math.max(.5,1-(g-1)*.1).toFixed(2)});s.dataset.person=n.id;s.dataset.generation=g;
  const show=()=>{readout.textContent=describe(n);};s.addEventListener('pointerenter',show);s.addEventListener('focus',show);activate(s,()=>refocus(n.id));group.append(s);
  // Names that fit run along a wide slice, or out along the radius of a narrow one.
  const mid=(n.a0+n.a1)/2,rm=r0+T/2,length=(n.a1-n.a0)*rm,deg=mid*180/Math.PI;let text=null,rot=0;
  if(length>=64){text=shorten(name(personBy.get(n.id)),Math.floor((length-8)/6.4));rot=deg+90+(Math.sin(mid)>0?180:0);}else if(length>=13){text=shorten(name(personBy.get(n.id)).split(' ')[0],8);rot=deg+(Math.cos(mid)<0?180:0);}
  if(text){const t=svgEl('text',{transform:`translate(${pt(rm,mid)}) rotate(${rot.toFixed(1)})`,'text-anchor':'middle',y:4,class:'sun-label','aria-hidden':'true'});t.textContent=text;group.append(t);}}
 viewport.append(svg);
 const legend=el('div',undefined,'sun-legend'),lines=el('ul'),gens=el('ul');for(const [heading,items] of [['Lines from each child',lines],['Generations',gens]]){const part=el('div');part.append(el('p',heading,'meta'),items);legend.append(part);}
 sun.kids.forEach((c,i)=>{const li=el('li'),sw=el('span',undefined,`sun-swatch sun-line-${i%LINES}`);sw.setAttribute('aria-hidden','true');li.append(sw,`${name(personBy.get(c.id))}: ${c.size-1} descendant${c.size===2?'':'s'}`);lines.append(li);});
 const firstSeen=g=>(rings[g]||[]).filter(n=>!n.again);
 for(let g=1;g<=maxGen;g++){const again=(rings[g]||[]).length-firstSeen(g).length;gens.append(el('li',`Generation ${g} · ${generationName(g,false).toLowerCase()}: ${firstSeen(g).length}${again?` (and ${again} reached again through another line)`:''}`));}
 const note=el('p',`${unique} recorded descendants of ${focusName}. Select a slice, or a person in the text version, to centre the sun on them.${maxGen>=MAXG?` Generations past ${MAXG} are not drawn.`:''} Recorded connections are not proof.`,'hint');
 const text=viewText('Text version of this family sun',Array.from({length:maxGen},(_,i)=>[`Generation ${i+1} · ${generationName(i+1,false)} (${firstSeen(i+1).length})`,(rings[i+1]||[]).map(n=>({id:n.id,note:[`${n.gen===1?'child':'descendant'} of ${name(personBy.get(n.from.id))}`,firm(n.r)?'':relLabel(n.r),n.again?'also descends through another line':`${n.size-1} descendant${n.size===2?'':'s'}`,lifespan(personBy.get(n.id))].filter(Boolean).join(' · ')}))]),refocus);
 output.append(viewport,readout,legend,note,text);const pz=svgPanZoom(svg,pan,2*S,2*S);return {zoom:pz.zoom,fit:pz.fit,dispose(){}};
}

// Lanes: the focus person's parents' family, their own family and each child's family, as lifespan bars on one time axis.
function familyLanes(output,root,refocus){
 const id=root.value||people[0]?.id;if(!personBy.has(id)){output.append(empty('No public people available to draw.'));return NO_VIEW;}
 const {parents,children,partners}=kin(),ids=(m,pid)=>(m.get(pid)||[]).map(x=>x.id),who=pid=>name(personBy.get(pid)),lanes=[];
 const parentIds=ids(parents,id),siblings=new Set(parentIds.flatMap(p=>ids(children,p)));
 for(const r of relationsByPerson.get(id)||[])if(SIBLING_KINDS.includes(r.kind)&&r.confidence!=='disproved'){const o=r.subject_id===id?r.object_id:r.subject_id;if(personBy.has(o)&&o!==id)siblings.add(o);}
 if(parentIds.length||siblings.size){siblings.add(id);lanes.push({title:`Parents' family${parentIds.length?`: ${parentIds.map(who).join(' & ')}`:''}`,rows:[...parentIds.map(p=>[p,'parent']),...[...siblings].sort(byBirth).map(s=>[s,s===id?'focus person':'sibling'])]});}
 const family=(pid,role,title)=>({title,rows:[[pid,role],...ids(partners,pid).map(s=>[s,'spouse or partner']),...ids(children,pid).map(c=>[c,role==='focus person'?'child':'grandchild'])]});
 lanes.push(family(id,'focus person',`Own family: ${who(id)}`));
 for(const c of ids(children,id))if(ids(partners,c).length||ids(children,c).length)lanes.push(family(c,'child',`Family of ${who(c)}`));
 // A bar runs from birth to death; without them, from the first to the last dated event.
 const span=pid=>{const ev=pe(personBy.get(pid)).filter(e=>year(e.date)!==null).sort(byDate),ys=ev.map(e=>year(e.date)),b=ev.find(e=>e.kind==='birth'),d=ev.find(e=>e.kind==='death');return {ev,start:b?year(b.date):ys[0]??null,end:d?year(d.date):ys[ys.length-1]??null,closed:!!d};};
 const spans=new Map;lanes.forEach(l=>l.rows.forEach(([pid])=>{if(!spans.has(pid))spans.set(pid,span(pid));}));
 const known=[...spans.values()].filter(s=>s.start!==null),lo=known.length?Math.min(...known.map(s=>s.start)):0,hi=known.length?Math.max(...known.map(s=>s.end)):0;
 const step=hi-lo>200?50:hi-lo>80?20:hi-lo>30?10:5,from=Math.floor(lo/step)*step,to=Math.max(from+step,Math.ceil(hi/step)*step),W=900,X0=214,X1=W-24,ROW=24,HEAD=30,AXIS=34;
 const x=y=>X0+(y-from)/(to-from)*(X1-X0),height=AXIS+lanes.reduce((s,l)=>s+HEAD+l.rows.length*ROW+8,0)+10;
 const viewport=el('div',undefined,'tree-viewport lanes-viewport'),bars=lanes.reduce((s,l)=>s+l.rows.filter(([pid])=>spans.get(pid).start!==null).length,0);
 const svg=svgEl('svg',{viewBox:`0 0 ${W} ${height}`,role:'group','aria-label':`Family lanes around ${who(id)}: ${lanes.length} famil${lanes.length===1?'y':'ies'}, ${bars} lifespan bars${known.length?` from ${lo} to ${hi}`:''}.`}),group=svgEl('g');svg.dataset.lanes='';svg.append(group);
 if(known.length)for(let y=from;y<=to;y+=step){group.append(svgEl('line',{x1:x(y),x2:x(y),y1:AXIS-6,y2:height-10,class:'lane-grid'}));const t=svgEl('text',{x:x(y),y:AXIS-12,'text-anchor':'middle',class:'lane-year'});t.textContent=y;group.append(t);}
 let top=AXIS;
 for(const lane of lanes){const head=svgEl('text',{x:8,y:top+20,class:'lane-head'});head.textContent=shorten(lane.title,110);group.append(head);top+=HEAD;
  for(const [pid,role] of lane.rows){const p=personBy.get(pid),s=spans.get(pid),cy=top+ROW/2,row=svgEl('g',{class:`lane-row ${pid===id?'focus':''}`});
   const nameNode=svgEl(links[pid]?'a':'g',{});if(links[pid])nameNode.setAttribute('href',links[pid]);nameNode.setAttribute('aria-label',`${name(p)}, ${role}, ${lifespan(p)||'no dated events'}`);if(!links[pid])nameNode.setAttribute('role','img');
   const t=svgEl('text',{x:18,y:cy+4,class:'lane-name'});t.textContent=shorten(name(p),27);nameNode.append(t);row.append(nameNode);
   if(s.start===null){const n=svgEl('text',{x:X0,y:cy+4,class:'lane-year','aria-hidden':'true'});n.textContent='No dated events';row.append(n);}
   else{row.append(svgEl('rect',{x:x(s.start),y:cy-5,width:Math.max(4,x(s.end)-x(s.start)),height:10,rx:5,class:`lane-bar ${pid===id?'focus':''} ${s.closed?'':'open'}`}));
    for(const e of s.ev){const c=svgEl('circle',{cx:x(year(e.date)),cy,r:3,class:'lane-event'});const title=svgEl('title');title.textContent=`${name(p)}: ${e.kind} ${eventDate(e)}`;c.append(title);row.append(c);}}
   group.append(row);top+=ROW;}
  top+=8;}
 viewport.append(svg);
 const undated=new Map;spans.forEach((_,pid)=>pe(personBy.get(pid)).filter(e=>year(e.date)===null).forEach(e=>undated.set(e.id+'\u0000'+pid,[pid,e])));
 const extra=el('div',undefined,'lanes-undated');extra.append(el('h2','Events without a year'));if(undated.size){const ul=el('ul');for(const [pid,e] of [...undated.values()].sort((a,b)=>byBirth(a[0],b[0])||a[1].id.localeCompare(b[1].id))){const li=el('li');li.append(personLink(personBy.get(pid)),` · ${e.kind}${e.date?` (${eventDate(e)})`:' (date not recorded)'}`);ul.append(li);}extra.append(ul);}else extra.append(el('p','Every recorded event of these people has a year.','meta'));
 const note=el('p',`${lanes.length} famil${lanes.length===1?'y':'ies'}, ${bars} lifespan bars on one time axis. A bar runs from a recorded birth to a recorded death; a faded bar runs between the first and last dated events instead. Dots mark dated events.`,'hint');
 const text=viewText('Text version of these lanes',lanes.map(l=>[l.title,l.rows.map(([pid,role])=>({id:pid,note:[role,lifespan(personBy.get(pid))||'no dated events'].join(' · ')}))]),refocus);
 output.append(viewport,note,extra,text);const pz=svgPanZoom(svg,group,W,height);return {zoom:pz.zoom,fit:pz.fit,dispose(){}};
}
const TREE_VIEWS={hourglass:hourglassTree,sun:familySun,lanes:familyLanes};
function comparison(){
 const a=$('[data-compare-a]'),b=$('[data-compare-b]'),out=$('#compare-result');if(!a||!b||!out)return;fillPeople(a);fillPeople(b);preselect(a,b);
 function draw(){out.replaceChildren();const pa=personBy.get(a.value),pb=personBy.get(b.value);if(!pa||!pb){out.append(empty('Choose two people to compare the recorded details.'));return;}const grid=el('div',undefined,'comparison');for(const p of [pa,pb]){const card=el('section',undefined,'card');card.append(el('h2',name(p)));const dl=el('dl');const add=(k,v)=>{const dd=el('dd');dd.append(v);dl.append(el('dt',k),dd);};const many=(items,none)=>items.length?pillList(items):none;add('Birth',shownDates(p)[0]);add('Death',shownDates(p)[1]);add('Names',many((p.names||[]).map(n=>n.value).filter(Boolean),'No name recorded'));add('Places',many([...new Set(pe(p).map(e=>placeBy.get(e.place_id)?.name).filter(Boolean))],'No place recorded'));add('Relatives',many(relativeIds(p.id).map(id=>linkTo(id,name(personBy.get(id)))),'No public relationships recorded'));const cs=claimsByPerson.get(p.id)||[];add('Claims',`${cs.length} recorded · ${cs.filter(c=>c.status==='supported').length} supported`);card.append(dl,personLink(p));grid.append(card);}out.append(grid,el('p','Similar details are research leads. Comparison does not establish identity or authorize a merge.','note'));}
 a.addEventListener('change',draw);b.addEventListener('change',draw);draw();
}
function connections(){
 const a=$('[data-connection-a]'),b=$('[data-connection-b]'),out=$('#connection-result');if(!a||!b||!out)return;fillPeople(a);fillPeople(b);preselect(a,b);
 const adjacency=new Map;for(const r of relationships){if(r.confidence==='disproved'||!personBy.has(r.subject_id)||!personBy.has(r.object_id))continue;for(const [x,y] of [[r.subject_id,r.object_id],[r.object_id,r.subject_id]]){if(!adjacency.has(x))adjacency.set(x,[]);adjacency.get(x).push({id:y,relation:r});}}
 function draw(){out.replaceChildren();if(!personBy.has(a.value)||!personBy.has(b.value)){out.append(empty('Choose two people to explore their recorded connections.'));return;}const queue=[a.value],seen=new Map([[a.value,null]]);let found=false;for(let i=0;i<queue.length;i++){const id=queue[i];if(id===b.value){found=true;break;}for(const n of adjacency.get(id)||[]){if(!seen.has(n.id)){seen.set(n.id,{previous:id,relation:n.relation});queue.push(n.id);}}}if(!found){out.append(empty('No connection found in the public records in this project. This does not establish that the people are unrelated.'));return;}const path=[];let id=b.value;while(id!==null){const step=seen.get(id);path.unshift({id,relation:step?.relation});id=step?.previous??null;}out.append(el('p',`${plural(path.length-1,'recorded connection')} · shortest available path`,'result-count'));const row=el('div',undefined,'connection-path'),steps=el('ol',undefined,'connection-sentences');path.forEach((n,i)=>{if(i){const before=path[i-1].id,words=relPhrase(n.relation,before);row.append(el('span',`${words} · ${relLabel(n.relation)}`,'connection-step'));steps.append(el('li',`${name(personBy.get(before))} ${words} ${name(personBy.get(n.id))} (${relLabel(n.relation)})`));}const box=el('div',undefined,'connection-person');box.append(personLink(personBy.get(n.id)));row.append(box);});out.append(row,steps,el('p','This path follows recorded relationships, including uncertain connections. It is not a proof of kinship.','note'));}
 a.addEventListener('change',draw);b.addEventListener('change',draw);draw();
}
function timeline(){
 const host=$('[data-timeline]');if(!host)return;const rows=$$('[data-event-id]',host);
 // A large site lists its decades here; the search covers every event in the shared data.
 const compact=!rows.length&&Number(host.dataset.total||0)>0&&events.length>0;if(!rows.length&&!compact)return;
 const search=el('input');search.type='search';search.placeholder='Person, date, event or place';const kinds=[...new Set(events.map(e=>e.kind))].sort();const kind=select([['','All event types'],...kinds.map(k=>[k,k])]);const bar=el('div',undefined,'toolbar');bar.append(field('Search timeline',search),field('Event type',kind));host.before(bar);const status=el('p',undefined,'result-count');host.before(status);
 if(compact){const index=[...host.children],results=el('ul',undefined,'record-list timeline'),LIMIT=100;results.hidden=true;host.append(results);status.setAttribute('role','status');
  const sorted=[...events].sort(byDate),texts=new Map;const text=e=>{if(!texts.has(e.id))texts.set(e.id,norm([e.date,e.kind,placeBy.get(e.place_id)?.name,e.description,...(e.participant_ids||[]).map(id=>name(personBy.get(id)))].join(' ')));return texts.get(e.id);};
  const item=e=>{const li=el('li'),who=el('p'),place=placeBy.get(e.place_id);const when=el('strong',`${eventDate(e)} · ${e.kind}`);if(e.date)when.dataset.date=e.date;li.append(when);if(place)li.append(` — ${place.name}`);if(e.description)li.append(el('p',e.description));(e.participant_ids||[]).forEach((id,i)=>{if(i)who.append(', ');who.append(linkTo(id,name(personBy.get(id))));});li.append(who);return li;};
  const show=()=>{const words=norm(search.value).trim().split(/\s+/).filter(Boolean);if(!words.length&&!kind.value){results.hidden=true;index.forEach(n=>n.hidden=false);status.textContent=`${events.length.toLocaleString()} events, one page per decade. Search to find events across every decade.`;return;}
   const found=sorted.filter(e=>(!kind.value||e.kind===kind.value)&&words.every(w=>text(e).includes(w)));results.replaceChildren(...found.slice(0,LIMIT).map(item));results.hidden=false;index.forEach(n=>n.hidden=true);
   status.textContent=found.length>LIMIT?`The first ${LIMIT} of ${found.length.toLocaleString()} matching events, in date order. Refine the search to see the others.`:`${found.length.toLocaleString()} of ${plural(events.length,'event')} shown`;};
  search.addEventListener('input',show);kind.addEventListener('change',show);show();return;}
 const render=()=>{let count=0;rows.forEach(row=>{const event=eventBy.get(row.dataset.eventId),text=norm([row.textContent,...(event?.participant_ids||[]).map(id=>name(personBy.get(id)))].join(' '));row.hidden=!(text.includes(norm(search.value))&&(!kind.value||event?.kind===kind.value));if(!row.hidden)count++;});status.textContent=`${count} of ${plural(rows.length,'event')} shown`;};search.addEventListener('input',render);kind.addEventListener('change',render);render();
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
   count.textContent=found.length>LIMIT?`The first ${LIMIT} of ${found.length.toLocaleString()} matching sources. Refine the search to see the others.`:`${found.length.toLocaleString()} of ${plural(all.length,'source')} shown`;};
  input.addEventListener('input',show);show();return;}
 const draw=()=>{let shown=0;rows.forEach(r=>{r.hidden=!norm(r.textContent).includes(norm(input.value));if(!r.hidden)shown++;});$$('[data-source-type]',host).forEach(s=>{s.hidden=$$('[data-source-id]',s).every(r=>r.hidden);});count.textContent=`${shown} of ${plural(rows.length,'source')} shown`;};input.addEventListener('input',draw);draw();
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
   count.textContent=found.length>LIMIT?`The first ${LIMIT} of ${found.length.toLocaleString()} matching studies, most recently updated first. Refine the search to see the others.`:`${found.length.toLocaleString()} of ${plural(all.length,'study')} shown`;};
  input.addEventListener('input',show);show();return;}
 const texts=new Map(cards.map(c=>[c,norm([c.textContent,...linked(studyBy.get(c.dataset.studyId))].join(' '))]));
 const draw=()=>{const words=norm(input.value).trim().split(/\s+/).filter(Boolean);let shown=0;cards.forEach(c=>{c.hidden=!words.every(w=>texts.get(c).includes(w));if(!c.hidden)shown++;});count.textContent=`${shown} of ${plural(cards.length,'study')} shown`;};input.addEventListener('input',draw);draw();
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
// The home page is written in full by the build, so it needs nothing from the shared data.
function overview(){}
function bookmarks(){
 if(view!=='person')return;const id=document.body.dataset.personId;if(!id)return;try{const key='genealogy-workbench-bookmarks',saved=new Set(JSON.parse(localStorage.getItem(key)||'[]'));const button=el('button');const render=()=>{button.textContent=saved.has(id)?'★ Saved on this device':'☆ Save on this device';button.setAttribute('aria-pressed',String(saved.has(id)));};render();button.addEventListener('click',()=>{saved.has(id)?saved.delete(id):saved.add(id);try{localStorage.setItem(key,JSON.stringify([...saved]));render();announce('Saved people updated on this device.');}catch(_){announce('Browser storage is unavailable.');}});($('.dossier-actions')||$('.page-header')||$('main'))?.append(button);}catch(_){} }
// Site search in the top bar: people, places, studies, sources, findings and questions by title.
// The index (a title and one short line per record) loads on first use as a script, which works from file:// as well.
const SEARCH_KINDS={person:'People',place:'Places',study:'Studies',source:'Sources',finding:'Findings',question:'Research questions'};
function siteSearch(){
 const form=$('form.site-search');if(!form)return;const input=$('input[name=q]',form),results=$('.site-search-results',form),count=$('.site-search-count',form);if(!input||!results||!count)return;
 const LIMIT=12;let index=null,loading=false;
 const hint=el('span','Use the down arrow to reach the results and Escape to close them.','sr-only');hint.id='site-search-hint';form.append(hint);input.setAttribute('aria-describedby',hint.id);input.setAttribute('aria-controls',results.id);
 // ⌘K or Ctrl+K anywhere, or / outside a text field, moves to the box; the hint shows this platform's key.
 const mac=/Mac|iPhone|iPad/.test(navigator.platform||navigator.userAgent),key=el('kbd',mac?'⌘K':'Ctrl K','site-search-key');key.setAttribute('aria-hidden','true');input.after(key);input.setAttribute('aria-keyshortcuts','Meta+K Control+K /');
 document.addEventListener('keydown',e=>{const typing=e.target.closest?.('input,textarea,select,[contenteditable]');if(e.altKey)return;if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'||e.key==='/'&&!typing&&!e.metaKey&&!e.ctrlKey){e.preventDefault();input.focus();input.select();}});
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
// The places map opens framed on its places, through the map's own Fit places button; World zooms back out.
function mapFit(){$('#map-output [data-map-fit]')?.click();}
// Places page: a region menu and a place-or-surname search over every place, drawn as the same cards; the first LIMIT matches are shown.
function placeCards(){
 const host=$('[data-place-filter]'),listing=$('[data-place-cards]'),status=$('#place-count');if(!host||!listing||!status||!places.length)return;
 const LIMIT=100,unplaced=host.dataset.unplaced||'',initial=status.textContent,routes={...(data.site?.place_urls||{}),...(data.site?.place_routes||{})};
 // A place's region is the last part of its name as recorded, as the page groups it.
 const regionOf=p=>{const parts=String(p.name).split(',').map(s=>s.trim()).filter(Boolean);return parts.length>1?parts[parts.length-1]:unplaced;};
 // As the cards count them: an event's people are its participants and anyone listing it among their own events.
 const at=new Map(places.map(p=>[p.id,{p,region:regionOf(p),events:0,people:new Set,years:[]}]));
 for(const [pid,evs] of eventsByPerson){if(!personBy.has(pid))continue;for(const e of evs.values())at.get(e.place_id)?.people.add(pid);}
 for(const e of events){const s=at.get(e.place_id);if(!s)continue;s.events++;const y=year(e.date);if(y!==null)s.years.push(y);}
 const records=[...at.values()].map(s=>{const counts=new Map;for(const pid of s.people){const c=canonical(surnameOf(personBy.get(pid)));if(c)counts.set(c,(counts.get(c)||0)+1);}
  s.surnames=[...counts].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0])).map(([n])=>n);s.text=fold([s.p.name,...s.surnames].join(' '));return s;})
  .sort((a,b)=>b.people.size-a.people.size||b.events-a.events||String(a.p.name).localeCompare(String(b.p.name))||a.p.id.localeCompare(b.p.id));
 const counts=new Map;records.forEach(s=>counts.set(s.region,(counts.get(s.region)||0)+1));
 const order=[...counts].sort((a,b)=>(a[0]===unplaced)-(b[0]===unplaced)||b[1]-a[1]||a[0].localeCompare(b[0]));
 const search=el('input'),region=select([['','Any region'],...order.map(([r,n])=>[r,`${r} (${n.toLocaleString()})`])]);search.type='search';search.placeholder='Place name or surname';
 const bar=el('div',undefined,'toolbar place-filters'),query=field('Find a place',search);query.className='grow';bar.append(query);if(order.length>1)bar.append(field('Region',region));host.append(bar);
 const results=el('ul',undefined,'place-cards');results.setAttribute('aria-label','Matching places');results.hidden=true;listing.before(results);
 const pill=n=>{const a=el('a',n,'pill');a.href=`${root}catalogue.html?surname=${encodeURIComponent(n)}`;return a;};
 function card(s){const li=el('li',undefined,'place-card'),h=el('h3'),url=routes[s.p.id];if(url){const a=el('a',s.p.name);a.href=window.GENEALOGY_SITE_DATA?root+url:url;h.append(a);}else h.append(s.p.name);
  const facts=s.region!==unplaced?[s.region]:[],n=s.people.size,lo=s.years.reduce((m,y)=>Math.min(m,y),Infinity),hi=s.years.reduce((m,y)=>Math.max(m,y),-Infinity);
  if(s.events)facts.push(`${n.toLocaleString()} ${n===1?'person':'people'}`,`${s.events.toLocaleString()} event${s.events===1?'':'s'}`,...(s.years.length?[lo===hi?`${lo}`:`${lo}–${hi}`]:[]));else facts.push('No public events recorded');
  li.append(h,el('p',facts.join(' · '),'place-facts'));
  if(s.surnames.length){const p=el('p',undefined,'place-surnames');p.append(el('span','Surnames: ','sr-only'),...s.surnames.slice(0,5).map(pill));if(s.surnames.length>5)p.append(el('span',`and ${(s.surnames.length-5).toLocaleString()} more`,'meta'));li.append(p);}
  const located=typeof s.p.latitude==='number'&&typeof s.p.longitude==='number';let where=located?`${s.p.latitude}, ${s.p.longitude}`:'Coordinates not supplied';if(located&&s.p.precision)where+=s.p.precision!=='exact'?` · located to ${s.p.precision} level`:' · exact location';
  li.append(el('p',where,'meta'));return li;}
 // With nothing chosen the written cards (or, on a large site, the busiest places) are shown again.
 function render(){const words=fold(search.value).trim().split(/\s+/).filter(Boolean),r=region.value;
  if(!words.length&&!r){results.hidden=true;results.replaceChildren();listing.hidden=false;status.textContent=initial;return;}
  const found=records.filter(s=>(!r||s.region===r)&&words.every(w=>s.text.includes(w)));results.replaceChildren(...found.slice(0,LIMIT).map(card));results.hidden=!found.length;listing.hidden=true;
  status.textContent=`${found.length.toLocaleString()} of ${records.length.toLocaleString()} places${found.length>LIMIT?` · first ${LIMIT} shown`:''}`;}
 search.addEventListener('input',render);region.addEventListener('change',render);
}
// A place's event table sorts by year, earliest or latest first; events without a year stay at the end.
function placeEvents(){
 for(const table of $$('table[data-place-events]')){const th=$('th[aria-sort]',table),body=table.tBodies[0];if(!th||!body)continue;
  const rows=[...body.rows],index=new Map(rows.map((r,i)=>[r,i])),y=r=>r.dataset.year?Number(r.dataset.year):null,button=el('button',th.textContent,'sort-button'),arrow=el('span',' ↑');arrow.setAttribute('aria-hidden','true');button.append(arrow);th.replaceChildren(button);
  button.addEventListener('click',()=>{const asc=th.getAttribute('aria-sort')!=='ascending';th.setAttribute('aria-sort',asc?'ascending':'descending');arrow.textContent=asc?' ↑':' ↓';
   body.append(...[...rows].sort((a,b)=>{const ya=y(a),yb=y(b);return (ya===null)-(yb===null)||(ya===null?0:asc?ya-yb:yb-ya)||index.get(a)-index.get(b);}));});}
}
// After tree, comparison and connections, which fill and preselect these menus.
function personPickers(){for(const [menu,label] of [['#tree-root','Find a person to explore from'],['[data-compare-a]','Find the first person'],['[data-compare-b]','Find the second person'],['[data-connection-a]','Find the first person'],['[data-connection-b]','Find the second person']])picker($(menu),label);}
// A link into a closed <details> (a claim row on research.html) opens it; browsers that do not do so themselves still show the target.
function openTargets(){const open=()=>{const target=location.hash.length>1&&document.getElementById(decodeURIComponent(location.hash.slice(1)));let n=target,opened=false;while(n){if(n.tagName==='DETAILS'&&!n.open){n.open=true;opened=true;}n=n.parentElement;}if(opened)target.scrollIntoView();};open();window.addEventListener('hashchange',open);}
const tasks=[overview,catalogue,tree,comparison,connections,timeline,sourceSearch,studySearch,map,bookmarks,personPickers,openTargets];for(const task of tasks){try{task();}catch(error){console.warn('Optional genealogy enhancement unavailable:',task.name,error);}}
try{siteSearch();}catch(error){console.warn('Optional genealogy enhancement unavailable: siteSearch',error);}
for(const task of [mapFit,placeCards,placeEvents]){try{task();}catch(error){console.warn('Optional genealogy enhancement unavailable:',task.name,error);}}
})();
