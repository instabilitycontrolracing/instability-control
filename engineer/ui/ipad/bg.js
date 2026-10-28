/* Race Engineer iPad - living backdrop (2026-10-25).
   Requested: "the rest of the screen should change to the corner or straight theme ... it should carry animation too, it
   should look captivating, addicting to look at"; "max out the graphics on the iPad"; "crazy shooting stars as the
   PlayStation corner comes up and goes by, particles flying by with the speed lines on the Mulsanne straights, the Dunlop
   chicane tyres spinning on their axis and throwing smoke across the screen"; "I don't want this background to be idle ever".

   One full-screen WebGL fragment shader draws the scene of the stop the car is at (everything procedural, on the GPU, at
   the iPad's native resolution), cross-fading to the next stop's scene. Motion is tied to the car's speed. If frames run
   long the drawing resolution steps down by itself (and back up when there's headroom), so the panels never stutter.
   No WebGL = the CSS colour layers underneath stay as they were. */
(() => {
  "use strict";
  const cv = document.getElementById("bgfx");
  if (!cv) return;
  const gl = cv.getContext("webgl", { alpha: false, antialias: false, depth: false, stencil: false, premultipliedAlpha: false, powerPreference: "high-performance", preserveDrawingBuffer: false });
  if (!gl) return;

  const KINDS = { Plain: 0, PlayStation: 1, Michelin: 2, Dunlop: 3, Bricks: 4, Speed: 5, Earth: 6, Maker: 7 };

  const VS = "attribute vec2 a;void main(){gl_Position=vec4(a,0.,1.);}";
  const FS = `
precision highp float;
uniform vec2 uRes; uniform float uTime, uSpd, uMix, uAgeA, uAgeB, uKA, uKB, uTexOn;
uniform vec3 uA1, uA2, uB1, uB2; uniform sampler2D uTex;
#define PI 3.14159265
float h11(float n){return fract(sin(n*127.1)*43758.5453);}
float h21(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
vec2 h22(vec2 p){float n=h21(p);return vec2(n,h21(p+n+17.17));}
float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);
  return mix(mix(h21(i),h21(i+vec2(1,0)),f.x),mix(h21(i+vec2(0,1)),h21(i+vec2(1,1)),f.x),f.y);}
float fbm(vec2 p){float v=0.,a=.5;mat2 m=mat2(1.6,1.2,-1.2,1.6);for(int i=0;i<5;i++){v+=a*noise(p);p=m*p;a*=.5;}return v;}
float seg(vec2 p,vec2 a,vec2 b){vec2 pa=p-a,ba=b-a;float h=clamp(dot(pa,ba)/dot(ba,ba),0.,1.);return length(pa-ba*h);}
float segT(vec2 p,vec2 a,vec2 b){vec2 pa=p-a,ba=b-a;return clamp(dot(pa,ba)/dot(ba,ba),0.,1.);}

/* twinkling star field: one star per cell at most */
float stars(vec2 p,float dens,float t,float sz){
  vec2 c=floor(p*dens),f=fract(p*dens)-.5;float r=h21(c);if(r<.86)return 0.;
  vec2 o=(h22(c)-.5)*.7;float d=length(f-o);float tw=.55+.45*sin(t*(1.5+r*4.)+r*40.);
  return smoothstep(sz,0.,d)*tw*(r-.86)*7.;}

/* shooting stars: a burst when the corner arrives (age < 4 s), then a steady shower */
vec3 meteors(vec2 p,float t,float age){
  vec3 col=vec3(0.);float burst=1.-smoothstep(2.5,5.,age);
  for(int i=0;i<28;i++){float fi=float(i);
    float act=step(fi,9.+burst*18.);
    float per=mix(2.6,6.5,h11(fi*3.1))*mix(1.,.45,burst);
    float ph=h11(fi*7.7)*per;float lt=mod(t+ph,per)/per;float k=floor((t+ph)/per);
    float life=.22;if(lt>life||act<.5)continue;float u=lt/life;
    float ang=mix(-2.55,-2.2,h11(fi+k*1.3));vec2 dir=vec2(cos(ang),sin(ang));
    vec2 st=vec2(mix(-.2,1.1,h11(fi*5.3+k*.71)),mix(.15,.62,h11(fi*2.9+k*1.9)));
    float len=mix(.25,.6,h11(fi*9.1+k));vec2 head=st+dir*u*1.4;vec2 tail=head-dir*len*min(1.,u*3.);
    float d=seg(p,head,tail);float along=segT(p,tail,head);
    float fade=sin(u*PI);float w=mix(.0015,.0045,h11(fi*4.4));
    float core=smoothstep(w,0.,d)*along*along;float glow=exp(-d*90.)*along*.35;
    float flare=exp(-length(p-head)*55.)*1.2;
    vec3 c=mix(vec3(.55,.75,1.),vec3(1.,.8,1.),h11(fi*13.));
    col+=c*(core*2.2+glow+flare)*fade;}
  return col;}

/* drifting motes: soft dots on a moving grid (several layers) */
float motes(vec2 p,float t,vec2 vel,float dens,float sz){
  vec2 q=p*dens+vel*t;vec2 c=floor(q),f=fract(q)-.5;float r=h21(c);vec2 o=(h22(c)-.5)*.8;
  float tw=.5+.5*sin(t*2.+r*30.);return smoothstep(sz,0.,length(f-o))*step(.55,r)*tw;}

/* a racing tyre on its axis: rubber, tread, a yellow sidewall band, a spinning 5-spoke rim (motion-blurred) */
vec4 tyre(vec2 p,vec2 c,float R,float spin,float mb){
  vec2 d=p-c;float r=length(d);if(r>R*1.04)return vec4(0.);
  float a=atan(d.y,d.x)+spin;
  vec3 col=vec3(.045,.045,.05);float al=smoothstep(R*1.01,R*.99,r);
  float tread=mix(step(.5,fract(a*22./(2.*PI))),.5,mb);col*=mix(1.,.55,tread*step(R*.9,r));
  float band=smoothstep(.012*R,0.,abs(r-R*.78));col=mix(col,vec3(1.,.81,0.),band*.9);
  float side=smoothstep(R*.62,R*.6,r);
  float spokes=mix(smoothstep(.35,.0,abs(fract(a*5./(2.*PI))-.5)-.08),.42,mb*.85);
  vec3 rim=mix(vec3(.12,.13,.15),vec3(.62,.64,.68),.5+.5*sin(a*2.+1.));
  float hub=smoothstep(R*.14,R*.12,r);
  col=mix(col,rim*(.4+.6*spokes),side);col=mix(col,vec3(.08),hub);
  float hl=smoothstep(.5,1.,dot(normalize(d+1e-4),normalize(vec2(-.6,.8))))*smoothstep(R*.6,R,r)*.25;
  col+=hl;return vec4(col,al);}

vec3 hue(float h){return clamp(abs(mod(h*6.+vec3(0,4,2),6.)-3.)-1.,0.,1.);}

vec3 scene(float k,vec3 c1,vec3 c2,float age,vec2 uv,vec2 p,float t){
  float asp=uRes.x/uRes.y;vec3 col;float spd=.35+uSpd;
  if(k<.5){ /* plain: aurora curtains + motes, in the stop's own colour */
    col=mix(c2*.12,c2*.38,uv.y);
    for(int i=0;i<3;i++){float fi=float(i);
      float y=.55+.12*fi-.25+.13*sin(p.x*(1.4+fi*.6)+t*(.13+fi*.05)+fi*2.)+.12*(fbm(vec2(p.x*1.3+t*.05,fi*3.+t*.03))-.5);
      float dd=uv.y-y;float curtain=exp(-abs(dd)*mix(9.,18.,fi*.5))*(dd>0.?1.:.35);
      float rays=.55+.45*noise(vec2(p.x*14.+fi*7.,t*.4));
      col+=mix(c1,c1.zxy*.6+c1*.6,fi*.4)*curtain*rays*.55;}
    col+=c1*motes(p,t,vec2(-.03,-.06),18.,.07)*.5+vec3(1.)*motes(p+3.,t,vec2(.02,-.1),34.,.05)*.25;
  } else if(k<1.5){ /* PlayStation: the user's star picture drifting, a living nebula, parallax stars, shooting stars */
    vec2 tu=vec2(.32+(uv.x-.5)*asp/2.6667*.55+.08*sin(t*.018),.03+(1.-uv.y)*.44);
    tu+=vec2(.01*sin(t*.05),.004*cos(t*.04));
    vec3 tx=vec3(0.);if(uTexOn>.5){vec2 o=vec2(1.5/1600.,1.5/600.);
      tx=(texture2D(uTex,tu).rgb*2.+texture2D(uTex,tu+o).rgb+texture2D(uTex,tu-o).rgb+texture2D(uTex,tu+vec2(o.x,-o.y)).rgb+texture2D(uTex,tu+vec2(-o.x,o.y)).rgb)/6.;}
    col=vec3(.01,.02,.09)+tx*.6;
    float n=fbm(p*1.6+vec2(t*.03,-t*.02)+fbm(p*2.2-t*.02)*1.4);
    col+=vec3(.42,.14,.85)*pow(n,2.6)*1.4+vec3(.0,.38,.95)*pow(fbm(p*2.3-vec2(t*.025,0.)+5.),2.6)*1.2;
    col+=vec3(.9,.95,1.)*(stars(p+vec2(t*.004,0.),40.,t,.07)+stars(p+vec2(t*.012,0.),22.,t,.06)*1.3);
    col+=meteors(p,t,age);
  } else if(k<2.5){ /* Michelin: blue, scrolling tread chevrons, a light sweep, the yellow edge breathing */
    col=mix(vec3(.094,.204,.431),vec3(.18,.36,.69),uv.y);
    vec2 q=mat2(.94,-.34,.34,.94)*p*7.;float f=fract(q.y*1.2+abs(fract(q.x)-.5)*.9+t*.5*spd);
    col*=1.-.085*smoothstep(.0,.05,f)*smoothstep(.22,.17,f);
    col+=vec3(.3,.5,1.)*pow(fbm(p*1.5+vec2(t*.04,0.)),3.)*.35;
    float sw=fract(t*.11);float band=exp(-pow((uv.x+uv.y*.6-sw*2.6+.5)*7.,2.));col+=vec3(.55,.7,1.)*band*.25;
    col+=vec3(1.,.95,.6)*motes(p,t,vec2(-.05,.02),20.,.06)*.35;
    float ex=gl_FragCoord.x;float glowY=.75+.25*sin(t*2.+uv.y*6.);
    col=mix(col,vec3(.99,.9,0.),step(ex,9.));col+=vec3(.99,.9,0.)*exp(-ex/26.)*.35*glowY;
  } else if(k<3.5){ /* Dunlop: graphite, two tyres spinning, smoke rolling off them across the screen, yellow kerb line */
    float br=noise(vec2(p.x*2.,p.y*300.))*.04;col=mix(vec3(.11,.114,.125),vec3(.227,.235,.255),uv.y)+br;
    float w=t*(6.+uSpd*30.);
    float mb=clamp(uSpd*1.4,0.,.9);
    vec4 t1=tyre(p,vec2(-.62*asp*.62,-.18),.42,w,mb);vec4 t2=tyre(p,vec2(.78*asp*.62,.12),.27,w*1.55,mb);
    /* smoke from each contact patch, blown to the right and rising */
    for(int i=0;i<2;i++){float fi=float(i);vec2 em=fi<.5?vec2(-.62*asp*.62,-.6):vec2(.78*asp*.62,-.15);
      vec2 q=p-em;float dx=q.x;float spread=.08+max(dx,0.)*.55;
      float m=smoothstep(-.05,.1,dx)*exp(-pow(q.y-dx*.35,2.)/(spread*spread))*exp(-max(dx,0.)*.55);
      float s=fbm(q*2.4-vec2(t*(.9+uSpd*1.5),t*.25)+fi*9.)*1.15;s=smoothstep(.35,.95,s)*m;
      col=mix(col,vec3(.82,.84,.88),clamp(s*.85,0.,.85));}
    col=mix(col,t2.rgb,t2.a);col=mix(col,t1.rgb,t1.a);
    float by=gl_FragCoord.y;col=mix(col,vec3(1.,.81,0.),step(by,8.));col+=vec3(1.,.81,0.)*exp(-by/28.)*.25;
  } else if(k<4.5){ /* Bricks: relief bricks lit by a light sweeping across, warm sparks rising */
    vec2 q=gl_FragCoord.xy/vec2(84.,32.)*(uRes.y/1640.)*2.;q.x+=step(1.,mod(floor(q.y),2.))*.5;
    vec2 id=floor(q),f=fract(q);float rv=h21(id);
    vec2 e=min(f,1.-f)*vec2(84.,32.);float edge=min(e.x,e.y);float mort=smoothstep(2.,4.,edge);
    vec3 base=mix(c2*.55+vec3(.18,.06,.03),c2*.85+vec3(.25,.09,.05),rv)*mix(.9,1.1,noise(q*6.));
    vec2 nrm=vec2(f.x<.5?-1.:1.,f.y<.5?-1.:1.)*(1.-smoothstep(0.,6.,edge));
    vec2 L=vec2(sin(t*.25),cos(t*.19))*vec2(.9,.6);float lit=.55+.45*clamp(dot(normalize(vec3(nrm,1.)),normalize(vec3(L-(uv-.5)*vec2(asp,1.),.8))),0.,1.);
    float spot=exp(-length((uv-.5)*vec2(asp,1.)-L*.5)*1.6);
    col=mix(vec3(.05,.03,.02),base*lit*(.55+.9*spot),mort);
    col+=vec3(1.,.55,.15)*motes(p,t,vec2(.01,-.18),26.,.05)*.6;
  } else if(k<5.5){ /* Speed (Mulsanne etc.): streaks and particles flying by, faster with the car */
    col=mix(vec3(.016,.04,.086),vec3(.04,.11,.21),uv.y);
    for(int i=0;i<4;i++){float fi=float(i);float rows=34.+fi*22.;float ry=floor(uv.y*rows);float rr=h11(ry+fi*77.);
      float fy=fract(uv.y*rows)-.5;float x=uv.x*asp+t*(.6+fi*.45+rr*.6)*spd*2.2+rr*30.;
      float sx=fract(x*(.35+rr*.4));float len=.35+rr*.4;
      float st=smoothstep(1.-len,1.,sx)*step(sx,1.)*smoothstep(.12,0.,abs(fy))*step(.45,rr);
      col+=c1*st*(.22+fi*.1);}
    for(int i=0;i<3;i++){float fi=float(i);vec2 q=vec2(uv.x*asp*(14.+fi*10.)+t*(9.+fi*7.)*spd,uv.y*(9.+fi*6.));
      vec2 id=floor(q),f=fract(q);float r=h21(id+fi*31.);if(r>.6){vec2 o=h22(id)*vec2(.6,.6)+.2;
      vec2 dd=f-o;float tl=smoothstep(.0,-.55,dd.x)*smoothstep(.07,0.,abs(dd.y))+smoothstep(.06,0.,length(dd));
      col+=mix(c1,vec3(1.),.5)*tl*(.25+fi*.15);}}
    col+=c1*exp(-abs(uv.y-.5)*6.)*.06*(.5+.5*sin(t*1.3));
  } else if(k<6.5){ /* Earth: red earth, rolling dust clouds, heat haze, drifting grit */
    vec2 hz=vec2(0.,sin(p.x*30.+t*3.)*.003*smoothstep(.5,0.,uv.y));
    col=mix(c2*.25+vec3(.06,.03,.02),c2*.12,uv.y)+c1*exp(-length((uv+hz-vec2(.5,0.))*vec2(asp*.7,1.))*1.6)*.45;
    float dc=fbm(p*1.6+vec2(-t*.22*spd,t*.03)+fbm(p*3.-t*.1)*.8);col=mix(col,c1*.95+vec3(.2,.1,.05),smoothstep(.38,.85,dc)*.75*(1.-uv.y*.5));
    float dc2=fbm(p*4.+vec2(-t*.5*spd,0.));col+=c1*smoothstep(.55,.9,dc2)*.18*(1.-uv.y);
    col+=c1*motes(p,t,vec2(-.25*spd,.02),40.,.05)*.5+vec3(1.,.8,.6)*motes(p+7.,t,vec2(-.5*spd,.03),70.,.04)*.25;
  } else { /* a maker: its colour, light rays turning from the top corner, bokeh drifting */
    col=mix(c2*.16,c2*.42,uv.y);vec2 o=vec2(1.05,1.08);vec2 d=uv-o;d.x*=asp;float a=atan(d.y,d.x);
    float rays=pow(noise(vec2(a*18.+t*.15,t*.1)),2.5)*smoothstep(1.8,.0,length(d));col+=c1*rays*.55;
    for(int i=0;i<10;i++){float fi=float(i);vec2 c=vec2(fract(h11(fi)+t*.012*(1.+h11(fi*3.))),fract(h11(fi*5.)-t*.008*(1.+h11(fi*2.))));
      c.x*=asp;float rr=mix(.04,.14,h11(fi*9.));float b=smoothstep(rr,rr*.7,length(p+vec2(asp*.5,.5)-c));col+=c1*b*.07;}
    col+=c1*motes(p,t,vec2(-.02,-.04),24.,.05)*.35;
  }
  return col;}

void main(){
  vec2 uv=gl_FragCoord.xy/uRes;vec2 p=(gl_FragCoord.xy-.5*uRes)/uRes.y;float t=uTime;
  vec3 col=scene(uKB,uB1,uB2,uAgeB,uv,p,t);
  if(uMix<.999){vec3 ca=scene(uKA,uA1,uA2,uAgeA,uv,p,t);col=mix(ca,col,smoothstep(0.,1.,uMix));}
  col*=1.-.42*pow(length((uv-.5)*vec2(1.05,1.25)),2.2);                     /* vignette */
  col+=(h21(gl_FragCoord.xy+fract(t*7.)*100.)-.5)*.018;                      /* living film grain */
  gl_FragColor=vec4(pow(max(col,0.),vec3(.95)),1.);
}`;

  function sh(type, src) { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { console.error(gl.getShaderInfoLog(s)); return null; } return s; }
  const vs = sh(gl.VERTEX_SHADER, VS), fs = sh(gl.FRAGMENT_SHADER, FS);
  if (!vs || !fs) return;
  const pr = gl.createProgram(); gl.attachShader(pr, vs); gl.attachShader(pr, fs); gl.linkProgram(pr);
  if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) { console.error(gl.getProgramInfoLog(pr)); return; }
  gl.useProgram(pr);
  const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(pr, "a"); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const U = {}; for (const n of ["uRes", "uTime", "uSpd", "uMix", "uAgeA", "uAgeB", "uKA", "uKB", "uTexOn", "uA1", "uA2", "uB1", "uB2", "uTex"]) U[n] = gl.getUniformLocation(pr, n);

  // the user's PlayStation star picture (served by the PC from Grandstand's corner_logos; optional)
  const tex = gl.createTexture(); let texOn = 0;
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([2, 6, 30, 255]));
  const img = new Image();
  img.onload = () => {
    gl.bindTexture(gl.TEXTURE_2D, tex); gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    texOn = 1;
  };
  const key = new URLSearchParams(location.search).get("k") || (() => { try { return localStorage.getItem("re_key") || ""; } catch (e) { return ""; } })();
  img.src = "/themebg/playstation.png?k=" + encodeURIComponent(key);

  const hex = (h, d) => { if (!h || !/^#?[0-9a-f]{6}/i.test(h)) return d; h = h.replace("#", ""); return [parseInt(h.slice(0, 2), 16) / 255, parseInt(h.slice(2, 4), 16) / 255, parseInt(h.slice(4, 6), 16) / 255]; };
  const hsl = (h, s, l) => { const f = (n) => { const k = (n + h / 30) % 12, a = s * Math.min(l, 1 - l); return l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)); }; return [f(0), f(8), f(4)]; };

  // the scene state: B = now, A = the one fading out
  const CAP = Math.max(0.2, Math.min(1, parseFloat(new URLSearchParams(location.search).get("gfx")) || 1));   // ?gfx=0.5 caps the resolution
  const S = { A: null, B: null, mix: 1, t0: performance.now(), scale: CAP, slow: 0, fast: 0, last: 0, spd: 0 };
  function sceneFor(p, bg) {
    if (p && p.name) {
      let h = 0; for (const ch of String(p.name)) h = (h * 31 + ch.charCodeAt(0)) % 360;
      const kind = p.kind ? (KINDS[p.kind] ?? 7) : 0;
      const plainC = hsl(h, .7, .55), plainD = hsl(h, .5, .3);
      return { key: (p.kind || "") + "|" + p.name, k: kind, c1: kind === 0 ? plainC : hex(p.c1, plainC), c2: kind === 0 ? plainD : hex(p.c2, plainD), start: performance.now() };
    }
    const b = hex(bg, [0.02, 0.1, 0.24]);                 // between stops: the track logo's colour, still alive
    return { key: "bg|" + bg, k: 0, c1: [Math.min(1, b[0] * 2.2 + .15), Math.min(1, b[1] * 2.2 + .15), Math.min(1, b[2] * 2.2 + .25)], c2: b.map((x) => Math.min(1, x * 1.6)), start: performance.now() };
  }
  window.BGFX = {
    place(p, bg) {
      const s = sceneFor(p, bg);
      if (S.B && S.B.key === s.key) return;
      if (!S.B) { S.B = s; S.A = s; S.mix = 1; return; }
      S.A = S.B; S.B = s; S.mix = 0;
    },
    speed(kmh) { if (typeof kmh === "number" && isFinite(kmh)) S.spd = Math.max(0, Math.min(1, kmh / 320)); },
  };
  document.body.classList.add("bgfx");

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 3) * S.scale;
    const w = Math.max(16, Math.round(cv.clientWidth * dpr)), h = Math.max(16, Math.round(cv.clientHeight * dpr));
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
  }
  addEventListener("resize", resize);

  let spdS = 0;
  function frame(now) {
    requestAnimationFrame(frame);
    if (document.hidden) return;
    const dt = S.last ? now - S.last : 16; S.last = now;
    // keep it smooth: step the drawing resolution down when frames run long, back up when there's room
    if (dt > 24) { S.slow++; S.fast = 0; } else if (dt < 14) { S.fast++; S.slow = 0; }
    if (S.slow > 20 && S.scale > 0.5 * CAP) { S.scale = Math.max(0.5 * CAP, S.scale - 0.1); S.slow = 0; }
    if (S.fast > 240 && S.scale < CAP) { S.scale = Math.min(CAP, S.scale + 0.1); S.fast = 0; }
    resize();
    if (!S.B) BGFX.place(null, getComputedStyle(document.documentElement).getPropertyValue("--bg0").trim());
    S.mix = Math.min(1, S.mix + dt / 1400);
    spdS += (S.spd - spdS) * Math.min(1, dt / 600);
    gl.viewport(0, 0, cv.width, cv.height);
    gl.uniform2f(U.uRes, cv.width, cv.height);
    gl.uniform1f(U.uTime, ((now - S.t0) / 1000) % 3600);
    gl.uniform1f(U.uSpd, spdS);
    gl.uniform1f(U.uMix, S.mix);
    gl.uniform1f(U.uKA, S.A.k); gl.uniform1f(U.uKB, S.B.k);
    gl.uniform1f(U.uAgeA, (now - S.A.start) / 1000); gl.uniform1f(U.uAgeB, (now - S.B.start) / 1000);
    gl.uniform3fv(U.uA1, S.A.c1); gl.uniform3fv(U.uA2, S.A.c2); gl.uniform3fv(U.uB1, S.B.c1); gl.uniform3fv(U.uB2, S.B.c2);
    gl.uniform1f(U.uTexOn, texOn); gl.uniform1i(U.uTex, 0);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
  requestAnimationFrame(frame);
})();
