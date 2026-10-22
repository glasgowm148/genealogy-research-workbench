/* The whole-tree atlas for tree.html: every public person on one radial canvas. Time (or generation) runs
   outward from the centre, each connected group of relatives is a sector around the rim, and lines join
   parents and children (solid) and partners (dashed). site.js offers it as the first tree view and passes
   its helpers in; the layout comes from the build (site.py's atlas_forest), so the drawing and the page's
   readable family list agree. Record values enter the DOM as text only. No network. */
(() => {
'use strict';
const R0=74,R1=520,RIM=18,TAU=Math.PI*2;
// Categories past the eighth share "Other"; the hues stay apart on the paper background.
const PALETTE=['#3f6ea8','#b5762a','#2f7d62','#8a4f9e','#c0504d','#3c97ad','#8c7d22','#c4688f'],OTHER='#a3a89b';
// The badge families of site.css, as dots: documented green, probable gold, possible orange, unassessed grey.
const EVIDENCE=[['documented','Documented','#2e7d4f'],['probable','Probable','#b38a1c'],['possible','Possible','#c8662a'],['unassessed','Unassessed tree link','#8f998a'],['none','No recorded parent','#c9cdbf']];
const MODES={colour:[['country','Country'],['family','Family'],['evidence','Evidence']],arrange:[['year','Year'],['generation','Generation']],show:[['all','Everyone'],['grandparents','Grandparents only']]};
// Kept between redraws of the view (a choice in the person box rebuilds it), and in the address.
let state=null;

window.GenealogyAtlas=function atlas(output,menu,h){
 const {el,people,personBy,name}=h,A=h.data.site?.atlas||{},groups=A.groups||[],kids=A.kids||{},beside=A.beside||{};
 if(!people.length){output.append(h.empty('No public people available to draw.'));return {zoom(){},fit(){},dispose(){}};}
 const hash=new URLSearchParams(location.hash.slice(1)),pick=(key,value)=>MODES[key].some(([v])=>v===value)?value:MODES[key][0][0];
 if(!state)state={colour:pick('colour',hash.get('colour')),arrange:pick('arrange',hash.get('arrange')),show:pick('show',hash.get('show')),born:Number(hash.get('born'))||null,k:1,cx:0,cy:0,tools:true,list:false,tab:'overview',selected:null};
 const {parents,children,partners}=h.kin(),nodes=new Map;

 // Layout: each group a sector as wide as its share of the people; within it every person has a span of
 // slots, a parent centred over their children and a partner beside them (site.py's atlas_forest).
 const gap=Math.min(.014,TAU*.2/Math.max(1,groups.length)),usable=TAU-gap*groups.length,total=groups.reduce((s,g)=>s+g[2],0)||1;
 // A person's slots, worked out once each; the trail stops a loop of parent links.
 const spans=new Map,span=(id,trail=new Set)=>{if(trail.has(id))return 0;if(!spans.has(id)){trail.add(id);const n=(kids[id]||[]).reduce((s,k)=>s+span(k,trail),0);trail.delete(id);spans.set(id,Math.max(n,1+(beside[id]||[]).length));}return spans.get(id);};
 const sectors=[];let angle=-Math.PI/2;
 groups.forEach(([title,roots,size,anchor],gi)=>{const width=usable*size/total,sector={title,size,anchor,a0:angle,a1:angle+width,gi,members:[]};
  const slots=roots.reduce((s,id)=>s+span(id),0)||1,slot=width/slots;let at=angle;
  const place=(id,start,gen,trail)=>{if(nodes.has(id)||trail.has(id)||!personBy.has(id))return 0;trail=new Set(trail).add(id);
   const mates=(beside[id]||[]).filter(m=>personBy.has(m)&&!nodes.has(m)),own=(kids[id]||[]).filter(k=>personBy.has(k)&&!trail.has(k));
   const inner=own.reduce((s,k)=>s+span(k),0),width=Math.max(inner,1+mates.length),centre=start+(width-mates.length)/2*slot;
   nodes.set(id,{id,p:personBy.get(id),angle:centre,gen,sector});sector.members.push(id);
   mates.forEach((m,i)=>{nodes.set(m,{id:m,p:personBy.get(m),angle:centre+(i+1)*slot,gen,sector});sector.members.push(m);});
   let x=start+(width-inner)/2*slot;for(const k of own)x+=place(k,x,gen+1,trail)*slot;return width;};
  for(const id of roots)at+=place(id,at,0,new Set)*slot;
  angle+=width+gap;sectors.push(sector);});
 // Anyone the layout did not reach (a person the build placed in no group) still gets a place, at the last sector's end.
 for(const p of people)if(!nodes.has(p.id)){const s=sectors[sectors.length-1];nodes.set(p.id,{id:p.id,p,angle:s?s.a1:0,gen:0,sector:s||null});s?.members.push(p.id);}
 const all=[...nodes.values()];

 // Years: the birth (or baptism) year; else one read from the person's other events or their relatives'
 // years, drawn hollow as an estimate; with none at all, the person sits on the "no dates" ring.
 const YEARLY=['birth','baptism','christening'],OFFSET={death:-60,burial:-60,marriage:-25};
 for(const n of all){const ev=h.pe(n.p);let y=null;for(const kind of YEARLY){const e=ev.find(x=>x.kind===kind&&h.year(x.date)!==null);if(e){y=h.year(e.date);break;}}
  if(y===null){const dated=ev.map(e=>[h.year(e.date),e.kind]).filter(([v])=>v!==null).sort((a,b)=>a[0]-b[0]);if(dated.length){y=dated[0][0]+(OFFSET[dated[0][1]]??-30);n.est=true;}}n.year=y;}
 for(let pass=0;pass<8;pass++){let changed=false;for(const n of all){if(n.year!==null)continue;const ys=[...(parents.get(n.id)||[]).map(x=>nodes.get(x.id)?.year+28),...(children.get(n.id)||[]).map(x=>nodes.get(x.id)?.year-28),...(partners.get(n.id)||[]).map(x=>nodes.get(x.id)?.year)].filter(v=>Number.isFinite(v));
  if(ys.length){n.year=Math.round(ys.reduce((a,b)=>a+b,0)/ys.length);n.est=true;changed=true;}}if(!changed)break;}
 const years=all.map(n=>n.year).filter(v=>v!==null),lo=years.length?Math.floor(Math.min(...years)/10)*10:0,hi=years.length?Math.max(lo+10,Math.ceil(Math.max(...years)/10)*10):10,maxGen=Math.max(1,...all.map(n=>n.gen));
 if(state.born!==null&&(state.born<lo||state.born>=hi))state.born=null;

 // Colour categories, most common first; the swatch list names them with their counts.
 const BEST=['documented','probable','possible','unassessed'],family=r=>h.FAMILY[h.GRADES[r?.grade]?h.data.site?.grade_confidence?.[r.grade]:String(r?.confidence||'unknown')]||'unassessed';
 const firstPlace=n=>{const ev=h.pe(n.p),e=YEARLY.map(k=>ev.find(x=>x.kind===k&&h.placeBy.has(x.place_id))).find(Boolean)||ev.find(x=>h.placeBy.has(x.place_id));return e?h.placeBy.get(e.place_id):null;};
 for(const n of all){const place=firstPlace(n);n.country=place?h.regionOfPlace(place)||'Location unknown':'Location unknown';n.family=h.canonical(h.surnameOf(n.p))||'No surname recorded';
  const fams=(parents.get(n.id)||[]).map(x=>family(x.r));n.evidence=BEST.find(f=>fams.includes(f))||(fams.length?'unassessed':'none');}
 const categories={};
 for(const key of ['country','family']){const counts=new Map;for(const n of all)counts.set(n[key],(counts.get(n[key])||0)+1);const ranked=[...counts].sort((a,b)=>b[1]-a[1]||String(a[0]).localeCompare(String(b[0])));
  const colour=new Map(ranked.slice(0,PALETTE.length).map(([v],i)=>[v,PALETTE[i]]));categories[key]={colour:v=>colour.get(v)||OTHER,legend:[...ranked.slice(0,PALETTE.length).map(([v,c])=>[v,c,colour.get(v)]),...(ranked.length>PALETTE.length?[['Other',ranked.slice(PALETTE.length).reduce((s,[,c])=>s+c,0),OTHER]]:[])]};}
 {const colour=new Map(EVIDENCE.map(([k,,c])=>[k,c]));categories.evidence={colour:v=>colour.get(v),legend:EVIDENCE.map(([k,label,c])=>[label,all.filter(n=>n.evidence===k).length,c]).filter(([,c])=>c)};}
 const colourOf=n=>categories[state.colour].colour(n[state.colour]);
 const grand=new Set(all.filter(n=>(children.get(n.id)||[]).some(c=>(children.get(c.id)||[]).length)).map(n=>n.id));

 // ---- Markup: heading, tools, the stage with its overlays, the person panel and the keys.
 const section=el('section',undefined,'atlas'),uid='atlas';section.setAttribute('aria-labelledby',`${uid}-heading`);section.dataset.atlas='';
 const intro=el('div',undefined,'atlas-intro'),heading=el('h2','Every person, room to explore');heading.id=`${uid}-heading`;
 const lead=el('p',`Time runs outward from ${lo}. Drag the year slider to watch the families grow.`,'hint');intro.append(el('p','The whole tree','eyebrow'),heading,lead);
 const bar=el('div',undefined,'atlas-bar'),search=el('input'),searchLabel=el('label');search.type='search';search.id=`${uid}-search`;search.setAttribute('autocomplete','off');search.placeholder='Search within the family tree';searchLabel.htmlFor=search.id;searchLabel.className='sr-only';searchLabel.textContent='Search within the family tree';
 const searchWrap=el('div',undefined,'atlas-search');searchWrap.append(searchLabel,search);
 const families=document.querySelector('[data-atlas-families]'),listButton=el('button','Readable family list'),toolsButton=el('button','Filters & tools');
 if(families){listButton.setAttribute('aria-controls',families.id);}else listButton.hidden=true;
 const tools=el('div',undefined,'atlas-tools');tools.id=`${uid}-tools`;toolsButton.setAttribute('aria-controls',tools.id);
 bar.append(searchWrap,listButton,toolsButton);
 const results=el('div',undefined,'atlas-results'),resultStatus=el('p','','meta'),resultList=el('ul');resultStatus.setAttribute('role','status');results.append(resultStatus,resultList);
 // The year slider and its Play button.
 const slider=el('input'),sliderId=`${uid}-born`,sliderLabel=el('label','Born by'),sliderValue=el('output'),play=el('button','Play'),allYears=el('button','All');
 slider.type='range';slider.id=sliderId;slider.min=String(lo);slider.max=String(hi);slider.step='1';sliderLabel.htmlFor=sliderId;sliderValue.htmlFor=sliderId;play.setAttribute('aria-pressed','false');play.dataset.atlasPlay='';
 const yearRow=el('div',undefined,'atlas-row atlas-years');yearRow.append(sliderLabel,slider,sliderValue,play,allYears);tools.append(yearRow);
 const choices={};
 for(const [key,label] of [['show','Show'],['arrange','Arrange by'],['colour','Colour']]){const row=el('div',undefined,'atlas-row'),tag=el('span',label,'atlas-row-label');tag.id=`${uid}-${key}-label`;row.setAttribute('role','group');row.setAttribute('aria-labelledby',tag.id);row.append(tag);
  choices[key]=MODES[key].map(([value,words])=>{const b=el('button',words);b.dataset.atlasChoice=`${key}:${value}`;b.addEventListener('click',()=>{state[key]=value;refresh();});row.append(b);return [value,b];});tools.append(row);}
 const swatches=el('ul',undefined,'atlas-swatches');swatches.setAttribute('aria-label','Colour key');tools.append(swatches);
 const layout=el('div',undefined,'atlas-layout'),stage=el('div',undefined,'atlas-stage'),canvas=el('canvas');canvas.tabIndex=0;canvas.setAttribute('role','img');canvas.dataset.atlasCanvas='';
 const help=el('p','Drag to pan, scroll or pinch to zoom, select a dot to read about a person. With the keyboard: arrow keys pan, + and − zoom, 0 fits the tree, Escape clears the selection; the search box and the readable family list reach every person.','hint');help.id=`${uid}-help`;canvas.setAttribute('aria-describedby',help.id);
 const pad=el('div',undefined,'atlas-pad');pad.setAttribute('role','group');pad.setAttribute('aria-label','Move the view');
 for(const [text,label,dx,dy] of [['↑','Move up',0,1],['←','Move left',1,0],['↓','Move down',0,-1],['→','Move right',-1,0]]){const b=el('button',text);b.setAttribute('aria-label',label);b.dataset.move=label.split(' ')[1];b.addEventListener('click',()=>pan(dx*90,dy*90));pad.append(b);}
 const zoomBar=el('div',undefined,'atlas-zoom'),minus=el('button','−'),level=el('button','100%'),plus=el('button','+'),fitButton=el('button','Fit');zoomBar.setAttribute('role','group');zoomBar.setAttribute('aria-label','Zoom');
 minus.setAttribute('aria-label','Zoom out');plus.setAttribute('aria-label','Zoom in');level.setAttribute('aria-label','Zoom level 100%: return to 100%');fitButton.setAttribute('aria-label','Fit the whole tree');level.dataset.atlasZoom='';zoomBar.append(minus,level,plus,fitButton);
 const mini=el('canvas',undefined,'atlas-minimap');mini.setAttribute('aria-hidden','true');mini.width=mini.height=0;
 stage.append(canvas,pad,zoomBar,mini);
 const panel=el('aside',undefined,'atlas-panel');panel.hidden=true;panel.dataset.atlasPanel='';panel.setAttribute('aria-labelledby',`${uid}-person`);
 layout.append(stage,panel);
 const count=el('p','','atlas-count');
 const lines=el('ul',undefined,'atlas-lines');for(const [cls,words] of [['parent','Parent relationship'],['uncertain','Possible or unassessed parent link'],['partner','Partners / co-parents'],['estimate','Hollow dot: birth year estimated']]){const li=el('li'),mark=el('span',undefined,`atlas-line atlas-line-${cls}`);mark.setAttribute('aria-hidden','true');li.append(mark,words);lines.append(li);}
 const announce=el('p','','sr-only');announce.setAttribute('role','status');
 section.append(intro,bar,results,tools,layout,count,lines,help,announce);output.append(section);

 // ---- Drawing.
 const ctx=canvas.getContext('2d'),mctx=mini.getContext?.('2d');
 if(!ctx){stage.replaceChildren(h.empty('Canvas drawing is unavailable in this browser. The readable family list below names every family.'));return {zoom(){},fit(){},dispose(){}};}
 let width=0,height=0,scale=1,tx=0,ty=0,frame=0,dead=false,shown=all,matches=null,playing=0;
 const radius=n=>state.arrange==='generation'?R0+n.gen/maxGen*(R1-R0):n.year===null?R1+6:R0+(n.year-lo)/(hi-lo)*(R1-R0);
 const visible=n=>(state.born===null||(n.year!==null&&n.year<=state.born))&&(state.show!=='grandparents'||grand.has(n.id));
 const cut=()=>state.born===null?hi:state.born;
 function positions(){for(const n of all){const r=radius(n);n.r=r;n.x=Math.cos(n.angle)*r;n.y=Math.sin(n.angle)*r;}shown=all.filter(visible);}
 function view(){width=stage.clientWidth||800;height=stage.clientHeight||560;const fitScale=Math.min(width,height)/(2*(R1+RIM+70));scale=fitScale*state.k;tx=width/2-state.cx*scale;ty=height/2-state.cy*scale;}
 const step=hi-lo>300?100:hi-lo>120?50:hi-lo>50?25:10;
 function paint(){frame=0;if(dead)return;view();const dpr=Math.min(window.devicePixelRatio||1,2);if(canvas.width!==Math.round(width*dpr)||canvas.height!==Math.round(height*dpr)){canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);}
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);ctx.save();ctx.translate(tx,ty);ctx.scale(scale,scale);const px=1/scale;
  // Sector tints, then the time or generation rings.
  for(const s of sectors){const top=s.members.map(id=>nodes.get(id)).filter(visible);if(!top.length)continue;ctx.beginPath();ctx.moveTo(Math.cos(s.a0)*R0,Math.sin(s.a0)*R0);ctx.arc(0,0,R1+4,s.a0,s.a1);ctx.arc(0,0,R0,s.a1,s.a0,true);ctx.closePath();ctx.globalAlpha=.07;ctx.fillStyle=dominant(s);ctx.fill();ctx.globalAlpha=1;}
  ctx.strokeStyle='#d9dbcf';ctx.lineWidth=px;ctx.setLineDash([]);
  const rings=state.arrange==='generation'?Array.from({length:maxGen+1},(_,g)=>[R0+g/maxGen*(R1-R0),`Generation ${g+1}`]):Array.from({length:Math.floor((hi-lo)/step)+1},(_,i)=>[R0+i*step/(hi-lo)*(R1-R0),String(lo+i*step)]);
  for(const [r] of rings){ctx.beginPath();ctx.arc(0,0,r,0,TAU);ctx.stroke();}
  if(state.arrange==='year'&&state.born!==null){ctx.strokeStyle='#a88742';ctx.lineWidth=1.5*px;ctx.setLineDash([4*px,3*px]);ctx.beginPath();ctx.arc(0,0,radius({year:state.born}),0,TAU);ctx.stroke();ctx.setLineDash([]);}
  // Parent links, batched by colour: solid when documented or probable, dotted and faint otherwise.
  const on=new Set(shown.map(n=>n.id)),sel=state.selected&&nodes.get(state.selected);
  for(const certain of [true,false]){const batches=new Map;for(const n of shown)for(const {id,r} of parents.get(n.id)||[]){if(!on.has(id)||h.firm(r)!==certain)continue;const c=colourOf(n);if(!batches.has(c))batches.set(c,[]);batches.get(c).push([nodes.get(id),n]);}
   ctx.lineWidth=(certain?1.1:.9)*px;ctx.setLineDash(certain?[]:[1.5*px,2.5*px]);ctx.globalAlpha=matches?.12:certain?.55:.4;
   for(const [c,pairs] of batches){ctx.strokeStyle=c;ctx.beginPath();for(const [a,b] of pairs)curve(a,b);ctx.stroke();}}
  ctx.globalAlpha=matches?.15:.7;ctx.strokeStyle='#a88742';ctx.lineWidth=px;ctx.setLineDash([4*px,3*px]);ctx.beginPath();
  for(const n of shown)for(const {id} of partners.get(n.id)||[]){if(id<n.id||!on.has(id))continue;const b=nodes.get(id);ctx.moveTo(n.x,n.y);ctx.lineTo(b.x,b.y);}ctx.stroke();ctx.setLineDash([]);ctx.globalAlpha=1;
  // The selected person's own links, drawn over the rest.
  if(sel&&on.has(sel.id)){ctx.strokeStyle='#193e32';ctx.lineWidth=2.2*px;ctx.beginPath();for(const {id} of parents.get(sel.id)||[])if(on.has(id))curve(nodes.get(id),sel);for(const {id} of children.get(sel.id)||[])if(on.has(id))curve(sel,nodes.get(id));ctx.stroke();
   ctx.setLineDash([4*px,3*px]);ctx.beginPath();for(const {id} of partners.get(sel.id)||[])if(on.has(id)){const b=nodes.get(id);ctx.moveTo(sel.x,sel.y);ctx.lineTo(b.x,b.y);}ctx.stroke();ctx.setLineDash([]);}
  // Dots, batched by colour; an estimated year is a ring, a search miss is faded.
  const dot=Math.max(2.8,Math.min(5,2.8*Math.sqrt(state.k)))*px,batches=new Map;
  for(const n of shown){const x=n.x*scale+tx,y=n.y*scale+ty;if(x<-20||y<-20||x>width+20||y>height+20)continue;const key=colourOf(n)+(n.est||n.year===null?'o':'f')+(matches&&!matches.has(n.id)?'d':'');if(!batches.has(key))batches.set(key,[]);batches.get(key).push(n);}
  for(const [key,list] of batches){const c=key.slice(0,7),hollow=key[7]==='o';ctx.globalAlpha=key.endsWith('d')?.18:1;ctx.beginPath();for(const n of list){ctx.moveTo(n.x+dot,n.y);ctx.arc(n.x,n.y,dot,0,TAU);}if(hollow){ctx.strokeStyle=c;ctx.lineWidth=1.2*px;ctx.fillStyle='#fffef9';ctx.fill();ctx.stroke();}else{ctx.fillStyle=c;ctx.fill();}}ctx.globalAlpha=1;
  if(sel&&on.has(sel.id)){ctx.beginPath();ctx.arc(sel.x,sel.y,dot+4*px,0,TAU);ctx.strokeStyle='#193e32';ctx.lineWidth=2*px;ctx.stroke();}
  // The rim: one band per family group, in the colour most of its people share.
  for(const s of sectors){ctx.beginPath();ctx.arc(0,0,R1+RIM*.75,s.a0,s.a1);ctx.strokeStyle=dominant(s);ctx.lineWidth=RIM*.5;ctx.globalAlpha=.85;ctx.stroke();ctx.globalAlpha=1;}
  ctx.restore();
  // Text in screen pixels: ring years, the centre, group names round the rim and people's names.
  ctx.font='11px system-ui,sans-serif';ctx.textBaseline='middle';ctx.lineJoin='round';const boxes=[];
  const label=(text,x,y,{align='left',colour='#233b32',weight='',force=false}={})=>{ctx.font=`${weight}11px system-ui,sans-serif`;const w=ctx.measureText(text).width,x0=align==='right'?x-w:align==='center'?x-w/2:x,box=[x0-2,y-8,x0+w+2,y+8];
   if(!force&&(x0<0||x0+w>width||y<8||y>height-8||boxes.some(b=>b[0]<box[2]&&box[0]<b[2]&&b[1]<box[3]&&box[1]<b[3])))return false;boxes.push(box);ctx.textAlign='left';if(weight==='700 '){ctx.fillStyle='rgba(255,254,249,.96)';ctx.strokeStyle='#193e32';ctx.lineWidth=1;ctx.beginPath();ctx.rect(box[0]-3,box[1]-1,box[2]-box[0]+6,box[3]-box[1]+2);ctx.fill();ctx.stroke();}ctx.lineWidth=3;ctx.strokeStyle='rgba(255,254,249,.92)';ctx.strokeText(text,x0,y);ctx.fillStyle=colour;ctx.fillText(text,x0,y);return true;};
  const cx=tx,cy=ty;
  if(R0*scale>26){label(state.arrange==='generation'?`${maxGen+1} generations`:`${lo}–${cut()}`,cx,cy-7,{align:'center',weight:'600 ',force:true});label(h.plural(shown.length,'person'),cx,cy+8,{align:'center',colour:'#5b635a',force:true});}
  for(const [r,text] of rings)label(text,cx,cy-r*scale,{align:'center',colour:'#5b635a'});
  if(sel&&on.has(sel.id)){const near=[sel,...[...parents.get(sel.id)||[],...children.get(sel.id)||[],...partners.get(sel.id)||[]].map(x=>nodes.get(x.id)).filter(n=>n&&on.has(n.id))];for(const n of near)personLabel(n,n===sel);}
  for(const s of sectors){const mid=(s.a0+s.a1)/2,r=(R1+RIM+8)*scale,x=cx+Math.cos(mid)*r,y=cy+Math.sin(mid)*r;if((s.a1-s.a0)*r<14&&s.gi>12)continue;label(rimText(s),x+(Math.cos(mid)<0?-4:4),y,{align:Math.cos(mid)<0?'right':'left',colour:'#193e32',weight:'600 '});}
  if(matches)for(const id of [...matches].slice(0,40)){const n=nodes.get(id);if(n&&on.has(id))personLabel(n);}
  // Names fill in as the zoom gives them room.
  if(state.k>=2.2){let drawn=0;for(const n of shown){if(drawn>260)break;const x=n.x*scale+tx,y=n.y*scale+ty;if(x<0||y<0||x>width||y>height)continue;if(personLabel(n))drawn++;}}
  function personLabel(n,strong){const x=n.x*scale+tx,y=n.y*scale+ty,right=Math.cos(n.angle)>=0||n.r<R0*1.2;return label(`${name(n.p)}${n.year!==null?` · ${n.est?'c. ':''}${n.year}`:''}`,x+(right?9:-9),y,{align:right?'left':'right',weight:strong?'700 ':'',force:strong});}
  drawMini();}
 function curve(a,b){const m=(a.r+b.r)/2;ctx.moveTo(a.x,a.y);ctx.bezierCurveTo(Math.cos(a.angle)*m,Math.sin(a.angle)*m,Math.cos(b.angle)*m,Math.sin(b.angle)*m,b.x,b.y);}
 const dominantCache=new Map;
 function dominant(s){const key=s.gi+state.colour;if(!dominantCache.has(key)){const counts=new Map;for(const id of s.members){const v=nodes.get(id)[state.colour];counts.set(v,(counts.get(v)||0)+1);}const best=[...counts].sort((a,b)=>b[1]-a[1])[0];dominantCache.set(key,best?categories[state.colour].colour(best[0]):OTHER);}return dominantCache.get(key);}
 const rimText=s=>s.anchor&&personBy.has(s.anchor)?`${name(personBy.get(s.anchor))} · ${s.size.toLocaleString()}`:`${s.title.replace(/\s*\(.*\)$/,'')} · ${s.size.toLocaleString()}`;
 function drawMini(){if(!mctx||!mini.clientWidth)return;const size=mini.clientWidth,dpr=Math.min(window.devicePixelRatio||1,2);if(mini.width!==size*dpr){mini.width=mini.height=size*dpr;}
  const k=size/(2*(R1+RIM+20));mctx.setTransform(dpr,0,0,dpr,0,0);mctx.clearRect(0,0,size,size);mctx.save();mctx.translate(size/2,size/2);mctx.scale(k,k);
  for(const s of sectors){mctx.beginPath();mctx.arc(0,0,R1+RIM*.75,s.a0,s.a1);mctx.strokeStyle=dominant(s);mctx.lineWidth=RIM;mctx.stroke();}
  const batches=new Map;for(const n of shown){const c=colourOf(n);if(!batches.has(c))batches.set(c,[]);batches.get(c).push(n);}
  for(const [c,list] of batches){mctx.fillStyle=c;mctx.beginPath();for(const n of list){mctx.rect(n.x-5,n.y-5,10,10);}mctx.fill();}
  // The part of the tree in view.
  const x0=(0-tx)/scale,y0=(0-ty)/scale,x1=(width-tx)/scale,y1=(height-ty)/scale;mctx.strokeStyle='#193e32';mctx.lineWidth=2/k;mctx.strokeRect(x0,y0,x1-x0,y1-y0);mctx.restore();}
 const schedule=()=>{if(!frame&&!dead)frame=requestAnimationFrame(paint);};

 // ---- Moving about.
 const fitScale=()=>Math.min(width||stage.clientWidth||800,height||stage.clientHeight||560)/(2*(R1+RIM+70));
 function zoom(factor,sx=width/2,sy=height/2){view();const k=Math.min(40,Math.max(.5,state.k*factor)),wx=(sx-tx)/scale,wy=(sy-ty)/scale,next=fitScale()*k;state.k=k;state.cx=wx-(sx-width/2)/next;state.cy=wy-(sy-height/2)/next;changed();}
 function pan(dx,dy){view();state.cx-=dx/scale;state.cy-=dy/scale;changed();}
 function fit(){state.k=1;state.cx=state.cy=0;changed();}
 function centreOn(n){view();state.k=Math.max(state.k,3);state.cx=n.x;state.cy=n.y;}
 function changed(){level.textContent=`${Math.round(state.k*100)}%`;level.setAttribute('aria-label',`Zoom level ${Math.round(state.k*100)}%: return to 100%`);schedule();}
 minus.addEventListener('click',()=>zoom(1/1.4));plus.addEventListener('click',()=>zoom(1.4));level.addEventListener('click',()=>{state.k=1;changed();});fitButton.addEventListener('click',fit);
 const pointers=new Map;let drag=null,pinch=null;
 canvas.addEventListener('pointerdown',e=>{pointers.set(e.pointerId,[e.clientX,e.clientY]);canvas.setPointerCapture(e.pointerId);if(pointers.size===2){const [a,b]=[...pointers.values()];pinch={d:Math.hypot(a[0]-b[0],a[1]-b[1]),k:state.k};drag=null;}else drag={x:e.clientX,y:e.clientY,cx:state.cx,cy:state.cy,moved:false};});
 canvas.addEventListener('pointermove',e=>{if(!pointers.has(e.pointerId))return;pointers.set(e.pointerId,[e.clientX,e.clientY]);
  if(pinch&&pointers.size===2){const [a,b]=[...pointers.values()],rect=canvas.getBoundingClientRect();zoom(pinch.k*Math.hypot(a[0]-b[0],a[1]-b[1])/pinch.d/state.k,(a[0]+b[0])/2-rect.left,(a[1]+b[1])/2-rect.top);return;}
  if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>4)drag.moved=true;if(drag.moved){view();state.cx=drag.cx-dx/scale;state.cy=drag.cy-dy/scale;schedule();}});
 const lift=e=>{const tap=drag&&!drag.moved&&pointers.size===1;pointers.delete(e.pointerId);if(pointers.size<2)pinch=null;if(tap&&e.type==='pointerup'){const rect=canvas.getBoundingClientRect(),x=(e.clientX-rect.left-tx)/scale,y=(e.clientY-rect.top-ty)/scale;let best=null,d=(12/scale)**2;for(const n of shown){const q=(n.x-x)**2+(n.y-y)**2;if(q<d){best=n;d=q;}}if(best)select(best.id);}drag=null;};
 canvas.addEventListener('pointerup',lift);canvas.addEventListener('pointercancel',lift);
 canvas.addEventListener('wheel',e=>{e.preventDefault();const rect=canvas.getBoundingClientRect();zoom(e.deltaY>0?1/1.15:1.15,e.clientX-rect.left,e.clientY-rect.top);},{passive:false});
 canvas.addEventListener('keydown',e=>{const keys={ArrowLeft:[60,0],ArrowRight:[-60,0],ArrowUp:[0,60],ArrowDown:[0,-60]};if(keys[e.key]){e.preventDefault();pan(...keys[e.key]);}else if(e.key==='+'||e.key==='='){e.preventDefault();zoom(1.4);}else if(e.key==='-'||e.key==='_'){e.preventDefault();zoom(1/1.4);}else if(e.key==='0'){e.preventDefault();fit();}else if(e.key==='Escape'&&state.selected){e.preventDefault();clear();}});
 const miniMove=e=>{if(!(e.buttons&1)&&e.type!=='pointerdown')return;const rect=mini.getBoundingClientRect(),k=rect.width/(2*(R1+RIM+20));state.cx=(e.clientX-rect.left-rect.width/2)/k;state.cy=(e.clientY-rect.top-rect.height/2)/k;schedule();};
 mini.addEventListener('pointerdown',miniMove);mini.addEventListener('pointermove',miniMove);
 const observer=typeof ResizeObserver==='function'?new ResizeObserver(schedule):null;observer?.observe(stage);

 // ---- The person panel: who, when and where, links out, then Overview, Family and Research tabs.
 function select(id,{centre=false,focus=false}={}){const n=nodes.get(id);if(!n)return;state.selected=id;if(menu)menu.value=id;if(centre){if(!visible(n)){state.born=null;state.show='all';}positions();centreOn(n);}fill(n);sync();schedule();announce.textContent=`${name(n.p)} selected.`;if(focus)panel.querySelector('h3')?.focus();}
 function clear(){state.selected=null;if(menu)menu.value='';panel.hidden=true;panel.replaceChildren();sync();schedule();announce.textContent='Selection cleared.';canvas.focus();}
 const button=(text,cls)=>{const b=el('button',text,cls);b.type='button';return b;};
 const linkTo=(href,text,cls)=>{const a=el('a',text,cls);a.href=href;return a;};
 function relativeList(title,rows){const box=el('div',undefined,'atlas-relatives');box.append(el('h4',title));if(!rows.length){box.append(el('p','None recorded.','meta'));return box;}const ul=el('ul');
  for(const {id,r} of rows){const p=personBy.get(id),li=el('li'),b=button(name(p),'atlas-relative');b.setAttribute('aria-label',`Select ${name(p)} in the atlas`);b.addEventListener('click',()=>select(id,{centre:true,focus:true}));li.append(b);const span=h.lifespan(p);if(span)li.append(el('span',` ${span}`,'meta'));if(r){const m=el('span',undefined,'atlas-badges');m.append(' ',...h.relBadges(r));li.append(m);}ul.append(li);}box.append(ul);return box;}
 function fill(n){const p=n.p,id=n.id,uidp=`${uid}-person`;panel.hidden=false;panel.replaceChildren();
  const head=el('div',undefined,'atlas-panel-head'),close=button('×','atlas-close');close.setAttribute('aria-label','Close the person profile');close.addEventListener('click',clear);head.append(el('p','Person profile','eyebrow'),close);
  const title=el('h3',name(p));title.id=uidp;title.tabIndex=-1;
  const [born,died]=h.shownDates(p);panel.append(head,el('p',p.external_id||id,'record-id'),title,el('p',[born,died].filter(v=>v!=='Unknown').join(' – ')||'Dates not recorded','lifespan'));
  const actions=el('p',undefined,'atlas-actions'),profile=A.profiles?.[id];
  if(profile){const a=linkTo(profile[1],`${profile[0]} ↗`,'button');a.rel='noopener';actions.append(a,' ');}
  actions.append(linkTo(`${h.prefix}catalogue.html?q=${encodeURIComponent(p.external_id||id)}`,'Catalogue','button button-quiet'));panel.append(actions);
  const reads=el('ul',undefined,'atlas-reads');if(h.links[id]){const li=el('li');li.append(linkTo(h.links[id],'Read current assessment & sources →'));reads.append(li);const ev=el('li');ev.append(linkTo(`${h.links[id]}#events`,'Open this person’s events and places'));reads.append(ev);}if(reads.childElementCount)panel.append(reads);
  const ev=h.pe(p).sort(h.byDate),regions=[];for(const e of ev){const pl=h.placeBy.get(e.place_id);const r=pl&&h.regionOfPlace(pl);if(r&&regions[regions.length-1]!==r)regions.push(r);}
  if(regions.length)panel.append(el('p',regions.join(' → '),'atlas-route'));
  const tabs=el('div',undefined,'atlas-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label',`About ${name(p)}`);const bodies=[];
  const overview=el('dl',undefined,'atlas-facts');for(const e of ev.slice(0,8)){const pl=h.placeBy.get(e.place_id),row=el('div');row.append(el('dt',e.kind.replace(/_/g,' ').replace(/^./,c=>c.toUpperCase())));const dd=el('dd',h.eventDate(e));if(pl)dd.append(el('span',pl.name,'meta'));row.append(dd);overview.append(row);}
  if(!ev.length)overview.append(el('p','No public events recorded.','meta'));if(ev.length>8)overview.append(el('p',`${ev.length-8} more events on the person’s page.`,'meta'));
  const fam=el('div');fam.append(relativeList('Parents',parents.get(id)||[]),relativeList('Spouses and partners',partners.get(id)||[]),relativeList('Children',children.get(id)||[]));
  const research=el('div'),claims=(h.claimsOf(id)||[]),studies=h.studies.filter(s=>(s.related_ids||[]).includes(id)),changes=p.changes||[];
  research.append(el('p',claims.length?`${h.plural(claims.length,'claim')} recorded, ${claims.filter(c=>c.status==='supported').length} supported by evidence.`:'No claims recorded yet.'));
  if(studies.length){research.append(el('h4','Studies'));const ul=el('ul');for(const s of studies){const li=el('li');li.append(linkTo(h.studyUrl(s.id),s.title||s.id));ul.append(li);}research.append(ul);}
  if(changes.length)research.append(el('p',`${h.plural(changes.length,'relationship change')} waiting to be made on ${A.tree_name||'the tree'}.`,'meta'));
  if(h.links[id]){const more=el('p');more.append(linkTo(`${h.links[id]}#research`,'Research notes on the person’s page →'));research.append(more);}
  for(const [key,words,body] of [['overview','Overview',overview],['family','Family',fam],['research','Research',research]]){const tab=button(words),pane=el('div',undefined,'atlas-pane');tab.id=`${uidp}-tab-${key}`;pane.id=`${uidp}-pane-${key}`;tab.setAttribute('role','tab');tab.setAttribute('aria-controls',pane.id);pane.setAttribute('role','tabpanel');pane.setAttribute('aria-labelledby',tab.id);pane.tabIndex=0;pane.append(body);tab.dataset.tab=key;tabs.append(tab);bodies.push([key,tab,pane]);
   tab.addEventListener('click',()=>{state.tab=key;show();});}
  const show=()=>{for(const [key,tab,pane] of bodies){const on=key===state.tab;tab.setAttribute('aria-selected',String(on));tab.tabIndex=on?0:-1;pane.hidden=!on;}};
  tabs.addEventListener('keydown',e=>{const i=bodies.findIndex(([key])=>key===state.tab),move={ArrowRight:1,ArrowLeft:-1,Home:-i,End:bodies.length-1-i}[e.key];if(move===undefined)return;e.preventDefault();state.tab=bodies[(i+move+bodies.length)%bodies.length][0];show();bodies.find(([key])=>key===state.tab)[1].focus();});
  show();panel.append(tabs,...bodies.map(([,,pane])=>pane));
  const explore=button('Explore this family →','atlas-explore');explore.addEventListener('click',()=>h.open('branches',id));panel.append(explore);}

 // ---- Controls, the address and the readable list.
 function sync(){for(const key of Object.keys(choices))for(const [value,b] of choices[key])b.setAttribute('aria-pressed',String(state[key]===value));
  slider.value=String(cut());sliderValue.textContent=state.born===null?'all years':String(state.born);allYears.disabled=state.born===null;
  toolsButton.setAttribute('aria-expanded',String(state.tools));tools.hidden=!state.tools;listButton.setAttribute('aria-expanded',String(state.list));if(families)families.hidden=!state.list;
  swatches.replaceChildren(...categories[state.colour].legend.map(([words,n,c])=>{const li=el('li'),sw=el('span',undefined,'atlas-swatch');sw.style.background=c;sw.setAttribute('aria-hidden','true');li.append(sw,`${words} `,el('span',n.toLocaleString(),'meta'));return li;}));
  const named=sectors.filter(s=>s.anchor).length;count.textContent=`${h.plural(shown.length,'person')} shown of ${all.length.toLocaleString()} · ${h.plural(named,'family group')} around the edge${sectors.length>named?', and those with no recorded relatives':''}`;
  canvas.setAttribute('aria-label',`Atlas of the whole tree: ${h.plural(shown.length,'person')} on rings by ${state.arrange==='generation'?'generation':`birth year from ${lo} to ${cut()}`}, coloured by ${state.colour}, in ${h.plural(sectors.length,'sector')}.${state.selected?` ${name(personBy.get(state.selected))} is selected.`:''}`);
  const q=new URLSearchParams({view:'atlas'});if(state.selected)q.set('person',state.selected);for(const key of ['colour','arrange','show'])if(state[key]!==MODES[key][0][0])q.set(key,state[key]);if(state.born!==null)q.set('born',String(state.born));
  try{history.replaceState(history.state,'',`${location.pathname}${location.search}#${q}`);}catch(_){/* a file:// page in some browsers */}}
 function refresh(){dominantCache.clear();positions();sync();schedule();}
 slider.addEventListener('input',()=>{const v=Number(slider.value);state.born=v>=hi?null:v;stopPlay();refresh();});
 allYears.addEventListener('click',()=>{state.born=null;stopPlay();refresh();});
 function stopPlay(){if(playing){clearInterval(playing);playing=0;play.textContent='Play';play.setAttribute('aria-pressed','false');}}
 play.addEventListener('click',()=>{if(playing){stopPlay();return;}if(state.born===null||state.born>=hi)state.born=lo;play.textContent='Pause';play.setAttribute('aria-pressed','true');const by=Math.max(1,Math.round((hi-lo)/90));
  playing=setInterval(()=>{const next=(state.born??lo)+by;state.born=next>=hi?null:next;if(state.born===null)stopPlay();refresh();},90);refresh();});
 toolsButton.addEventListener('click',()=>{state.tools=!state.tools;sync();schedule();});
 listButton.addEventListener('click',()=>{state.list=!state.list;sync();if(state.list)families?.querySelector('h2')?.scrollIntoView?.({block:'nearest'});});
 // Each person in the readable list can be chosen in the atlas from the keyboard.
 const added=[];if(families)for(const li of families.querySelectorAll('li[data-person-id]')){const id=li.dataset.personId;if(!nodes.has(id))continue;const b=button('Show','atlas-show');b.setAttribute('aria-label',`Show ${name(personBy.get(id))} in the atlas`);b.addEventListener('click',()=>{select(id,{centre:true,focus:true});section.scrollIntoView?.({block:'start'});});const first=li.querySelector(':scope > ul');li.insertBefore(b,first);li.insertBefore(document.createTextNode(' '),b);added.push(b);}
 // Search within the tree: matches stay bright on the drawing and the first eight are listed to choose from.
 const searchText=new Map(all.map(n=>[n.id,h.fold([...(n.p.names||[]).map(x=>x.value),n.id,n.p.external_id||''].join(' '))]));
 function find(){const words=h.fold(search.value).trim().split(/\s+/).filter(Boolean);if(!words.length){matches=null;resultList.replaceChildren();resultStatus.textContent='';results.hidden=true;schedule();return;}
  const found=all.filter(n=>words.every(w=>searchText.get(n.id).includes(w))).sort((a,b)=>name(a.p).localeCompare(name(b.p)));matches=new Set(found.map(n=>n.id));results.hidden=false;
  resultStatus.textContent=found.length?`${h.plural(found.length,'person')} match${found.length===1?'es':''}${found.length>8?'; the first 8 are listed':''}. Matches stay bright in the drawing.`:'No public person in the tree matches.';
  resultList.replaceChildren(...found.slice(0,8).map(n=>{const li=el('li'),b=button(name(n.p),'atlas-result');const span=h.lifespan(n.p);if(span)b.append(el('span',` ${span}`,'meta'));b.addEventListener('click',()=>select(n.id,{centre:true,focus:true}));li.append(b);return li;}));schedule();}
 search.addEventListener('input',find);search.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();const first=resultList.querySelector('button');first?.click();}else if(e.key==='Escape'&&search.value){e.preventDefault();search.value='';find();}});
 results.hidden=true;

 // The first drawing: the person in the box or the address is selected and brought into view.
 positions();const asked=menu?.value&&nodes.has(menu.value)?menu.value:null;
 if(asked&&asked!==state.selected)select(asked,{centre:true});else if(asked)fill(nodes.get(asked));else{state.selected=null;}
 sync();changed();
 return {zoom:f=>zoom(f),fit,dispose(){dead=true;stopPlay();if(frame)cancelAnimationFrame(frame);observer?.disconnect();added.forEach(b=>{b.previousSibling?.remove();b.remove();});if(families)families.hidden=false;}};
};
})();
