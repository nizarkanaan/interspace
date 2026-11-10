// Original procedural artwork for the Interspace design study. No external assets.
(() => {
  const root = document.getElementById('ispace');
  const homes = {sources:[190,183],evidence:[602,183],experiment:[190,373],review:[602,373]};
  let active = null;
  const appearance = matchMedia('(prefers-color-scheme: dark)');

  function colours() {
    const dark = appearance.matches;
    return dark ? {
      outside:'#181b21',floor:'#343e48',tile:'#3d4853',wall:'#626d77',wallSide:'#46535d',outline:'#18222d',
      desk:'#a3adb0',deskSide:'#63737c',paper:'#e5e9db',screen:'#14202e',display:'#82adce',
      ink:'#e8edf1',muted:'#b5c2cc',plant:'#7d9c68',pot:'#b08976',glass:'#a5c5d0',
      white:'#eef1ed',skin:'#dba982',hair:'#302b33',shoe:'#202631',yellow:'#d1b963',shadow:'#25313b',
      Researcher:'#9cb181',Scout:'#72b8b5',Builder:'#95a8e6',Reviewer:'#d79aaf'
    } : {
      outside:'#e5e8eb',floor:'#e0e8e4',tile:'#cdd9d3',wall:'#f8f9f4',wallSide:'#bfcacb',outline:'#48565e',
      desk:'#b9c5ca',deskSide:'#84969f',paper:'#fffdf2',screen:'#253346',display:'#7dadd2',
      ink:'#24343b',muted:'#53676d',plant:'#64805b',pot:'#bb8064',glass:'#a2c7cf',
      white:'#fbfcf5',skin:'#d6a17b',hair:'#383038',shoe:'#313947',yellow:'#cfad42',shadow:'#b8c7c1',
      Researcher:'#6d8054',Scout:'#367b7b',Builder:'#5168b1',Reviewer:'#9b526d'
    };
  }

  function paintCharacter(ctx,role,x,y,p,{selected=false,scale=1.65}={}) {
    ctx.save();ctx.translate(x,y);ctx.scale(scale,scale);
    const rect=(a,b,w,h,c)=>{ctx.fillStyle=c;ctx.fillRect(a,b,w,h);};
    ctx.fillStyle=p.shadow;ctx.beginPath();ctx.ellipse(0,2,13,4,0,0,Math.PI*2);ctx.fill();
    if(selected){ctx.strokeStyle=p[role];ctx.lineWidth=2;ctx.beginPath();ctx.ellipse(0,2,17,6,0,0,Math.PI*2);ctx.stroke();}
    rect(-7,-7,5,9,p.shoe);rect(2,-7,5,9,p.shoe);
    rect(-8,-23,16,18,p[role]);
    rect(-12,-22,4,12,p[role]);rect(8,-22,4,12,p[role]);
    rect(-12,-11,4,4,p.skin);rect(8,-11,4,4,p.skin);
    rect(-7,-36,14,13,p.skin);rect(-8,-38,16,5,p.hair);rect(-8,-35,3,6,p.hair);
    rect(-3,-30,2,2,p.hair);rect(3,-30,2,2,p.hair);
    if(role==='Researcher'){
      rect(-8,-23,6,18,p.white);rect(2,-23,6,18,p.white);rect(-12,-22,4,10,p.white);rect(8,-22,4,10,p.white);
      rect(-5,-23,3,5,p[role]);rect(2,-23,3,5,p[role]);rect(-7,-33,6,5,p.outline);rect(1,-33,6,5,p.outline);
      rect(-6,-32,4,3,p.glass);rect(2,-32,4,3,p.glass);rect(-1,-32,2,1,p.outline);
      rect(-15,-16,7,11,p[role]);rect(-14,-15,5,8,p.paper);rect(-15,-16,2,11,p[role]);rect(4,-15,3,4,p[role]);
    }else if(role==='Scout'){
      rect(-9,-39,18,5,p[role]);rect(-4,-35,15,3,p[role]);rect(7,-44,2,6,p.outline);rect(6,-46,4,3,p.yellow);
      rect(-7,-24,3,17,p.yellow);rect(-10,-13,10,9,p.pot);rect(-9,-15,8,3,p.outline);rect(10,-18,6,9,p.outline);rect(11,-17,4,5,p.display);
    }else if(role==='Builder'){
      rect(-10,-25,20,7,p[role]);rect(-2,-24,1,7,p.white);rect(2,-24,1,7,p.white);
      rect(-10,-39,20,3,p.outline);rect(-11,-37,4,10,p.outline);rect(7,-37,4,10,p.outline);
      rect(-10,-34,3,6,p[role]);rect(8,-34,3,6,p[role]);rect(-4,-14,8,5,p.outline);
    }else{
      rect(-5,-43,10,7,p.hair);rect(-8,-23,16,4,p.white);rect(-2,-21,4,7,p.outline);
      rect(-7,-33,14,3,p.outline);rect(-5,-32,3,2,p.glass);rect(2,-32,3,2,p.glass);
      rect(7,-20,10,16,p.pot);rect(8,-18,8,12,p.paper);rect(10,-21,4,3,p.outline);
      rect(10,-15,5,1,p[role]);rect(10,-12,5,1,p[role]);
    }
    ctx.restore();
  }

  function drawScene(state) {
    const {canvas,items,selected}=state,ctx=canvas.getContext('2d'),p=colours();
    const width=canvas.clientWidth;if(!width)return;
    const height=width*480/800,dpr=Math.min(devicePixelRatio||1,2);
    if(canvas.width!==Math.round(width*dpr)||canvas.height!==Math.round(height*dpr)){
      canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
    }
    ctx.setTransform(canvas.width/800,0,0,canvas.height/480,0,0);ctx.imageSmoothingEnabled=false;
    const rect=(x,y,w,h,c)=>{ctx.fillStyle=c;ctx.fillRect(x,y,w,h);};
    const line=(x,y,X,Y,c,w=1)=>{ctx.strokeStyle=c;ctx.lineWidth=w;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(X,Y);ctx.stroke();};
    const box=(x,y,w,h,c)=>{rect(x+5,y+6,w,h,p.shadow);rect(x,y,w,h,c);rect(x,y+h-6,w,6,p.deskSide);};
    const label=(text,x,y,size=11,color=p.muted)=>{if(width<440&&size<14)return;ctx.fillStyle=color;ctx.font=`${Math.max(size,11*800/width)}px ui-monospace,monospace`;ctx.fillText(text,x,y);};
    const plant=(x,y)=>{rect(x-9,y,18,15,p.pot);rect(x-2,y-24,4,26,p.plant);rect(x-15,y-20,15,9,p.plant);rect(x,y-30,12,12,p.plant);rect(x-9,y-38,9,14,p.plant);};
    const monitor=(x,y,w=52)=>{rect(x,y,w,33,p.outline);rect(x+4,y+4,w-8,24,p.screen);rect(x+w/2-3,y+33,6,8,p.outline);rect(x+w/2-13,y+40,26,3,p.outline);for(let i=0;i<3;i++)rect(x+9,y+9+i*6,w-22-(i%2)*8,2,p.display);};
    const paper=(x,y)=>{rect(x,y,22,28,p.paper);for(let i=0;i<4;i++)rect(x+4,y+5+i*4,13,1,p.deskSide);};
    ctx.clearRect(0,0,800,480);rect(0,0,800,480,p.outside);rect(32,62,736,386,p.shadow);
    rect(22,48,748,389,p.floor);for(let x=22;x<770;x+=34)line(x,48,x,437,p.tile);for(let y=48;y<437;y+=34)line(22,y,770,y,p.tile);
    rect(22,16,748,40,p.wall);rect(22,49,748,9,p.wallSide);rect(22,16,10,421,p.wallSide);rect(760,16,10,421,p.wallSide);
    rect(330,23,140,21,p.screen);label('INTERSPACE / LAB 01',344,38,11,p.paper);
    for(const x of [80,570]){rect(x,23,150,22,p.outline);rect(x+3,26,144,16,p.glass);line(x+75,25,x+75,43,p.wall,3);}
    // Stable department areas: agents never move between them.
    for(const [x,y] of [[44,63],[488,63],[44,251],[488,251]]){
      rect(x,y,250,179,p.wall);rect(x+4,y+4,242,171,p.floor);
    }
    // Shelves, collection drawers and a whiteboard make the room spatially legible.
    box(52,70,245,37,p.desk);for(let i=0;i<16;i++)rect(61+i*14,73,9,26,[p.Scout,p.Researcher,p.paper,p.Reviewer,p.Builder][i%5]);
    box(508,68,205,42,p.paper);line(522,78,594,78,p.Researcher,2);line(522,87,676,87,p.deskSide);line(522,96,648,96,p.deskSide);
    plant(735,93);plant(60,425);
    // Upper work benches, lower work benches, and the central circulation aisle.
    box(105,110,160,46,p.desk);monitor(117,111,48);box(202,113,44,27,p.Scout);rect(208,119,31,2,p.paper);
    box(510,110,184,46,p.desk);paper(524,119);paper(550,116);rect(622,115,44,25,p.Researcher);rect(627,120,34,15,p.paper);
    box(103,285,172,48,p.desk);monitor(115,282);monitor(177,282);rect(115,325,110,7,p.outline);
    box(509,285,188,48,p.desk);paper(522,295);paper(550,291);rect(597,292,54,29,p.paper);line(602,300,642,300,p.Reviewer,2);
    box(53,240,32,103,p.outline);for(let i=0;i<5;i++){rect(58,247+i*18,22,11,p.deskSide);rect(61,250+i*18,3,3,p.display);}
    // Central meeting island with source packets; passage is left clear around it.
    box(326,101,144,57,p.desk);paper(344,114);paper(375,110);rect(425,119,18,17,p.yellow);
    rect(339,160,18,12,p.deskSide);rect(434,160,18,12,p.deskSide);
    label('WEB SCOUTS',107,232,16,p.ink);label('RESEARCH',510,232,16,p.ink);label('BUILDERS',105,423,16,p.ink);label('REVIEW',510,423,16,p.ink);
    label('EVIDENCE DESK',349,92,10);label('SHARED PROJECT',340,415,10);
    state.positions=[];
    for(const item of items){
      const [x,y]=homes[item.id];
      paintCharacter(ctx,item.role,x,y,p,{selected:selected===item.id});
      state.positions.push({id:item.id,x,y:y-30});
      const symbol=item.state==='Needs you'?'!':item.state==='Done'?'✓':item.label==='Paused'?'Ⅱ':item.state==='Working'?'…':'·';
      if(width>=440){rect(x+13,y-65,20,19,p.paper);label(symbol,x+18,y-51,14,item.state==='Needs you'?p.Reviewer:p.outline);}
      if(width>=440){ctx.textAlign='center';label(item.role,x,y+20,14,p.ink);ctx.textAlign='left';}
    }
    // Shared project board; this scene is static, with no animation loop.
    rect(340,300,100,64,p.wall);rect(344,304,92,56,p.deskSide);paper(354,312);paper(386,312);
    for(const el of root.querySelectorAll('[data-character-role]')){
      const portrait=el.getContext('2d');el.width=60;el.height=70;portrait.clearRect(0,0,60,70);paintCharacter(portrait,el.dataset.characterRole,30,65,p,{scale:1.4});
    }
  }

  function unmount(){
    if(!active)return;
    active.observer.disconnect();
    active.canvas.removeEventListener('pointerdown',active.pick);
    appearance.removeEventListener('change',active.redraw);
    active=null;
  }

  function mount(canvas,items,selected,onSelect){
    unmount();if(!canvas)return;
    const state={canvas,items,selected,onSelect,positions:[]};
    state.redraw=()=>drawScene(state);
    state.pick=event=>{
      const b=canvas.getBoundingClientRect(),x=(event.clientX-b.left)*800/b.width,y=(event.clientY-b.top)*480/b.height;
      const closest=state.positions.map(pos=>({...pos,distance:Math.hypot(pos.x-x,pos.y-y)})).sort((a,b)=>a.distance-b.distance)[0];
      if(closest&&closest.distance<40)onSelect(closest.id);
    };
    canvas.addEventListener('pointerdown',state.pick);appearance.addEventListener('change',state.redraw);
    state.observer=new ResizeObserver(state.redraw);state.observer.observe(canvas);active=state;drawScene(state);
  }

  root.interspaceLab={mount,unmount};
})();
