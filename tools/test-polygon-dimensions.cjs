const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(__dirname+'/../index.html','utf8');
const core=source.slice(source.indexOf('// Polygon dimensions use metres'),source.indexOf('// End polygon dimension core.'));
const ctx=vm.createContext({});vm.runInContext(core,ctx);
const frame={origin:[128.1,35.1],mx:111195.0802335329*Math.cos(35.1*Math.PI/180),my:111195.0802335329};
const geo=xy=>ctx.editPolygonGeographic(xy,frame),clone=x=>JSON.parse(JSON.stringify(x));
const square=geo([[0,0],[20,0],[20,15],[0,15]]),locks={lengths:{},angles:{}};
let next=ctx.editPolygonSolve(square,{lengths:{0:25},angles:{}});assert(next);assert(Math.abs(ctx.editPolygonLength(next[0],next[1])-25)<.002);
let fixed={lengths:{0:25},angles:{1:90}};next=ctx.editPolygonSolve(next,fixed);assert(next);assert.equal(ctx.editPolygonLocksError(next,fixed),'');
let shape=ctx.editPolygonLocal(next,ctx.editPolygonFrame(next));assert(Math.abs(ctx.editPolygonAngle(shape,1)-90)<.02);
const fixedShape={lengths:{},angles:{}};square.forEach((p,i)=>{fixedShape.lengths[i]=ctx.editPolygonLength(p,square[(i+1)%4]);fixedShape.angles[i]=90});
next=ctx.editPolygonSolve(square,fixedShape);assert(next,'redundant complete rectangle constraints');
const target=geo([[3,4]])[0];next=ctx.editPolygonSolve(square,fixedShape,{index:0,point:target});assert(next,'drag rigid constrained shape');assert(ctx.editPolygonLength(next[0],target)<.002);assert.equal(ctx.editPolygonLocksError(next,fixedShape),'');
assert.equal(ctx.editPolygonSolve(square,{lengths:fixedShape.lengths,angles:{0:90,1:90,2:90,3:120}}),null,'contradictory quadrilateral angles rejected');
const triangle=geo([[0,0],[10,0],[4,8]]);assert.equal(ctx.editPolygonSolve(triangle,{lengths:{0:30,1:5,2:5},angles:{}}),null,'triangle inequality rejected');
const concave=geo([[0,0],[20,0],[20,10],[10,10],[10,20],[0,20]]);shape=ctx.editPolygonLocal(concave,ctx.editPolygonFrame(concave));assert(Math.abs(ctx.editPolygonAngle(shape,3)-270)<.02);
next=ctx.editPolygonSolve(concave,{lengths:{0:22},angles:{3:270}});assert(next,'reflex angle kept during length change');assert.equal(ctx.editPolygonLocksError(next,{lengths:{0:22},angles:{3:270}}),'');
const reversed=concave.toReversed();shape=ctx.editPolygonLocal(reversed,ctx.editPolygonFrame(reversed));assert(Math.abs(ctx.editPolygonAngle(shape,2)-270)<.02);assert(ctx.editPolygonSolve(reversed,{lengths:{0:12},angles:{2:270}}));
assert.deepEqual(clone(ctx.editPolygonLocks(JSON.stringify({lengths:{0:25,99:2},angles:{1:90}}),4)),{lengths:{0:25},angles:{1:90}},'round-trip constraints');
assert.deepEqual(clone(ctx.editPolygonLocks('bad JSON',4)),locks);
assert.equal(ctx.editPolygonLocksError(square,{lengths:{0:25},angles:{}}).includes('변 길이'),true);
// Ordinary dimensional edits in both winding orders must meet every retained lock.
for(let i=0;i<20;i++){
 const polygon=i%2?square.toReversed():square;
 const dims={lengths:{0:12+i/2,2:12+i/2},angles:{0:90,1:90,2:90,3:90}};
 const result=ctx.editPolygonSolve(polygon,dims);assert(result,'rectangle sample '+i);assert.equal(ctx.editPolygonLocksError(result,dims),'');
}
console.log('PASS: dimension solver, locked drag, conflicts, reflex angles, winding and persistence (32 scenarios)');
