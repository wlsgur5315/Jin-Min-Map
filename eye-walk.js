/* Eye-level site walk. Local scene only: never mutates GIS or user geometry. */
(function(root){
 'use strict';
 function segmentDistance(x,z,a,b){const dx=b[0]-a[0],dz=b[1]-a[1],d=dx*dx+dz*dz,t=d?Math.max(0,Math.min(1,((x-a[0])*dx+(z-a[1])*dz)/d)):0;return Math.hypot(x-a[0]-t*dx,z-a[1]-t*dz)}
 function inRing(x,z,ring){let inside=false;for(let i=0,j=ring.length-1;i<ring.length;j=i++){const a=ring[i],b=ring[j];if((a[1]>z)!==(b[1]>z)&&x<(b[0]-a[0])*(z-a[1])/(b[1]-a[1])+a[0])inside=!inside}return inside}
 function inPolygon(x,z,rings){return inRing(x,z,rings[0])&&!rings.slice(1).some(r=>inRing(x,z,r))}
 function blocked(x,z,entries,radius=.28){
  for(const e of entries){const b=e.box;if(x<b[0]-radius||z<b[1]-radius||x>b[2]+radius||z>b[3]+radius)continue;
   for(const rings of e.polygons){if(inPolygon(x,z,rings))return true;for(const ring of rings)for(let i=1;i<ring.length;i++)if(segmentDistance(x,z,ring[i-1],ring[i])<radius)return true}
  }return false;
 }
 function sampleGrid(grid,x,z){
  const u=(x+grid.radius)/grid.step,v=(z+grid.radius)/grid.step,i=Math.floor(u),j=Math.floor(v),n=grid.n;
  if(i<0||j<0||i>=n-1||j>=n-1)return null;
  const a=grid.values[j*n+i],b=grid.values[j*n+i+1],c=grid.values[(j+1)*n+i],d=grid.values[(j+1)*n+i+1];
  if(![a,b,c,d].every(Number.isFinite))return null;
  const fx=u-i,fz=v-j;return a*(1-fx)*(1-fz)+b*fx*(1-fz)+c*(1-fx)*fz+d*fx*fz;
 }
 function fillTerrainGaps(grid,fallbackElevation,maxRadius=4,minCoverage=.8){
  const values=grid.values,original=values.slice(),n=grid.n,total=values.length,valid=original.reduce((count,v)=>count+Number(Number.isFinite(v)),0),coverage=valid/total;
  if(!Number.isFinite(fallbackElevation)||coverage<minCoverage)return null;
  let filled=0,flatFallback=0;
  for(let index=0;index<total;index++){
   if(Number.isFinite(original[index]))continue;
   const x=index%n,y=Math.floor(index/n);let samples=[];
   for(let r=1;r<=maxRadius&&!samples.length;r++){
    for(let dy=-r;dy<=r;dy++)for(let dx=-r;dx<=r;dx++){
     if(Math.max(Math.abs(dx),Math.abs(dy))!==r)continue;
     const sx=x+dx,sy=y+dy;if(sx<0||sy<0||sx>=n||sy>=n)continue;
     const value=original[sy*n+sx];if(Number.isFinite(value)){const d2=dx*dx+dy*dy;samples.push([value,1/d2])}
    }
   }
   if(samples.length){const weight=samples.reduce((sum,item)=>sum+item[1],0);values[index]=samples.reduce((sum,item)=>sum+item[0]*item[1],0)/weight}
   else{values[index]=fallbackElevation;flatFallback++}
   filled++;
  }
  return{coverage,filled,flatFallback};
 }
 function footprintGroundMax(grid,polygons){
  let maximum=-Infinity;
  const include=(x,z)=>{const y=sampleGrid(grid,x,z);if(Number.isFinite(y))maximum=Math.max(maximum,y)};
  for(const rings of polygons){
   for(const ring of rings)for(let i=0;i<ring.length;i++){
    const a=ring[i],b=ring[(i+1)%ring.length],length=Math.hypot(b[0]-a[0],b[1]-a[1]),steps=Math.max(1,Math.ceil(length/Math.max(.5,grid.step*.5)));
    for(let k=0;k<=steps;k++){const t=k/steps;include(a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t)}
   }
   const points=rings[0],minX=Math.min(...points.map(p=>p[0])),maxX=Math.max(...points.map(p=>p[0])),minZ=Math.min(...points.map(p=>p[1])),maxZ=Math.max(...points.map(p=>p[1]));
   const i0=Math.max(0,Math.ceil((minX+grid.radius)/grid.step)),i1=Math.min(grid.n-1,Math.floor((maxX+grid.radius)/grid.step)),j0=Math.max(0,Math.ceil((minZ+grid.radius)/grid.step)),j1=Math.min(grid.n-1,Math.floor((maxZ+grid.radius)/grid.step));
   for(let j=j0;j<=j1;j++)for(let i=i0;i<=i1;i++){const x=-grid.radius+i*grid.step,z=-grid.radius+j*grid.step;if(inPolygon(x,z,rings)){const y=grid.values[j*grid.n+i];if(Number.isFinite(y))maximum=Math.max(maximum,y)}}
  }
  return Number.isFinite(maximum)?maximum:null;
 }
 function move(position,dx,dz,grid,entries){
  let {x,z}=position;const n=Math.max(1,Math.ceil(Math.hypot(dx,dz)/.16)),sx=dx/n,sz=dz/n;
  const valid=(a,b)=>{const before=sampleGrid(grid,x,z),after=sampleGrid(grid,a,b);return after!==null&&before!==null&&Math.abs(after-before)<.55&&!blocked(a,b,entries)};
  for(let i=0;i<n;i++){if(valid(x+sx,z+sz)){x+=sx;z+=sz}else if(sx&&valid(x+sx,z))x+=sx;else if(sz&&valid(x,z+sz))z+=sz}
  return {x,z};
 }
 const math={segmentDistance,inRing,inPolygon,blocked,sampleGrid,fillTerrainGaps,footprintGroundMax,move};
 if(typeof module!=='undefined'&&module.exports)module.exports=math;
 if(!root.document)return;
 root.EYE_WALK_MATH=math;
 const $=id=>document.getElementById(id),API=root.EYE_WALK={active:false,picking:false,setup,sync,pick,cancelPick};
 let start=null,marker=null,state=null,busy=false,token=0,scope='',records=[],settings={eye:1.6,speed:1.5,sensitivity:.0022};
 try{const saved=JSON.parse(localStorage.getItem('jinmin_eye_walk_settings')||'null');if(saved){if(saved.eye>=.8&&saved.eye<=2.2)settings.eye=Number(saved.eye);if([.8,1.5,2.5].includes(saved.speed))settings.speed=saved.speed;if(saved.sensitivity>=.0008&&saved.sensitivity<=.004)settings.sensitivity=saved.sensitivity}
  records=JSON.parse(localStorage.getItem('jinmin_eye_walk_records')||'[]');if(!Array.isArray(records))records=[];records=records.filter(r=>r&&Number.isFinite(r.distance)&&r.distance>0&&r.a?.length===3&&r.b?.length===3&&[...r.a,...r.b].every(Number.isFinite)).slice(-50);
 }catch{records=[]}
 const node=(tag,parent,text,cls)=>{const n=document.createElement(tag);if(text)n.textContent=text;if(cls)n.className=cls;if(parent)parent.appendChild(n);return n};
 const button=(parent,text,handler,cls)=>{const b=node('button',parent,text,cls);b.type='button';b.onclick=handler;return b};
 function status(text){$('eyeWalkStatus').textContent=text}
 function saveSettings(){try{localStorage.setItem('jinmin_eye_walk_settings',JSON.stringify(settings))}catch{}syncSettings()}
 function syncSettings(){for(const el of document.querySelectorAll('[data-ew-setting]'))el.value=settings[el.dataset.ewSetting];if($('eyeWalkEyeValue'))$('eyeWalkEyeValue').textContent=settings.eye.toFixed(1)+'m';if(state){state.dirty=true;state.keys.clear()}}
 function settingsUI(host){
  for(const [key,title,options] of [['eye','눈높이',[[1.2,'1.2m'],[1.6,'1.6m'],[1.8,'1.8m']]],['speed','이동 속도',[[.8,'천천히'],[1.5,'보통'],[2.5,'빠르게']]],['sensitivity','마우스 감도',[[.001,'낮음'],[.0022,'보통'],[.0035,'높음']]]]){
   const label=node('label',host,title,'ew-field'),select=node('select',label);select.dataset.ewSetting=key;select.setAttribute('aria-label',title);
   for(const [value,text] of options){const o=node('option',select,text);o.value=value}select.value=settings[key];select.onchange=()=>{settings[key]=Number(select.value);saveSettings()};
  }
  const help=node('div',host,'','ew-help');for(const [key,text] of [['마우스','이동만으로 시선 회전'],['WASD','앞뒤·좌우 이동'],['Tab','회전·이동 정지 / 커서로 기능 선택'],['Tab 다시','둘러보기 복귀 / 커서 숨김'],['E','조준한 벽면의 정면 거리 측정'],['Esc','커서 해제 · 다시 누르면 지도 복귀'],['터치','이동 패드 · 화면 드래그 · 기능 버튼']]){node('b',help,key);node('span',help,text)}
 }
 function recordUI(host){host.classList.add('ew-records');host.dataset.ewRecords='true';renderRecords()}
 function renderRecords(){for(const host of document.querySelectorAll('[data-ew-records]')){host.replaceChildren();if(!records.length){node('p',host,'고정한 측정 결과가 없습니다.','ew-muted');continue}
   for(const record of records.slice().reverse()){const row=node('div',host,'','ew-record');node('b',row,record.distance.toFixed(2)+'m · 정면 이격');node('span',row,record.from+' → '+record.to,'ew-muted');const actions=node('div',row,'','ew-row');if(API.active)button(actions,'측정선 보기',()=>showRecord(record));button(actions,'삭제',()=>{records=records.filter(r=>r!==record);persistRecords();renderRecords()})}
  }}
 function persistRecords(){try{localStorage.setItem('jinmin_eye_walk_records',JSON.stringify(records))}catch{}}
 function setup(){
  if(typeof SCREEN_UI==='undefined')return;
  const nav=$('screenMainNav'),b=screenButton('눈높이 보기',nav,()=>screenChoose('walk','start'));b.dataset.screenMain='walk';
  const page=screenPage('walk-start');node('h3',page,'어디에서 걸어볼까요?');node('p',page,'도로 또는 건물 바깥의 지점을 선택하세요.','hint');
  const location=node('div',page,'시작 위치 미선택','ew-location');location.id='eyeWalkLocation';button(page,'지도에서 위치 선택',beginPick).id='eyeWalkPick';
  const row=node('div',page,'','ew-row');node('span',row,'눈높이','hint');node('b',row,settings.eye.toFixed(1)+'m').id='eyeWalkEyeValue';
  const s=node('p',page,'시작 위치를 선택하면 걷기를 시작할 수 있습니다.','ew-muted');s.id='eyeWalkStatus';s.setAttribute('role','status');s.setAttribute('aria-live','polite');
  const go=button(page,'걷기 시작',open,'primary');go.id='eyeWalkStart';go.disabled=true;
  node('p',page,'현재 로드된 주변 건물·DEM 지형과 배경지도를 사용합니다.','hint');
  node('h3',screenPage('walk-records'),'측정 기록');recordUI(screenPage('walk-records'));
  node('h3',screenPage('walk-settings'),'조작 설정');settingsUI(screenPage('walk-settings'));
  buildModal();document.addEventListener('keydown',keydown,true);document.addEventListener('keyup',e=>state?.keys.delete(e.code),true);
  document.addEventListener('pointerlockchange',()=>{const s=state;if(!s){if(document.pointerLockElement===$('eyeWalkCanvas'))document.exitPointerLock?.();return}if(document.pointerLockElement===s.renderer.domElement){if(!API.active){document.exitPointerLock?.();return}s.ignoreMouseUntil=performance.now()+100;setMenu(false)}else if(API.active)setMenu(true)});
  document.addEventListener('pointerlockerror',()=>{if(state){setMenu(true);hud('마우스 고정을 시작하지 못했습니다. 둘러보기 버튼을 다시 눌러 주세요.')}});
  document.addEventListener('mousemove',e=>{const s=state;if(!API.active||!s||s.menu||performance.now()<(s.ignoreMouseUntil||0))return;const locked=document.pointerLockElement===s.renderer.domElement;if(!locked&&s.renderer.domElement.requestPointerLock)return;if(!locked&&e.target!==s.renderer.domElement)return;look(e.movementX,e.movementY)});
  window.addEventListener('blur',pause);document.addEventListener('visibilitychange',()=>{if(document.hidden)pause()});window.addEventListener('pagehide',close);
  map.on('click',e=>{if(API.picking)pick([e.lngLat.lng,e.lngLat.lat])});
  window.addEventListener('resize',resize);if(typeof ResizeObserver!=='undefined')new ResizeObserver(resize).observe($('eyeWalkHost'));sync();screenWorkspaceSync();
 }
 function sync(){
  if(!$('eyeWalkStart'))return;
  const next=String(selectedId||'')+'|'+String(EDIT_PARCEL?.properties?.pnu||'');if(scope&&scope!==next&&!API.active){start=null;marker?.remove();marker=null}scope=next;
  if(typeof SCREEN_UI!=='undefined'&&SCREEN_UI.main!=='walk')cancelPick();
  $('eyeWalkStart').disabled=!start||busy;$('eyeWalkStart').textContent=busy?'장면 준비 중…':'걷기 시작';$('eyeWalkPick').textContent=API.picking?'위치 선택 취소':start?'시작 위치 다시 선택':'지도에서 위치 선택';
  $('eyeWalkLocation').textContent=start?'시작 위치 · '+start[1].toFixed(6)+', '+start[0].toFixed(6):'시작 위치 미선택';
 }
 function beginPick(){
  if(API.picking){cancelPick();return}
  if(!map.isStyleLoaded()){status('지도가 준비된 뒤 다시 선택하세요.');return}
  if(!buildingSolarFeatures().length&&!editCustomModels().length){status('먼저 작업할 지역의 건물이나 필지를 선택해 주세요.');return}
  API.picking=true;map.getCanvas().style.cursor='crosshair';status('지도에서 도로 또는 빈 공간을 누르세요.');message('눈높이 시작 위치 선택 중 · 건물 바깥을 누르세요.');sync();
 }
 function cancelPick(){if(!API.picking)return;API.picking=false;map.getCanvas().style.cursor='';sync()}
 function pick(point){
  const features=[...buildingSolarFeatures().filter(f=>!buildingIsHidden(f)),...editCustomModels()];
  if(features.some(f=>{try{return turf.booleanPointInPolygon(turf.point(point),f)}catch{return false}})){status('건물 내부입니다. 도로 또는 건물 바깥을 선택하세요.');return false}
  start=point.slice();API.picking=false;map.getCanvas().style.cursor='';marker?.remove();marker=new maplibregl.Marker({color:'#22d3ee'}).setLngLat(start).addTo(map);
  status('위치 선택 완료 · 걷기 시작을 누르세요.');sync();return true;
 }
 function buildModal(){
  const modal=node('div',document.body,'','ew-modal');modal.id='eyeWalkModal';modal.hidden=true;modal.setAttribute('role','dialog');modal.setAttribute('aria-modal','true');modal.setAttribute('aria-labelledby','eyeWalkTitle');
  const head=node('header',modal,'','ew-header');node('b',head,'눈높이로 걷기').id='eyeWalkTitle';node('span',head,'장면 준비 중…','ew-muted').id='eyeWalkMode';button(head,'지도로 복귀',close).id='eyeWalkExit';
  const body=node('div',modal,'','ew-body');body.id='eyeWalkBody';const host=node('div',body,'','ew-canvas-host');host.id='eyeWalkHost';node('div',host,'장면 준비 중…','ew-hud').id='eyeWalkHud';
  const cross=node('div',host,'＋','ew-crosshair');cross.id='eyeWalkCrosshair';cross.setAttribute('aria-hidden','true');
  const mapCanvas=node('canvas',host,'','ew-mini');mapCanvas.id='eyeWalkMini';mapCanvas.width=220;mapCanvas.height=220;mapCanvas.setAttribute('aria-label','건물 배치와 현재 위치');
  const pad=node('div',host,'','ew-pad');pad.id='eyeWalkPad';pad.setAttribute('aria-label','이동');
  for(const [key,label,cls] of [['KeyW','↑','ew-up'],['KeyA','←','ew-left'],['KeyS','↓','ew-down'],['KeyD','→','ew-right']]){
   const b=button(pad,label,null,cls);b.setAttribute('aria-label',{'KeyW':'앞으로','KeyA':'왼쪽으로','KeyS':'뒤로','KeyD':'오른쪽으로'}[key]);
   b.onpointerdown=e=>{e.preventDefault();if(!state||state.menu)return;b.setPointerCapture(e.pointerId);state.keys.add(key)};for(const event of ['pointerup','pointercancel','lostpointercapture'])b.addEventListener(event,()=>state?.keys.delete(key));
  }
  const actions=node('div',host,'','ew-scene-actions');button(actions,'E · 거리 측정',measure,'primary').id='eyeWalkMeasure';button(actions,'Tab · 기능 선택',()=>setMenu(true)).id='eyeWalkMenuButton';
  const result=node('div',host,'','ew-result');result.id='eyeWalkResult';result.hidden=true;node('b',result,'').id='eyeWalkDistance';node('span',result,'정면 이격거리 · 모델 형상 기준');const rr=node('div',result,'','ew-row');button(rr,'측정 고정',pinMeasurement);button(rr,'지우기',clearMeasurement);
  const menu=node('aside',body,'','ew-menu');menu.id='eyeWalkMenu';
  const resume=button(menu,'Tab · 둘러보기',resumeLook,'primary');resume.id='eyeWalkResume';
  const tabs=node('nav',menu,'','ew-tabs');for(const [key,label] of [['walk','걷기'],['records','기록'],['settings','설정']]){const b=button(tabs,label,()=>menuPage(key));b.dataset.ewMenu=key}
  const walk=node('section',menu);walk.dataset.ewPane='walk';node('h3',walk,'기능 선택 모드');node('p',walk,'시선 회전과 이동이 멈췄습니다. 마우스로 기능을 선택하세요.','ew-muted');button(walk,'현재 벽면 거리 측정',measure);button(walk,'시작 위치로 돌아가기',()=>{if(state){state.x=0;state.z=0;state.dirty=true;clearMeasurement();hud('시작 위치로 돌아왔습니다.')}});
  const r=node('section',menu);r.dataset.ewPane='records';recordUI(r);const st=node('section',menu);st.dataset.ewPane='settings';settingsUI(st);menuPage('walk');
  const footer=node('footer',modal,'','ew-footer');node('span',footer,'','ew-muted').id='eyeWalkSceneInfo';node('span',footer,'WASD 이동 · 마우스 회전 · Tab 기능 선택 · E 측정');
 }
 function menuPage(key){for(const b of document.querySelectorAll('[data-ew-menu]'))b.setAttribute('aria-pressed',String(b.dataset.ewMenu===key));for(const p of document.querySelectorAll('[data-ew-pane]'))p.hidden=p.dataset.ewPane!==key}
 function hud(text){$('eyeWalkHud').textContent=text}
 function setMenu(open){
  const s=state;if(!s)return;s.menu=open;s.keys.clear();s.touch=null;s.dirty=true;
  if(open&&document.pointerLockElement===s.renderer.domElement)document.exitPointerLock?.();
  $('eyeWalkMenu').hidden=!open;$('eyeWalkCrosshair').hidden=open;$('eyeWalkPad').hidden=open;$('eyeWalkBody').classList.toggle('ew-choosing',open);
  s.renderer.domElement.style.cursor=open?'auto':'none';
  $('eyeWalkMode').textContent=open?'기능 선택 · 회전 정지':'둘러보기 · 눈높이 '+settings.eye.toFixed(1)+'m';$('eyeWalkMenuButton').textContent=open?'기능 선택 중':'Tab · 기능 선택';
  if(open){hud('회전 정지 · 커서로 기능 선택 · Tab으로 둘러보기 복귀');$('eyeWalkResume').focus()}resize();
 }
 function resumeLook(event){
  const s=state;if(!s)return;
  if(event?.pointerType==='touch'||navigator.maxTouchPoints>0&&!matchMedia('(any-pointer: fine)').matches){setMenu(false);return}
  if(s.renderer.domElement.requestPointerLock){try{const promise=s.renderer.domElement.requestPointerLock();promise?.catch(()=>{if(state===s){setMenu(true);hud('둘러보기 버튼을 클릭해 마우스 고정을 다시 시작하세요.')}})}catch{setMenu(true);hud('마우스 고정을 시작할 수 없습니다. 터치 드래그를 사용하세요.')}}
  else setMenu(false);
 }
 function pause(){if(API.active&&state)setMenu(true)}
 function look(dx,dy){const s=state;if(!s||s.menu)return;s.yaw-=dx*settings.sensitivity;s.pitch=Math.max(-1.3,Math.min(1.3,s.pitch-dy*settings.sensitivity));s.dirty=true}
 function keydown(e){
  if(!API.active)return;if(e.code==='Escape'){e.preventDefault();e.stopImmediatePropagation();if(state&&!state.menu)setMenu(true);else close();return}
  if(!state||e.ctrlKey||e.metaKey||e.altKey||e.isComposing)return;
  if(e.code==='Tab'){e.preventDefault();e.stopImmediatePropagation();if(e.repeat)return;state.menu?resumeLook():setMenu(true);return}
  if(['KeyW','KeyA','KeyS','KeyD','KeyE','ShiftLeft','ShiftRight'].includes(e.code)){
   if(state.menu)return;e.preventDefault();e.stopImmediatePropagation();if(e.code==='KeyE'){if(!e.repeat)measure()}else state.keys.add(e.code);
  }
 }
 function captureMap(){return new Promise(resolve=>{let done=false;const finish=()=>{if(done)return;done=true;clearTimeout(timeout);map.off('render',onRender);resolve(null)},onRender=()=>{if(done)return;try{const source=map.getCanvas(),c=document.createElement('canvas'),ratio=Math.min(1,2048/source.width);c.width=Math.round(source.width*ratio);c.height=Math.round(source.height*ratio);c.getContext('2d').drawImage(source,0,0,c.width,c.height);done=true;clearTimeout(timeout);map.off('render',onRender);resolve(c)}catch{finish()}};const timeout=setTimeout(finish,1800);map.on('render',onRender);map.triggerRepaint()})}
 function settled(){return new Promise(resolve=>{let done=false;const end=()=>{if(done)return;done=true;clearTimeout(timeout);map.off('idle',end);resolve()};const timeout=setTimeout(end,2500);map.on('idle',end);map.triggerRepaint()})}
 function mapSnapshot(){const c=map.getCenter();return {center:[c.lng,c.lat],zoom:map.getZoom(),pitch:map.getPitch(),bearing:map.getBearing(),padding:{...map.getPadding()}}}
 async function open(){
  if(busy||!start)return;cancelPick();busy=true;API.active=true;const run=++token;sync();$('eyeWalkModal').hidden=false;hud('지도와 지형을 준비하는 중…');$('eyeWalkMenu').hidden=true;$('eyeWalkCrosshair').hidden=true;
  const original=mapSnapshot(),hidden=new Map();let renderer=null,threeScene=null;
  try{
   solarPlaybackStop();map.stop();map.jumpTo({center:start,zoom:17,pitch:0,bearing:0,padding:{top:0,bottom:0,left:0,right:0}});
   const THREE=await import('https://cdn.jsdelivr.net/npm/three@0.169.0/build/three.module.js');await settled();if(run!==token)return;
   const center=start.slice(),merc=maplibregl.MercatorCoordinate.fromLngLat(center,0),scale=merc.meterInMercatorCoordinateUnits();
   const local=ll=>{const m=maplibregl.MercatorCoordinate.fromLngLat(ll,0);return [(m.x-merc.x)/scale,(m.y-merc.y)/scale]},geo=(x,z)=>{const ll=new maplibregl.MercatorCoordinate(merc.x+x*scale,merc.y+z*scale,0).toLngLat();return [ll.lng,ll.lat]};
   const datum=solarTerrainHeight(center);if(datum===null)throw Error('선택 위치의 지표면 높이를 아직 읽지 못했습니다. 지도를 확대하고 지형이 로드된 뒤 다시 시작하세요.');
   const c=map.getCanvas(),topLeft=local(map.unproject([0,0]).toArray()),bottomRight=local(map.unproject([c.clientWidth,c.clientHeight]).toArray()),radius=Math.min(160,-topLeft[0]-3,-topLeft[1]-3,bottomRight[0]-3,bottomRight[1]-3);
   if(radius<20)throw Error('주변 지도를 충분히 확보하지 못했습니다. 창 크기를 늘린 뒤 다시 시작하세요.');
   const n=65,grid={n,radius,step:2*radius/(n-1),values:[]};for(let j=0;j<n;j++)for(let i=0;i<n;i++)grid.values.push(solarTerrainHeight(geo(-radius+i*grid.step,-radius+j*grid.step)));
   const gapStats=fillTerrainGaps(grid,datum);if(!gapStats)throw Error('지형 표고 자료에 빈 구역이 많아 눈높이 장면을 만들 수 없습니다. 지형 타일이 로드된 뒤 다시 시작하세요.');
   const candidates=collectBuildings(center,local,radius),entries=[];let skipped=0,skippedOutside=0;
   for(const item of candidates){const p=item.f.properties||{};let at;try{at=turf.pointOnFeature(item.f).geometry.coordinates}catch{at=featureGroundAnchor(item.f)||center}const anchorLocal=local(at),elevation=sampleGrid(grid,anchorLocal[0],anchorLocal[1]);if(elevation===null){skipped++;continue}
    const storedFoundation=item.custom?editModelElevation(item.f).render_base:Math.max(0,Number(p.render_base)||0),polygons=(item.f.geometry.type==='Polygon'?[item.f.geometry.coordinates]:item.f.geometry.coordinates).map(poly=>poly.map(r=>r.map(local)));
    const flat=polygons.flat(2),box=[Math.min(...flat.map(p=>p[0])),Math.min(...flat.map(p=>p[1])),Math.max(...flat.map(p=>p[0])),Math.max(...flat.map(p=>p[1]))];
    if(box[0]<-radius||box[1]<-radius||box[2]>radius||box[3]>radius){skippedOutside++;continue}
    const footprintMax=footprintGroundMax(grid,polygons);if(footprintMax===null){skipped++;continue}
    const terrainFoundation=Math.max(0,footprintMax-elevation+.25),extra=Math.max(storedFoundation,terrainFoundation);
    entries.push({...item,polygons,box,base:elevation-datum+extra,foundation:extra,terrainFoundation,meshes:[]});
   }
   if(!entries.length)throw Error('주변에 표시할 건물이 없습니다. 건물 자료를 불러온 지역에서 시작하세요.');
   if(blocked(0,0,entries))throw Error('시작 위치가 건물 벽에 너무 가깝습니다. 도로나 넓은 빈 공간을 선택하세요.');
   for(const id of ['buildings-3d','buildings-foundation','smart-osm-3d','smart-osm-foundation','buildings-2d','smart-osm-2d','edit-custom-model-3d','edit-custom-model-foundation','edit-custom-model-outline','selected-building-fill','selected-building-line','solar-three-map-custom'])if(map.getLayer(id)){hidden.set(id,map.getLayoutProperty(id,'visibility'));map.setLayoutProperty(id,'visibility','none')}
   const image=await captureMap();if(run!==token)return;if(!image)throw Error('주변 지도를 캡처하지 못해 도로를 표시할 수 없습니다. 지도 타일이 모두 로드된 뒤 다시 시작하세요.');
   hud('실제 건물 형상을 구성하는 중…');
   threeScene=new THREE.Scene();threeScene.background=new THREE.Color('#bfd5e4');threeScene.fog=new THREE.Fog('#bfd5e4',radius*.8,radius*2);
   threeScene.add(new THREE.HemisphereLight('#f1f7ff','#64756a',2.2));const sun=new THREE.DirectionalLight('#fff3dd',2.3);sun.position.set(-50,100,30);threeScene.add(sun);
   renderer=new THREE.WebGLRenderer({antialias:true,alpha:false});renderer.setPixelRatio(Math.min(1.5,devicePixelRatio||1));renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.domElement.id='eyeWalkCanvas';renderer.domElement.setAttribute('aria-label','눈높이 걷기 장면');$('eyeWalkHost').prepend(renderer.domElement);
   const camera=new THREE.PerspectiveCamera(75,1,.08,radius*3),geometries=[],materials=[];
   const terrainGeometry=makeTerrain(THREE,grid,datum,topLeft,bottomRight);geometries.push(terrainGeometry);let texture=null;if(image){texture=new THREE.CanvasTexture(image);texture.colorSpace=THREE.SRGBColorSpace;texture.anisotropy=Math.min(4,renderer.capabilities.getMaxAnisotropy())}
   const groundMaterial=new THREE.MeshStandardMaterial({map:texture,color:texture?'#ffffff':'#819589',roughness:1,side:THREE.DoubleSide});materials.push(groundMaterial);const terrain=new THREE.Mesh(terrainGeometry,groundMaterial);threeScene.add(terrain);
   const existingMat=new THREE.MeshStandardMaterial({color:'#c9d3db',roughness:.95,side:THREE.DoubleSide}),customMat=new THREE.MeshStandardMaterial({color:'#55a7d5',roughness:.9,side:THREE.DoubleSide}),foundationMat=new THREE.MeshStandardMaterial({color:'#475569',roughness:1,side:THREE.DoubleSide}),customFoundationMat=new THREE.MeshStandardMaterial({color:'#9a5c32',roughness:1,side:THREE.DoubleSide});materials.push(existingMat,customMat,foundationMat,customFoundationMat);const meshes=[];
   for(const entry of entries)for(const rings of entry.polygons){const shape=new THREE.Shape();rings[0].forEach(([x,z],i)=>i?shape.lineTo(x,-z):shape.moveTo(x,-z));for(const ring of rings.slice(1)){const hole=new THREE.Path();ring.forEach(([x,z],i)=>i?hole.lineTo(x,-z):hole.moveTo(x,-z));shape.holes.push(hole)}
    const g=new THREE.ExtrudeGeometry(shape,{depth:entry.h,bevelEnabled:false,steps:1});g.rotateX(-Math.PI/2);geometries.push(g);const mesh=new THREE.Mesh(g,entry.custom?customMat:existingMat);mesh.position.y=entry.base;mesh.userData.entry=entry;entry.meshes.push(mesh);meshes.push(mesh);threeScene.add(mesh);
    if(entry.foundation>.01){const fg=new THREE.ExtrudeGeometry(shape,{depth:entry.foundation,bevelEnabled:false,steps:1});fg.rotateX(-Math.PI/2);geometries.push(fg);const foundation=new THREE.Mesh(fg,entry.custom?customFoundationMat:foundationMat);foundation.position.y=entry.base-entry.foundation;foundation.userData.entry=entry;entry.meshes.push(foundation);meshes.push(foundation);threeScene.add(foundation)}
   }
   const highlight=new THREE.LineLoop(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:'#22d3ee',depthTest:false}));highlight.renderOrder=8;highlight.visible=false;threeScene.add(highlight);
   const measurementGroup=new THREE.Group();threeScene.add(measurementGroup);
   const selected=solarAnalysisCenter(),aim=selected?local(selected):[0,-15],bearing=map.getBearing()*Math.PI/180,yaw=Math.hypot(...aim)>2?Math.atan2(-aim[0],-aim[1]):bearing;
   state={THREE,scene:threeScene,renderer,camera,grid,datum,local,geo,entries,meshes,terrain,geometries,materials,texture,highlight,measurementGroup,x:0,z:0,yaw,pitch:0,keys:new Set(),menu:true,target:null,pending:null,frame:0,last:0,dirty:true,miniAt:0,touch:null,ray:new THREE.Raycaster(),lastTarget:''};
   threeScene.updateMatrixWorld(true);setupCanvasInput(renderer.domElement);$('eyeWalkSceneInfo').textContent='주변 '+entries.length+'동 · 반경 '+Math.floor(radius)+'m · '+(image?'배경지도·DEM':'DEM 기준면')+(gapStats.filled?' · 지형 결측 '+gapStats.filled+'곳 보간':'')+(gapStats.flatFallback?' · 저신뢰 평면 보정 '+gapStats.flatFallback+'곳':'')+(skippedOutside?' · 지형 범위 밖 '+skippedOutside+'동 제외':'')+(skipped?' · 고도 미확보 '+skipped+'동 제외':'');
   resize();setMenu(true);renderRecords();state.frame=requestAnimationFrame(tick);status('눈높이 장면 준비 완료 · 마우스 또는 터치로 둘러보세요.');
  }catch(error){if(run===token){console.warn('Eye walk:',error);if(!state){renderer?.dispose();if(renderer?.domElement)renderer.domElement.remove();if(threeScene)threeScene.traverse(o=>{o.geometry?.dispose();if(o.material)for(const m of Array.isArray(o.material)?o.material:[o.material])m.dispose()})}close();status(error.message||'눈높이 장면을 만들지 못했습니다.')}}
  finally{
   for(const [id,visibility] of hidden)if(map.getLayer(id))map.setLayoutProperty(id,'visibility',visibility||'visible');
   map.jumpTo(original);busy=false;sync();
  }
 }
 function collectBuildings(center,local,radius){
  const seen=new Set(),out=[];const add=(f,custom)=>{try{if(!['Polygon','MultiPolygon'].includes(f.geometry?.type)||f.properties?.facility||f.properties?.suppress_render||f.properties?.hidden||!custom&&buildingIsHidden(f))return;const p=f.properties||{},h=custom?Number(p.model_height):buildingHeight({f});if(!(h>0&&h<=600))return;const distance=turf.distance(center,turf.centroid(f),{units:'meters'});if(distance>radius*Math.SQRT2+10)return;const key=(custom?'custom:':'gis:')+JSON.stringify(f.geometry);if(seen.has(key))return;seen.add(key);out.push({f,custom,h,distance,name:custom?editModelLabel(f):[p.building_name||p.register_name,p.building_dong||p.register_dong].filter(Boolean).join(' · ')||'기존 건물'})}catch{}};
  for(const f of buildingSolarFeatures())add(f,false);for(const f of editCustomModels())add(f,true);out.sort((a,b)=>Number(b.custom)-Number(a.custom)||a.distance-b.distance);return out.slice(0,260);
 }
 function makeTerrain(T,grid,datum,a,b){
  const positions=[],uv=[],indices=[];for(let j=0;j<grid.n;j++)for(let i=0;i<grid.n;i++){const x=-grid.radius+i*grid.step,z=-grid.radius+j*grid.step,y=grid.values[j*grid.n+i];positions.push(x,Number.isFinite(y)?y-datum:0,z);uv.push((x-a[0])/(b[0]-a[0]),1-(z-a[1])/(b[1]-a[1]))}
  for(let j=0;j<grid.n-1;j++)for(let i=0;i<grid.n-1;i++){const k=j*grid.n+i,ids=[k,k+1,k+grid.n,k+grid.n+1];if(ids.every(v=>Number.isFinite(grid.values[v])))indices.push(k,k+grid.n,k+1,k+1,k+grid.n,k+grid.n+1)}
  const g=new T.BufferGeometry();g.setAttribute('position',new T.Float32BufferAttribute(positions,3));g.setAttribute('uv',new T.Float32BufferAttribute(uv,2));g.setIndex(indices);g.computeVertexNormals();return g;
 }
 function setupCanvasInput(canvas){
  canvas.addEventListener('click',e=>{if(e.pointerType!=='touch'&&state?.menu)resumeLook()});
  canvas.addEventListener('pointerdown',e=>{if(!state||state.menu||e.pointerType==='mouse')return;state.touch={id:e.pointerId,x:e.clientX,y:e.clientY};canvas.setPointerCapture(e.pointerId)});
  canvas.addEventListener('pointermove',e=>{const s=state,t=s?.touch;if(!t||s.menu||t.id!==e.pointerId)return;look((e.clientX-t.x)*1.6,(e.clientY-t.y)*1.6);t.x=e.clientX;t.y=e.clientY});
  for(const event of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(event,()=>{if(state)state.touch=null});
 }
 function resize(){const s=state;if(!s)return;const host=$('eyeWalkHost'),w=host.clientWidth,h=host.clientHeight;if(!w||!h)return;s.renderer.setSize(w,h,false);s.camera.aspect=w/h;s.camera.updateProjectionMatrix();s.dirty=true}
 function updateCamera(s){const ground=sampleGrid(s.grid,s.x,s.z);s.camera.position.set(s.x,(ground??s.datum)-s.datum+settings.eye,s.z);s.camera.rotation.order='YXZ';s.camera.rotation.set(s.pitch,s.yaw,0);s.camera.updateMatrixWorld()}
 function tick(now){
  const s=state;if(!API.active||!s)return;const dt=s.last?Math.min(.05,(now-s.last)/1000):0;s.last=now;
  if(!s.menu&&!document.hidden){let forward=Number(s.keys.has('KeyW'))-Number(s.keys.has('KeyS')),right=Number(s.keys.has('KeyD'))-Number(s.keys.has('KeyA'));const length=Math.hypot(forward,right);if(length){const speed=settings.speed*(s.keys.has('ShiftLeft')||s.keys.has('ShiftRight')?1.7:1),dx=(-Math.sin(s.yaw)*forward+Math.cos(s.yaw)*right)/length*speed*dt,dz=(-Math.cos(s.yaw)*forward-Math.sin(s.yaw)*right)/length*speed*dt,next=move(s,dx,dz,s.grid,s.entries);s.x=next.x;s.z=next.z;s.dirty=true}}
  if(s.dirty){updateCamera(s);updateTarget(s);s.renderer.render(s.scene,s.camera);s.dirty=false}
  if(now-s.miniAt>160){drawMini(s);s.miniAt=now}
  s.frame=requestAnimationFrame(tick);
 }
 function updateTarget(s){
  s.ray.setFromCamera(new s.THREE.Vector2(0,0),s.camera);s.ray.far=s.grid.radius*2;const hit=s.ray.intersectObjects(s.meshes,false)[0],terrainHit=s.ray.intersectObject(s.terrain,false)[0];
  s.target=null;s.highlight.visible=false;if(hit&&(!terrainHit||terrainHit.distance>hit.distance+.03)){
   const normal=hit.face.normal.clone().transformDirection(hit.object.matrixWorld);if(Math.abs(normal.y)<.25){if(normal.dot(s.camera.position.clone().sub(hit.point))<0)normal.negate();normal.y=0;normal.normalize();s.target={...hit,normal,entry:hit.object.userData.entry};highlightFace(s,s.target)}
  }
  $('eyeWalkMeasure').disabled=!s.target;
  if(!s.menu){const text=s.target?'조준한 벽면: '+s.target.entry.name+' · E 거리 측정':'벽면을 바라보면 E로 정면 간격을 측정합니다.';if(text!==s.lastTarget||!$('eyeWalkHud').textContent){hud(text);s.lastTarget=text}}
 }
 function highlightFace(s,hit){
  const entry=hit.entry,p=hit.point,n=hit.normal;let segment=null,best=Infinity;
  for(const poly of entry.polygons)for(const ring of poly)for(let i=1;i<ring.length;i++){const d=segmentDistance(p.x,p.z,ring[i-1],ring[i]);if(d<best){best=d;segment=[ring[i-1],ring[i]]}}
  if(!segment)return;const [a,b]=segment,y=entry.base-entry.foundation,top=entry.base+entry.h,points=[new s.THREE.Vector3(a[0],y,a[1]),new s.THREE.Vector3(b[0],y,b[1]),new s.THREE.Vector3(b[0],top,b[1]),new s.THREE.Vector3(a[0],top,a[1])];
  s.highlight.geometry.dispose();s.highlight.geometry=new s.THREE.BufferGeometry().setFromPoints(points);s.highlight.visible=true;
 }
 function measure(){
  const s=state;if(!s)return;updateCamera(s);updateTarget(s);const hit=s.target;if(!hit){hud('측정할 건물 벽면을 조준하세요. 지붕·지표면은 벽면 측정 대상이 아닙니다.');return}
  const origin=hit.point.clone().addScaledVector(hit.normal,.02),ray=new s.THREE.Raycaster(origin,hit.normal,.001,s.grid.radius*2),opposite=ray.intersectObjects(s.meshes,false)[0],terrain=ray.intersectObject(s.terrain,false)[0];
  if(!opposite){hud('같은 높이의 정면 방향에 측정 가능한 다른 건물이 없습니다.');return}
  if(opposite.object.userData.entry===hit.entry){hud('정면 방향이 같은 건물의 다른 벽면에 막혀 있습니다.');return}
  if(terrain&&terrain.distance<opposite.distance){hud('정면 방향이 지형에 가려 건물 사이 간격을 측정할 수 없습니다.');return}
  const distance=hit.point.distanceTo(opposite.point);if(distance<.05){hud('건물 면이 겹치거나 접해 있습니다. 간격을 확정할 수 없습니다.');return}
  s.pending={distance,a:[...s.geo(hit.point.x,hit.point.z),hit.point.y+s.datum],b:[...s.geo(opposite.point.x,opposite.point.z),opposite.point.y+s.datum],from:hit.entry.name,to:opposite.object.userData.entry.name,time:new Date().toISOString()};showMeasurement(s.pending);hud('정면 이격 '+distance.toFixed(2)+'m · 측정 고정을 누르면 기록에 저장됩니다.');
 }
 function showMeasurement(record){
  const s=state;if(!s)return;clearLines(s.measurementGroup);const T=s.THREE,a=s.local(record.a),b=s.local(record.b),points=[new T.Vector3(a[0],record.a[2]-s.datum,a[1]),new T.Vector3(b[0],record.b[2]-s.datum,b[1])],geometry=new T.BufferGeometry().setFromPoints(points),material=new T.LineBasicMaterial({color:'#22d3ee',depthTest:false});const line=new T.Line(geometry,material);line.renderOrder=9;s.measurementGroup.add(line);
  for(const point of points){const marker=new T.Mesh(new T.SphereGeometry(.12,8,6),new T.MeshBasicMaterial({color:'#fef08a',depthTest:false}));marker.position.copy(point);marker.renderOrder=10;s.measurementGroup.add(marker)}
  $('eyeWalkDistance').textContent=record.distance.toFixed(2)+'m';$('eyeWalkResult').hidden=false;s.pending=record;s.dirty=true;
 }
 function clearLines(group){for(const child of [...group.children]){group.remove(child);child.geometry?.dispose();child.material?.dispose()}}
 function clearMeasurement(){if(!state)return;clearLines(state.measurementGroup);state.pending=null;state.dirty=true;$('eyeWalkResult').hidden=true}
 function pinMeasurement(){const s=state;if(!s?.pending)return;const record=JSON.parse(JSON.stringify(s.pending));if(!records.some(r=>r.time===record.time)){records.push(record);records=records.slice(-50);persistRecords();renderRecords()}hud('측정 기록에 저장했습니다. Tab → 기록에서 확인하세요.')}
 function showRecord(record){if(!state)return;const p=state.local(record.a);if(Math.hypot(...p)>state.grid.radius*2){hud('현재 장면 범위 밖의 측정 기록입니다. 해당 위치에서 다시 시작하세요.');return}showMeasurement(record)}
 function drawMini(s){
  const c=$('eyeWalkMini'),g=c.getContext('2d'),n=c.width,scale=n/Math.min(100,s.grid.radius*2),pos=(x,z)=>[n/2+(x-s.x)*scale,n/2+(z-s.z)*scale];g.fillStyle='#142b3b';g.fillRect(0,0,n,n);g.lineWidth=1;
  for(const e of s.entries){g.beginPath();for(const poly of e.polygons)for(const ring of poly){ring.forEach(([x,z],i)=>i?g.lineTo(...pos(x,z)):g.moveTo(...pos(x,z)));g.closePath()}g.fillStyle=e.custom?'#55a7d5':'#71869a';g.fill('evenodd')}
  if(s.pending){const a=s.local(s.pending.a),b=s.local(s.pending.b);g.strokeStyle='#fde68a';g.lineWidth=2;g.beginPath();g.moveTo(...pos(...a));g.lineTo(...pos(...b));g.stroke()}
  const p=pos(s.x,s.z);g.strokeStyle='#67e8f9';g.lineWidth=2;g.beginPath();g.moveTo(...p);g.lineTo(p[0]-Math.sin(s.yaw)*16,p[1]-Math.cos(s.yaw)*16);g.stroke();g.beginPath();g.arc(...p,4,0,Math.PI*2);g.fillStyle='#f8fafc';g.fill();g.font='16px system-ui';g.fillText('N',8,20);
 }
 function close(){
  ++token;API.active=false;cancelPick();const s=state;state=null;
  if(document.pointerLockElement===$('eyeWalkCanvas'))document.exitPointerLock?.();
  if(s){cancelAnimationFrame(s.frame);s.keys.clear();s.renderer.domElement.remove();clearLines(s.measurementGroup);s.highlight.geometry.dispose();s.highlight.material.dispose();for(const g of s.geometries)g.dispose();for(const m of s.materials)m.dispose();s.texture?.dispose();s.renderer.dispose();s.renderer.forceContextLoss()}
  $('eyeWalkModal').hidden=true;$('eyeWalkResult').hidden=true;sync();if(typeof SCREEN_UI!=='undefined'&&SCREEN_UI.main==='walk')screenWorkspaceSync();$('eyeWalkStart')?.focus();
 }
 API.close=close;API.resume=resumeLook;API.measure=measure;API.pause=pause;API.start=open;
 setup();
})(typeof window==='undefined'?globalThis:window);
