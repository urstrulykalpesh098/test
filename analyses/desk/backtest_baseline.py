"""Score the desk's S&P calls against a no-judgment VIX baseline.
Baseline: zero drift, daily sigma = VIX/100/sqrt(252) from the last close before the call,
horizon = trading days from that close to the resolve date."""
import json, glob, math, re, sys, statistics as st
from pathlib import Path
N=lambda x:0.5*(1+math.erf(x/math.sqrt(2)))
SPX={"2026-11-06":7376.86,"2026-11-09":7549.94,"2026-11-10":7520.93,"2026-11-11":7619.38,"2026-11-12":7592.40,"2026-11-13":7561.67,"2026-11-16":7416.59,"2026-11-17":7340.53,"2026-11-18":7323.63,"2026-11-19":7175.83,"2026-11-20":6910.39,"2026-11-23":7237.17,"2026-11-24":7201.09,"2026-11-25":7182.78}
VIX={"2026-11-06":25.64,"2026-11-09":19.92,"2026-11-10":19.46,"2026-11-11":17.49,"2026-11-12":18.70,"2026-11-13":19.30,"2026-11-16":22.91,"2026-11-17":25.46,"2026-11-18":24.56,"2026-11-19":28.44,"2026-11-20":35.89,"2026-11-23":26.62,"2026-11-24":26.36,"2026-11-25":28.29}
days=sorted(SPX)
num=lambda s: float(s.replace(',',''))
def base_prob(claim, made, resolves, pre_open):
    c=claim.replace('–','-').replace('—','-')
    if 'S&P' not in c or 'VIX' in c[:4]: return None
    if any(w in c.lower() for w in ('any day','at least one','high-to-low','range is','intraday','200-day average within','through year-end','week')): pass
    prior=[d for d in days if (d<made or (d==made and not pre_open and False))]
    # last close strictly before the made date for pre-open/weekend calls; same day close for close-run calls
    if not pre_open and made in SPX: prior=[d for d in days if d<=made]
    if not prior: return None
    d0=prior[-1]; C=SPX[d0]; V=VIX[d0]
    fut=[d for d in days if d0<d<=resolves]
    if not fut or resolves not in SPX: return None
    h=len(fut); s=V/100/math.sqrt(252)*math.sqrt(h)
    if re.search(r'any day|at least one|high-to-low|range|intraday|within 21|through year', c, re.I) and not re.search(r'inside|between', c, re.I): return None
    m=re.search(r'(?:inside|between)\s+([\d,]{4,6}(?:\.\d+)?)\s*(?:-|and|to)\s*([\d,]{4,6}(?:\.\d+)?)', c)
    if m:
        a,b=sorted([num(m.group(1)),num(m.group(2))]); return N(math.log(b/C)/s)-N(math.log(a/C)/s)
    m=re.search(r'(above|below|higher than|lower than|under|over)\s+(?:Fri\w*\s+|its\s+|the\s+)?(?:200-day[^0-9]*)?([\d,]{4,6}(?:\.\d+)?)', c)
    if m:
        K=num(m.group(2)); up=m.group(1) in('above','higher than','over'); p=N(math.log(C/K)/s); return p if up else 1-p
    if re.search(r'closes up|up on the day|ends the week higher|closes higher', c, re.I): return 0.5
    return None
rows=[]
for f in glob.glob(sys.argv[1]+'/*.json'):
    d=json.load(open(f)); x=d.get('data',d); pid=Path(f).stem
    if x.get('status') not in('hit','miss') or not isinstance(x.get('prob'),(int,float)): continue
    pre=('pre-open' in x.get('source','').lower()) or pid.startswith(('pre','mg','mon'))
    b=base_prob(x['claim'],x['made'],x['resolves'],pre)
    rows.append((pid,x['prob'],1 if x['status']=='hit' else 0,b,x['claim']))
br=lambda ps: st.mean((p-y)**2 for p,y in ps)
allr=[(p,y) for _,p,y,_,_ in rows]
print('all graded',len(rows),'desk Brier %.3f hit rate %.0f%%'%(br(allr),100*st.mean(y for _,y in allr)))
m=[r for r in rows if r[3] is not None]
print('S&P calls with a baseline:',len(m))
print('  desk Brier %.3f   baseline Brier %.3f   coin 0.250'%(br([(p,y) for _,p,y,_,_ in m]),br([(b,y) for _,_,y,b,_ in m])))
bins=[(0,.3),(.3,.5),(.5,.7),(.7,.85),(.85,1.01)]
print('calibration (desk all graded):')
for lo,hi in bins:
    xs=[(p,y) for p,y in allr if lo<=p<hi]
    if xs: print('  %3d-%3d%%: n=%2d said %.0f%% happened %.0f%%'%(lo*100,min(hi,1)*100,len(xs),100*st.mean(p for p,_ in xs),100*st.mean(y for _,y in xs)))
print('baseline calibration on matched:')
for lo,hi in bins:
    xs=[(b,y) for _,_,y,b,_ in m if lo<=b<hi]
    if xs: print('  %3d-%3d%%: n=%2d said %.0f%% happened %.0f%%'%(lo*100,min(hi,1)*100,len(xs),100*st.mean(p for p,_ in xs),100*st.mean(y for _,y in xs)))
json.dump([{'id':i,'prob':p,'y':y,'base':b,'claim':c} for i,p,y,b,c in rows],open(sys.argv[2],'w'),indent=0)
