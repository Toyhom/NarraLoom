import {t} from './i18n.js';
import {actionPose} from './actions.js';
// Source lip/skin warp and one generated cavity; legacy keypose atlases remain readable.
const vertex=`#version 300 es
in vec2 pos;out vec2 uv;
uniform vec2 resolution,imageSize,mouth,eyeL,eyeR;
uniform float faceWidth,jaw,blink,happy,sad,angry,brow,roundM,wide,headX,headY,tilt,breath,closeup,atlasReady,bodyX,bodyY,bodyTilt,lean;
float zone(vec2 p,vec2 c,vec2 r){vec2 d=(p-c)/r;return exp(-dot(d,d)*2.);}
void main(){uv=pos;vec2 p=pos*imageSize;vec2 m=mouth*imageSize;vec2 l=eyeL*imageSize;vec2 r=eyeR*imageSize;float f=faceWidth*imageSize.x;
 for(int i=0;i<2;i++){vec2 e=i==0?l:r;float z=zone(p,e,vec2(f*.19,f*.10));p.y+=(e.y-p.y)*z*blink*.98;vec2 b=e-vec2(0.,f*.095);float bz=zone(p,b,vec2(f*.23,f*.13));float inner=1.-clamp(abs(p.x-(l.x+r.x)*.5)/f*2.,0.,1.);p.y+=f*(angry*.13*inner-sad*.12*inner-brow*.065)*bz;p.y-=happy*f*.025*z;}
 float mz=zone(p,m,vec2(f*.26,f*.2));float corner=clamp(abs(p.x-m.x)/(f*.12),0.,1.);p.y+=mz*(jaw*(1.-atlasReady)*f*.06*clamp((p.y-m.y)/f*8.+.5,0.,1.)-happy*f*.12*(1.-atlasReady)*corner+sad*f*.05*(1.-atlasReady)*corner);p.x+=(p.x-m.x)*mz*((wide*.15-roundM*.2)*(1.-atlasReady));
 vec2 hc=(l+r)*.5;float hz=zone(p,hc+vec2(0.,f*.12),vec2(f*.7,f*.72));p.x+=headX*f*.055*hz;p.y+=headY*f*.035*hz;float ca=cos(tilt*hz),sa=sin(tilt*hz);vec2 d=p-hc;p=hc+vec2(ca*d.x-sa*d.y,sa*d.x+ca*d.y);p.y+=sin(pos.y*3.14159)*breath*imageSize.y*.002;
 vec2 pivot=vec2(hc.x,mix(hc.y,imageSize.y,.63));float upper=1.-smoothstep(pivot.y,imageSize.y,p.y);
 vec2 body=p-pivot;float ba=bodyTilt*upper;float bc=cos(ba),bs=sin(ba);p=pivot+vec2(bc*body.x-bs*body.y,bs*body.x+bc*body.y);
 p.x+=(p.x-hc.x)*lean*upper+bodyX*imageSize.x*upper;p.y+=(p.y-pivot.y)*lean*upper+bodyY*imageSize.y*upper;
 float scale=min(resolution.x/(imageSize.x*1.1),resolution.y/(imageSize.y*1.08));float zoom=mix(1.,clamp(.5/faceWidth,1.1,2.2),closeup);vec2 focus=mix(imageSize*.5,vec2(imageSize.x*.5,hc.y+f*.35),closeup);vec2 q=(p-focus)*scale*zoom;q.y=-q.y;gl_Position=vec4(q/(resolution*.5),0.,1.);}`;
const fragment=`#version 300 es
precision highp float;
in vec2 uv;out vec4 color;
uniform sampler2D art,mouthAtlas;
uniform vec2 imageSize;
uniform vec4 mouthRoi;
uniform float jaw,roundM,happy,atlasReady,sourceLip,maxOpen,repaired;
uniform vec2 lipBounds;
uniform float lipCurve[33];
float curve(float x){float t=clamp((x-lipBounds.x)/(lipBounds.y-lipBounds.x),0.,1.)*32.;int a=int(floor(t));return mix(lipCurve[a],lipCurve[min(a+1,32)],fract(t));}
vec4 neutralAt(vec2 p){
 if(repaired<.5)return texture(art,p/imageSize);
 vec2 q=(p-mouthRoi.xy)/mouthRoi.zw;
 vec4 neutralPixel=texture(mouthAtlas,vec2(clamp(q.x,.00261,.99739)*.5,clamp(q.y,.00261,.99739)));
 float edge=smoothstep(0.,.06,min(min(q.x,q.y),min(1.-q.x,1.-q.y)));
 return mix(texture(art,p/imageSize),neutralPixel,edge);
}
vec4 sourceMouth(vec2 pixel){
 float width=lipBounds.y-lipBounds.x, cx=(lipBounds.x+lipBounds.y)*.5;
 float shapeScale=1.-roundM*.26+happy*.10;
 float yfade=1.-smoothstep(width*.20,width*.40,abs(pixel.y-curve(cx)));
 float xfade=1.-smoothstep(width*.59,width*.82,abs(pixel.x-cx));
 float sx=mix(pixel.x,cx+(pixel.x-cx)/shapeScale,xfade*yfade);
 float nx=(sx-cx)/(width*.5), line=curve(sx);
 float smileShift=-happy*width*.035*min(1.,nx*nx)*xfade*yfade;
 float dy=pixel.y-line-smileShift;
 float halfGap=jaw*maxOpen*.5*pow(max(0.,1.-nx*nx),.7);
 float sy=line+sign(dy)*max(0.,abs(dy)-halfGap*yfade);
 vec4 skin=neutralAt(vec2(sx,sy));
 if(halfGap>.005){
  float inside=smoothstep(-.65,.65,halfGap-abs(dy))*smoothstep(0.,.12,jaw);
  float v=clamp((dy+halfGap)/(2.*halfGap),.00261,.99739);
  vec3 cavity=texture(mouthAtlas,vec2(.5+clamp(nx*.5+.5,.00261,.99739)*.5,v)).rgb;
  skin.rgb=mix(skin.rgb,cavity,inside);
 }
 return skin;
}
vec4 tile(vec2 p,float j,float r,float s){
 return texture(mouthAtlas,(clamp(p,vec2(.003),vec2(.997))+vec2(j,s*3.+r))/vec2(8.,6.));
}
vec4 row(vec2 p,float j,float r,float s){return mix(tile(p,floor(j),r,s),tile(p,min(7.,floor(j)+1.),r,s),fract(j));}
vec4 shape(vec2 p,float j,float r,float s){return mix(row(p,j,floor(r),s),row(p,j,min(2.,floor(r)+1.),s),fract(r));}
void main(){
 color=texture(art,uv);
 if(atlasReady>.5){
  vec2 local=(uv*imageSize-mouthRoi.xy)/mouthRoi.zw;
  if(all(greaterThanEqual(local,vec2(0.)))&&all(lessThanEqual(local,vec2(1.)))){
   if(sourceLip>.5){color=sourceMouth(uv*imageSize);return;}
   float j=clamp(max(jaw,happy*.4),0.,1.)*7., r=clamp(roundM,0.,1.)*2.;
   vec4 mouth=mix(shape(local,j,r,0.),shape(local,j,r,1.),clamp(happy*.8,0.,1.));
   color.rgb=mix(color.rgb,mouth.rgb,mouth.a);
  }
 }
}
`;
function shader(gl,kind,source){const s=gl.createShader(kind);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;}
export class PuppetStage{
 constructor(canvas,onStatus){this.canvas=canvas;this.onStatus=onStatus;this.loaded=false;this.frame=null;this.face=null;this.mode='listening';this.look=[0,0];this.smooth={};this.generation=0;this.active=false;
  this.gl=canvas.getContext('webgl2',{alpha:true,premultipliedAlpha:false,preserveDrawingBuffer:true});if(!this.gl)throw Error(t("浏览器需要支持 WebGL2"));const g=this.gl;this.program=g.createProgram();g.attachShader(this.program,shader(g,g.VERTEX_SHADER,vertex));g.attachShader(this.program,shader(g,g.FRAGMENT_SHADER,fragment));g.linkProgram(this.program);if(!g.getProgramParameter(this.program,g.LINK_STATUS))throw Error(g.getProgramInfoLog(this.program));
  const points=[];const nx=64,ny=96;for(let y=0;y<ny;y++)for(let x=0;x<nx;x++){const a=x/nx,b=y/ny,c=(x+1)/nx,d=(y+1)/ny;points.push(a,b,c,b,a,d,c,b,c,d,a,d);}this.count=points.length/2;g.bindBuffer(g.ARRAY_BUFFER,g.createBuffer());g.bufferData(g.ARRAY_BUFFER,new Float32Array(points),g.STATIC_DRAW);const loc=g.getAttribLocation(this.program,'pos');g.enableVertexAttribArray(loc);g.vertexAttribPointer(loc,2,g.FLOAT,false,0,0);this.locations={};
  canvas.addEventListener('pointermove',e=>{const b=canvas.getBoundingClientRect();this.look=[(e.clientX-b.left)/b.width*2-1,(e.clientY-b.top)/b.height*2-1];});canvas.addEventListener('pointerleave',()=>this.look=[0,0]);this.last=performance.now();const loop=()=>{this.render();this.raf=requestAnimationFrame(loop);};this.raf=requestAnimationFrame(loop);
 }
 async load(character){const generation=++this.generation;this.loaded=false;this.onStatus(t("正在准备 2D 立绘…"));const base=character.asset_base||`/assets/${character.profile.character_id}/puppet/`;const response=await fetch(base+'rig.json');if(!response.ok)throw Error(t("这个角色还没有 2D 资源"));const rig=await response.json();let atlas=null;if(rig.mouth_binding?.atlas){atlas=new Image();atlas.src=base+rig.mouth_binding.atlas;await atlas.decode();}const image=new Image();image.src=base+rig.image;await image.decode();if(generation!==this.generation)return;this.rig=rig;this.character=character;this.smooth={};this.actionPreview=null;const g=this.gl;g.useProgram(this.program);if(this.texture)g.deleteTexture(this.texture);this.texture=g.createTexture();g.bindTexture(g.TEXTURE_2D,this.texture);g.texImage2D(g.TEXTURE_2D,0,g.RGBA,g.RGBA,g.UNSIGNED_BYTE,image);g.texParameteri(g.TEXTURE_2D,g.TEXTURE_MIN_FILTER,g.LINEAR);g.texParameteri(g.TEXTURE_2D,g.TEXTURE_MAG_FILTER,g.LINEAR);g.texParameteri(g.TEXTURE_2D,g.TEXTURE_WRAP_S,g.CLAMP_TO_EDGE);g.texParameteri(g.TEXTURE_2D,g.TEXTURE_WRAP_T,g.CLAMP_TO_EDGE);if(this.atlasTexture)g.deleteTexture(this.atlasTexture);this.atlasTexture=g.createTexture();g.activeTexture(g.TEXTURE1);g.bindTexture(g.TEXTURE_2D,this.atlasTexture);if(atlas)g.texImage2D(g.TEXTURE_2D,0,g.RGBA,g.RGBA,g.UNSIGNED_BYTE,atlas);else g.texImage2D(g.TEXTURE_2D,0,g.RGBA,1,1,0,g.RGBA,g.UNSIGNED_BYTE,new Uint8Array([0,0,0,0]));g.texParameteri(g.TEXTURE_2D,g.TEXTURE_MIN_FILTER,g.LINEAR);g.texParameteri(g.TEXTURE_2D,g.TEXTURE_MAG_FILTER,g.LINEAR);g.texParameteri(g.TEXTURE_2D,g.TEXTURE_WRAP_S,g.CLAMP_TO_EDGE);g.texParameteri(g.TEXTURE_2D,g.TEXTURE_WRAP_T,g.CLAMP_TO_EDGE);g.activeTexture(g.TEXTURE0);this.loaded=true;this.onStatus(t("准备好了"));this.sceneInfo={character:character.profile.character_id,mode:'2d',renderer:rig.renderer,morphNames:rig.channels};this.motionEvidence={speechFrames:0,maxJointDelta:0,maxMouth:0,maxExpression:0,actionFrames:{},maxBodyDelta:0};}
 dispose(){this.active=false;this.loaded=false;this.generation++;cancelAnimationFrame(this.raf);this.gl.getExtension("WEBGL_lose_context")?.loseContext();}
 previewAction(name){this.actionPreview={started:performance.now(),cue:{name,start_s:0,duration_s:2,strength:.85}};}
 setMode(mode){this.mode=mode;if(mode!=='speaking'){this.frame=null;this.face=null;this.actionPreview=null;}}
 setPerformance(frame,face){this.frame=frame;this.face=face;}
 render(){if(!this.loaded||!this.active)return;const g=this.gl,box=this.canvas.getBoundingClientRect(),dpr=Math.min(devicePixelRatio,2),w=Math.round(box.width*dpr),h=Math.round(box.height*dpr);if(!w||!h)return;if(this.canvas.width!==w||this.canvas.height!==h){this.canvas.width=w;this.canvas.height=h;}g.viewport(0,0,w,h);g.clearColor(.945,.965,.925,1);g.clear(g.COLOR_BUFFER_BIT);g.enable(g.BLEND);g.blendFunc(g.SRC_ALPHA,g.ONE_MINUS_SRC_ALPHA);g.useProgram(this.program);const u=(n,...v)=>{const loc=this.locations[n]??=g.getUniformLocation(this.program,n);v.length===4?g.uniform4f(loc,...v):v.length===2?g.uniform2f(loc,...v):g.uniform1f(loc,v[0]);};const t=performance.now()/1000,dt=Math.min(.1,t-this.last/1000);this.last=performance.now();const values=this.face?.values??{};const get=n=>{const goal=values[n]??0;return this.smooth[n]=(this.smooth[n]??0)+(goal-(this.smooth[n]??0))*(1-Math.exp(-dt*18));};const lm=this.rig.landmarks;
 let cueTime=this.frame?.action_time_s??this.frame?.segment_time_s??0,cues=this.frame?.actions??[];
 if(this.actionPreview){cueTime=(performance.now()-this.actionPreview.started)/1000;cues=[this.actionPreview.cue];if(cueTime>=this.actionPreview.cue.duration_s)this.actionPreview=null;}
 const pose=actionPose(cues,cueTime);this.actionState={...pose,time_s:cueTime};
 let headX=this.look[0]*.65+pose.headX,headY=this.look[1]*.45+pose.headY,tilt=Math.sin(t*.9)*.008+pose.tilt;
 u('bodyX',pose.bodyX);u('bodyY',pose.bodyY);u('bodyTilt',pose.bodyTilt);u('lean',pose.lean);
 const jaw=get('jaw_open'),happy=get('happy'),sad=get('sad'),angry=get('angry'),soft=get('soft'),blink=Math.pow(Math.max(0,Math.cos(t*1.15)),52);u('closeup',this.closeup?1:0);u('resolution',w,h);u('imageSize',this.rig.width,this.rig.height);u('mouth',...lm.mouth);u('eyeL',...lm.left_eye);u('eyeR',...lm.right_eye);u('faceWidth',lm.face_width);u('mouthWidth',this.rig.mouth_width_px);u('jaw',jaw);u('blink',Math.max(blink,get('eye_squint')*.4));u('happy',happy+soft*.25);u('sad',sad);u('angry',angry);u('brow',get('brow_up'));u('roundM',get('mouth_round'));u('wide',get('mouth_wide'));u('headX',headX);u('headY',headY);u('tilt',tilt);u('breath',Math.sin(t*1.6));u('atlasReady',this.rig.mouth_binding?1:0);const binding=this.rig.mouth_binding??{};u('sourceLip',binding.method==='source-lip-warp-v3'?1:0);u('maxOpen',binding.max_open_px??0);u('repaired',binding.missing_source_mouth_repaired?1:0);u('lipBounds',...(binding.lip_x_px??[0,1]));g.uniform1fv(g.getUniformLocation(this.program,'lipCurve[0]'),binding.lip_curve_y_px??Array(33).fill(0));u('mouthRoi',...(this.rig.mouth_binding?.roi_px??[0,0,1,1]));g.uniform1i(g.getUniformLocation(this.program,'art'),0);g.uniform1i(g.getUniformLocation(this.program,'mouthAtlas'),1);g.activeTexture(g.TEXTURE1);g.bindTexture(g.TEXTURE_2D,this.atlasTexture);g.activeTexture(g.TEXTURE0);g.bindTexture(g.TEXTURE_2D,this.texture);g.drawArrays(g.TRIANGLES,0,this.count);const e=this.motionEvidence;if(e){if(this.frame)e.speechFrames++;for(const name of pose.active)e.actionFrames[name]=(e.actionFrames[name]??0)+1;e.maxBodyDelta=Math.max(e.maxBodyDelta,Math.abs(pose.bodyX)+Math.abs(pose.bodyY)+Math.abs(pose.bodyTilt)+Math.abs(pose.lean));e.maxMouth=Math.max(e.maxMouth,jaw);e.maxJointDelta=Math.max(e.maxJointDelta,Math.abs(headX)+Math.abs(headY));e.maxExpression=Math.max(e.maxExpression,happy,sad,angry,soft);}window.avatarRenderFps=1/Math.max(dt,.001);
 }
}
