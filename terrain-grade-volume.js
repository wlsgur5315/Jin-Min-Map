/* Parcel-clipped, absolute-elevation cut/fill preview. */
(function(){
'use strict';
const ID='terrain-grade-volume';
let cachedGrid=null,cachedParcel=null,terrain=[],layer=null;
function sample(g,x,y){
 const u=(x-g.w)/(g.e-g.w)*(g.gridN-1),v=(g.n-y)/(g.n-g.s)*(g.gridN-1),i=Math.max(0,Math.min(g.gridN-2,Math.floor(u))),j=Math.max(0,Math.min(g.gridN-2,Math.floor(v))),a=u-i,b=v-j;
 const z=[g.values[j*g.gridN+i],g.values[j*g.gridN+i+1],g.values[(j+1)*g.gridN+i],g.values[(j+1)*g.gridN+i+1]];
 return z.every(Number.isFinite)?z[0]*(1-a)*(1-b)+z[1]*a*(1-b)+z[2]*(1-a)*b+z[3]*a*b:null;
}
function prepare(g,parcel){
 if(cachedGrid===g&&cachedParcel===parcel)return;
 terrain=[];cachedGrid=g;cachedParcel=parcel;
 const N=g.gridN-1;
 for(let y=0;y<N;y++)for(let x=0;x<N;x++){
  const p=[[x,y],[x+1,y],[x+1,y+1],[x,y+1]].map(([i,j])=>[g.w+(g.e-g.w)*i/N,g.n-(g.n-g.s)*j/N]);
  for(const ids of [[0,1,2],[0,2,3]]){
   const t=ids.map(i=>p[i]);const clipped=turf.intersect(turf.featureCollection([parcel,turf.polygon([[...t,t[0]]])]));
   if(!clipped)continue;
   const polys=clipped.geometry.type==='Polygon'?[clipped.geometry.coordinates]:clipped.geometry.coordinates;
   for(const rings of polys)for(const tri of turf.tesselate(turf.polygon(rings)).features){
    const pts=tri.geometry.coordinates[0].slice(0,3).map(q=>[q[0],q[1],sample(g,...q)]);
    if(pts.every(q=>Number.isFinite(q[2])))terrain.push(pts);
   }
  }
 }
}
function clip(points,h,sign){
 const out=[];
 for(let i=0;i<points.length;i++){
  const a=points[i],b=points[(i+1)%points.length],da=sign*(a[2]-h),db=sign*(b[2]-h);
  if(da>=0)out.push(a);
  if((da<0&&db>0)||(da>0&&db<0)){const t=da/(da-db);out.push([a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1]),h])}
 }
 return out;
}
function build(g,parcel,h){
 prepare(g,parcel);
 const origin=maplibregl.MercatorCoordinate.fromLngLat([(g.w+g.e)/2,(g.s+g.n)/2],h),triangles=[],lines=[];
 const xyz=p=>{const m=maplibregl.MercatorCoordinate.fromLngLat(p,p[2]);return[m.x-origin.x,m.y-origin.y,m.z-origin.z]};
 const add=(a,b,c,color)=>{const p=[a,b,c].map(xyz);triangles.push({p,color,center:p[0].map((v,i)=>(v+p[1][i]+p[2][i])/3)})};
 const fan=(p,color)=>{for(let i=1;i+1<p.length;i++)add(p[0],p[i],p[i+1],color)};
 const key=p=>p.slice(0,2).map(v=>v.toFixed(9)).join(',');
 for(const [sign,color]of [[1,[.91,.24,.20,.36]],[-1,[.15,.48,.95,.4]]]){
  const edges=new Map();
  for(const tri of terrain){
   const p=clip(tri,h,sign);if(p.length<3||p.every(q=>Math.abs(q[2]-h)<1e-7))continue;
   fan(p,color);fan(p.map(q=>[q[0],q[1],h]),color);
   for(let i=0;i<p.length;i++){const a=p[i],b=p[(i+1)%p.length],k=[key(a),key(b)].sort().join('|');const prev=edges.get(k);if(prev)prev.count++;else edges.set(k,{a,b,count:1})}
  }
  for(const {a,b,count} of edges.values())if(count===1){const A=[a[0],a[1],h],B=[b[0],b[1],h];add(a,b,B,color);add(a,B,A,color)}
 }
 for(const t of terrain)fan(t,[.72,.79,.76,.13]);
 const polys=parcel.geometry.type==='Polygon'?[parcel.geometry.coordinates]:parcel.geometry.coordinates;
 for(const rings of polys){
  for(const t of turf.tesselate(turf.polygon(rings)).features)fan(t.geometry.coordinates[0].slice(0,3).map(q=>[...q,h]),[1,.87,.39,.18]);
  for(const ring of rings)for(let i=1;i<ring.length;i++)lines.push(xyz([...ring[i-1],h]),xyz([...ring[i],h]));
 }
 return {origin,triangles,lines};
}
function create(map){
 return {id:ID,type:'custom',renderingMode:'3d',data:null,
 onAdd(m,gl){
  const shader=(type,src)=>{const s=gl.createShader(type);gl.shaderSource(s,src);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s};
  const vs=shader(gl.VERTEX_SHADER,'attribute vec3 p;attribute vec4 c;uniform mat4 matrix;varying vec4 color;void main(){gl_Position=matrix*vec4(p,1.);color=c;}');
  const fs=shader(gl.FRAGMENT_SHADER,'precision mediump float;varying vec4 color;void main(){gl_FragColor=vec4(color.rgb*color.a,color.a);}');
  this.program=gl.createProgram();gl.attachShader(this.program,vs);gl.attachShader(this.program,fs);gl.linkProgram(this.program);gl.deleteShader(vs);gl.deleteShader(fs);if(!gl.getProgramParameter(this.program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(this.program));
  this.buffer=gl.createBuffer();this.vao=gl.createVertexArray();this.matrix=gl.getUniformLocation(this.program,'matrix');this.p=gl.getAttribLocation(this.program,'p');this.c=gl.getAttribLocation(this.program,'c');
 },
 render(gl,projection){
  if(!this.data)return;
  const mat=projection?.defaultProjectionData?.mainMatrix||projection?.modelViewProjectionMatrix||projection;if(!mat||mat.length!==16)return;
  const {origin,triangles,lines}=this.data,M=Array.from(mat);
  for(let r=0;r<4;r++)M[12+r]=mat[r]*origin.x+mat[4+r]*origin.y+mat[8+r]*origin.z+mat[12+r];
  const depth=t=>{const p=t.center;return(M[2]*p[0]+M[6]*p[1]+M[10]*p[2]+M[14])/(M[3]*p[0]+M[7]*p[1]+M[11]*p[2]+M[15])};
  triangles.sort((a,b)=>depth(b)-depth(a));const data=[];for(const t of triangles)for(const p of t.p)data.push(...p,...t.color);const count=data.length/7;for(const p of lines)data.push(...p,1,.9,.49,.8);
  const old={vao:gl.getParameter(gl.VERTEX_ARRAY_BINDING),buffer:gl.getParameter(gl.ARRAY_BUFFER_BINDING),program:gl.getParameter(gl.CURRENT_PROGRAM),depth:gl.isEnabled(gl.DEPTH_TEST),mask:gl.getParameter(gl.DEPTH_WRITEMASK),cull:gl.isEnabled(gl.CULL_FACE),blend:gl.isEnabled(gl.BLEND),src:gl.getParameter(gl.BLEND_SRC_RGB),dst:gl.getParameter(gl.BLEND_DST_RGB),sa:gl.getParameter(gl.BLEND_SRC_ALPHA),da:gl.getParameter(gl.BLEND_DST_ALPHA)};
  // Draw through the opaque base map so below-ground cut surfaces remain visible.
  gl.useProgram(this.program);gl.bindVertexArray(this.vao);gl.bindBuffer(gl.ARRAY_BUFFER,this.buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(data),gl.DYNAMIC_DRAW);
  gl.enableVertexAttribArray(this.p);gl.vertexAttribPointer(this.p,3,gl.FLOAT,false,28,0);gl.enableVertexAttribArray(this.c);gl.vertexAttribPointer(this.c,4,gl.FLOAT,false,28,12);gl.uniformMatrix4fv(this.matrix,false,new Float32Array(M));
  gl.disable(gl.DEPTH_TEST);gl.depthMask(false);gl.disable(gl.CULL_FACE);gl.enable(gl.BLEND);gl.blendFunc(gl.ONE,gl.ONE_MINUS_SRC_ALPHA);gl.drawArrays(gl.TRIANGLES,0,count);gl.drawArrays(gl.LINES,count,lines.length);
  gl.bindVertexArray(old.vao);gl.bindBuffer(gl.ARRAY_BUFFER,old.buffer);gl.useProgram(old.program);gl.depthMask(old.mask);for(const [cap,on]of [[gl.DEPTH_TEST,old.depth],[gl.CULL_FACE,old.cull],[gl.BLEND,old.blend]])on?gl.enable(cap):gl.disable(cap);gl.blendFuncSeparate(old.src,old.dst,old.sa,old.da);
 },
 onRemove(m,gl){gl.deleteBuffer(this.buffer);gl.deleteVertexArray(this.vao);gl.deleteProgram(this.program)}
 };
}
window.JinTerrainVolume={
 update(map,g,parcel,h){const data=build(g,parcel,h);if(!map.getLayer(ID)){layer=create(map);map.addLayer(layer)}layer.data=data;map.triggerRepaint()},
 clear(map){if(map.getLayer(ID))map.removeLayer(ID);layer=null;map.triggerRepaint()},
 build
};
})();
