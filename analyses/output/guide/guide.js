{
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const N={
 q:{v:'?',t:'The question',s:'S&P up on Fri 27 Nov?',c:'--dim',wide:[.06,.5],nar:[.5,.06]},
 raw:{v:'52%',t:'Desk judgment',s:'Claude reads the tape',c:'--vio',wide:[.25,.15],nar:[.17,.27]},
 cal:{v:'37%',t:'Calibrated',s:'its 50-70% calls hit 30%',c:'--vio',wide:[.45,.15],nar:[.17,.49]},
 base:{v:'50%',t:'VIX formula',s:'no-opinion baseline',c:'--amb',wide:[.35,.5],nar:[.5,.27]},
 sim:{v:'47%',t:'Simulator',s:'200,000 replayed paths',c:'--blu',wide:[.35,.82],nar:[.83,.27]},
 fin:{v:'45%',t:'Final call',s:'average of the three',c:'--tx',wide:[.66,.5],nar:[.5,.7],fill:true},
 gr:{v:'Fri',t:'Graded at the close',s:'up: 0.31 · down: 0.20',c:'--grn',wide:[.88,.5],nar:[.5,.88],dash:true}
};
const E=[['q','raw'],['q','base'],['q','sim'],['raw','cal'],['cal','fin'],['base','fin'],['sim','fin'],['fin','gr']];
const fig=document.getElementById('flow');
function draw(){
 const W=fig.clientWidth,H=fig.clientHeight,nar=W<640,r=nar?24:28;
 const P=k=>{const f=nar?N[k].nar:N[k].wide;return [f[0]*W,f[1]*H]};
 let o=`<svg viewBox="0 0 ${W} ${H}" aria-hidden="true">`;
 for(const [a,b] of E){const [x1,y1]=P(a),[x2,y2]=P(b);
  const d=nar?`M${x1},${y1} C${x1},${(y1+y2)/2} ${x2},${(y1+y2)/2} ${x2},${y2}`:`M${x1},${y1} C${(x1+x2)/2},${y1} ${(x1+x2)/2},${y2} ${x2},${y2}`;
  o+=`<path d="${d}" fill="none" stroke="${css(N[b].c==='--tx'?N[a].c:N[b].c)}" stroke-width="3" opacity=".55"/>`;}
 for(const k in N){const n=N[k],[x,y]=P(k),col=css(n.c),bg=css('--bg');
  o+=`<circle cx="${x}" cy="${y}" r="${r}" fill="${n.fill?col:bg}" stroke="${col}" stroke-width="3" ${n.dash?'stroke-dasharray="5 4"':''}/>`;
  o+=`<text x="${x}" y="${y+5}" text-anchor="middle" style="font-weight:800;font-size:${n.v.length>3?13:15}px;fill:${n.fill?bg:css('--tx')}">${n.v}</text>`;
  const side=k==='q'&&nar;
  const tx=side?x+r+10:x,ty=side?y-2:y+r+20,anc=side?'start':(!nar&&k==='q'?'start':(!nar&&k==='gr'?'end':'middle'));
  const ax=(!nar&&k==='q')?x-r:(!nar&&k==='gr')?x+r:tx;
  const st=`paint-order:stroke;stroke:${bg};stroke-width:4px`;
  o+=`<text x="${ax}" y="${ty}" text-anchor="${anc}" style="font-weight:700;font-size:15px;fill:${css('--tx')};${st}">${n.t}</text>`;
  if(!(nar&&['raw','base','sim'].includes(k)))o+=`<text x="${ax}" y="${ty+18}" text-anchor="${anc}" style="font-size:13px;fill:${css('--dim')};${st}">${n.s}</text>`;}
 fig.innerHTML=o+'</svg>';
}
const roFlow=new ResizeObserver(draw);roFlow.observe(fig);
const mq=window.matchMedia('(prefers-color-scheme: dark)');mq.addEventListener?.('change',draw);
const moTheme=new MutationObserver(draw);moTheme.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});

const R=[
 ['S&P, next day','2022 to 2026, 1,229 days',.795,.983],
 ['S&P, five days','same test period',.791,.986],
 ['VIX, next day','2022 to 2026, 1,262 days',.811,.990],
 ['S&P, last 15 days','the November shock',.533,.867]
];
const lo=.4,sc=v=>((v-lo)/(1-lo)*100).toFixed(1)+'%';
document.getElementById('rangeBars').innerHTML=R.map(([a,b,n,o])=>`<div class="brow"><div class="lab">${a}<span><b style="color:var(--vio)">new ${(n*100).toFixed(1)}%</b> · old ${(o*100).toFixed(1)}%</span></div><div class="btrack"><i class="b new" style="width:${sc(n)}"></i><i class="b old" style="width:${sc(o)}"></i><i class="t" style="left:${sc(.8)}"></i></div><div class="sm mut">${b}</div></div>`).join('')+
 `<div class="legend"><span><i style="background:var(--vio)"></i>new rule (v5)</span><span><i style="background:var(--line)"></i>old 1.6x rule</span><span><i style="background:var(--amb);width:3px;height:12px"></i>80% target</span><span>scale starts at 40%</span></div>`;
}
