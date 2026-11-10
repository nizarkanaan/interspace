// Original procedural artwork for the Interspace design study. No external assets.
(() => {
  const root = document.getElementById('ispace');
  const catalog = root.interspaceRoles;
  let active = null;
  const appearance = matchMedia('(prefers-color-scheme: dark)');

  function colours() {
    const dark = appearance.matches;
    return dark ? {
      outside:'#181b21',floor:'#343e48',tile:'#3d4853',wall:'#626d77',wallSide:'#46535d',outline:'#18222d',
      desk:'#a3adb0',deskSide:'#63737c',paper:'#e5e9db',screen:'#14202e',display:'#82adce',
      ink:'#e8edf1',muted:'#b5c2cc',plant:'#7d9c68',pot:'#b08976',glass:'#a5c5d0',
      white:'#eef1ed',skin:'#dba982',hair:'#302b33',shoe:'#202631',yellow:'#d1b963',shadow:'#25313b',
      Researcher:'#9cb181',Scout:'#72b8b5',Builder:'#95a8e6',Reviewer:'#d79aaf',Analyst:'#cebc80',Writer:'#c6a5d8',Coordinator:'#8fbabd'
    } : {
      outside:'#e5e8eb',floor:'#e0e8e4',tile:'#cdd9d3',wall:'#f8f9f4',wallSide:'#bfcacb',outline:'#48565e',
      desk:'#b9c5ca',deskSide:'#84969f',paper:'#fffdf2',screen:'#253346',display:'#7dadd2',
      ink:'#24343b',muted:'#53676d',plant:'#64805b',pot:'#bb8064',glass:'#a2c7cf',
      white:'#fbfcf5',skin:'#d6a17b',hair:'#383038',shoe:'#313947',yellow:'#cfad42',shadow:'#b8c7c1',
      Researcher:'#6d8054',Scout:'#367b7b',Builder:'#5168b1',Reviewer:'#9b526d',Analyst:'#887038',Writer:'#866099',Coordinator:'#4d7e82'
    };
  }

  function paintCharacter(ctx,roleName,x,y,p,{selected=false,scale=1.65}={}) {
    const definition=catalog.byName(roleName),role=definition.look;
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
    }else if(role==='Reviewer'){
      rect(-5,-43,10,7,p.hair);rect(-8,-23,16,4,p.white);rect(-2,-21,4,7,p.outline);
      rect(-7,-33,14,3,p.outline);rect(-5,-32,3,2,p.glass);rect(2,-32,3,2,p.glass);
      rect(7,-20,10,16,p.pot);rect(8,-18,8,12,p.paper);rect(10,-21,4,3,p.outline);
      rect(10,-15,5,1,p[role]);rect(10,-12,5,1,p[role]);
    }else if(role==='Analyst'){
      rect(-9,-23,18,4,p.white);rect(-7,-19,14,13,p[role]);rect(-7,-34,14,3,p.outline);
      rect(-6,-33,4,3,p.glass);rect(2,-33,4,3,p.glass);rect(-2,-21,4,13,p.outline);
    }else if(role==='Writer'){
      rect(-10,-40,20,5,p[role]);rect(-6,-43,12,4,p[role]);rect(-9,-24,18,5,p.yellow);rect(5,-23,4,12,p.yellow);
    }else{
      rect(-9,-23,18,3,p.white);rect(-3,-21,6,9,p.white);rect(-1,-20,2,8,p[role]);
      rect(7,-37,4,10,p.outline);rect(9,-28,6,2,p.outline);rect(12,-28,2,5,p.outline);
    }
    // A specialty prop supplements the department silhouette; labels identify the exact role.
    const px=11,py=-19;
    if(definition.prop==='book'||definition.prop==='notebook'){
      rect(px,py,11,15,p[role]);rect(px+2,py+2,8,11,p.paper);rect(px+3,py+4,5,1,p.outline);
    }else if(definition.prop==='bulb'){
      rect(px+1,py-5,8,8,p.yellow);rect(px+3,py+3,4,4,p.outline);rect(px+3,py-9,3,2,p.yellow);
    }else if(definition.prop==='magnifier'){
      ctx.strokeStyle=p.outline;ctx.lineWidth=2;ctx.beginPath();ctx.arc(px+5,py+1,5,0,Math.PI*2);ctx.stroke();rect(px+8,py+5,3,8,p.outline);
    }else if(definition.prop==='wrench'){
      rect(px+4,py,4,15,p.deskSide);rect(px,py-4,4,7,p.deskSide);rect(px+8,py-4,4,7,p.deskSide);rect(px,py+2,12,3,p.deskSide);
    }else if(definition.prop==='pencil'){
      rect(px+3,py-4,4,18,p.yellow);rect(px+3,py-6,4,3,p.Reviewer);rect(px+4,py+14,2,3,p.outline);
    }else if(definition.prop==='scanner'){
      rect(px,py,9,15,p.outline);rect(px+2,py+2,5,7,p.display);rect(px+4,py-5,2,5,p.outline);
    }else{
      rect(px,py,14,16,p.outline);rect(px+1,py+1,12,14,p.paper);
      if(definition.prop==='chart'){for(let i=0;i<3;i++)rect(px+3+i*3,py+11-i*3,2,3+i*3,p[role]);}
      else if(definition.prop==='mail'){rect(px+2,py+5,10,1,p[role]);rect(px+4,py+7,6,1,p[role]);rect(px+6,py+9,2,1,p[role]);}
      else if(definition.prop==='calendar'){rect(px+1,py+1,12,4,p.Reviewer);for(let i=0;i<6;i++)rect(px+3+(i%3)*3,py+7+Math.floor(i/3)*4,2,2,p.outline);}
      else if(definition.prop==='test'){rect(px+3,py+7,3,3,p.plant);rect(px+6,py+4,3,5,p.plant);}
      else if(definition.prop==='slides'){rect(px+3,py+3,9,5,p[role]);rect(px+3,py+10,8,1,p.outline);}
      else {rect(px+4,py-2,6,3,p.outline);for(let i=0;i<3;i++)rect(px+3,py+4+i*3,8,1,p[role]);}
    }
    ctx.restore();
  }

  function refreshPortraits(){
    const palette=colours();
    for(const el of root.querySelectorAll('[data-character-role]')){
      const ctx=el.getContext('2d');el.width=72;el.height=76;
      paintCharacter(ctx,el.dataset.characterRole,28,69,palette,{scale:1.4});
    }
  }

  function layoutDepartments(items){
    const groups=catalog.departments.map(group=>({...group,items:items.filter(item=>item.department===group.id)})).filter(group=>group.items.length);
    const rooms=[];let y=68;
    for(let index=0;index<groups.length;index+=2){
      const pair=groups.slice(index,index+2);
      const height=70+Math.max(...pair.map(group=>Math.ceil(group.items.length/3)))*120;
      pair.forEach((group,column)=>rooms.push({...group,x:28+column*382,y,width:362,height}));
      y+=height+18;
    }
    return {rooms,height:Math.max(y+18,270)};
  }

  function drawScene(state){
    const {canvas,items,selected}=state;if(!canvas)return;
    const width=canvas.clientWidth;if(!width)return;
    const layout=layoutDepartments(items),height=layout.height,p=colours(),ctx=canvas.getContext('2d');
    state.logicalHeight=height;
    canvas.style.aspectRatio='800 / '+height;
    const dpr=Math.min(devicePixelRatio||1,2);
    canvas.width=Math.round(width*dpr);canvas.height=Math.round(width*height/800*dpr);
    ctx.setTransform(canvas.width/800,0,0,canvas.height/height,0,0);ctx.imageSmoothingEnabled=false;
    const rect=(x,y,w,h,c)=>{ctx.fillStyle=c;ctx.fillRect(x,y,w,h);};
    const label=(text,x,y,size=17)=>{ctx.fillStyle=p.ink;ctx.font=Math.max(size,11*800/width)+'px ui-monospace,monospace';ctx.fillText(text,x,y);};
    rect(0,0,800,height,p.outside);rect(14,14,772,height-28,p.floor);
    for(let x=14;x<786;x+=32)rect(x,14,1,height-28,p.tile);
    for(let y=14;y<height-14;y+=32)rect(14,y,772,1,p.tile);
    rect(14,14,772,38,p.wall);rect(14,49,772,7,p.wallSide);
    label('INTERSPACE / DEPARTMENTS',32,40,18);
    state.positions=[];
    for(const room of layout.rooms){
      rect(room.x,room.y,room.width,room.height,p.wallSide);rect(room.x+5,room.y+5,room.width-10,room.height-10,p.floor);
      rect(room.x+5,room.y+5,room.width-10,31,p.wall);label(room.name.toUpperCase(),room.x+16,room.y+27,18);
      room.items.forEach((item,index)=>{
        const x=room.x+60+(index%3)*120,y=room.y+132+Math.floor(index/3)*120;
        const role=catalog.byName(item.role);
        rect(x-37,y-63,82,30,p.shadow);rect(x-40,y-67,82,30,p.desk);rect(x-40,y-42,82,5,p.deskSide);
        if(['engineering','analysis','operations','discovery'].includes(room.id)){
          rect(x-29,y-89,42,29,p.outline);rect(x-26,y-86,36,21,p.screen);
          for(let i=0;i<3;i++)rect(x-22,y-82+i*5,25-i*4,2,p.display);
          rect(x-11,y-60,5,6,p.outline);
        }else{
          rect(x-27,y-65,19,22,p.paper);rect(x+2,y-62,23,17,p[role.look]);rect(x+5,y-59,17,11,p.paper);
        }
        paintCharacter(ctx,item.role,x,y,p,{selected:selected===item.id,scale:1.5});
        state.positions.push({id:item.id,x,y:y-27});
        // Short unique specialty code stays readable; full names and state are in native buttons below.
        ctx.textAlign='center';label(role.code+' '+(item.number||1),x,y+24,16);ctx.textAlign='left';
      });
    }
    if(!layout.rooms.length)label('NO AGENTS IN THIS DEPARTMENT',38,140,18);
  }

  function unmount(){
    if(!active)return;
    active.observer?.disconnect();
    active.canvas?.removeEventListener('pointerdown',active.pick);
    appearance.removeEventListener('change',active.redraw);active=null;
  }

  function mount(canvas,items,selected,onSelect){
    unmount();
    const state={canvas,items,selected,onSelect,positions:[],logicalHeight:480};
    state.redraw=()=>{drawScene(state);refreshPortraits();};
    if(canvas){
      state.pick=event=>{
        const b=canvas.getBoundingClientRect(),x=(event.clientX-b.left)*800/b.width,y=(event.clientY-b.top)*state.logicalHeight/b.height;
        const closest=state.positions.map(pos=>({...pos,distance:Math.hypot(pos.x-x,pos.y-y)})).sort((a,b)=>a.distance-b.distance)[0];
        if(closest&&closest.distance<40)onSelect(closest.id);
      };
      canvas.addEventListener('pointerdown',state.pick);
      state.observer=new ResizeObserver(state.redraw);state.observer.observe(canvas);
    }
    appearance.addEventListener('change',state.redraw);active=state;state.redraw();
  }
  root.interspaceLab={mount,unmount,refreshPortraits};
})();
