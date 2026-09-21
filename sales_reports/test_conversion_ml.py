import sys, os, random, tempfile
from datetime import datetime, timedelta
sys.path.insert(0, ".")
import conversion_ml as ml

fails=[]
def check(n,c): print(("  PASS" if c else "  FAIL"), n); (fails.append(n) if not c else None)

# ---- pure metrics ----
check("_auc perfect", abs(ml._auc([0,0,1,1],[0.1,0.2,0.8,0.9]) - 1.0) < 1e-9)
check("_auc worst",   abs(ml._auc([1,1,0,0],[0.1,0.2,0.8,0.9]) - 0.0) < 1e-9)
check("_brier basic", abs(ml._brier([1,0],[1.0,0.0]) - 0.0) < 1e-9)
check("_logloss finite", ml._logloss([1,0],[0.9,0.1]) > 0)

FO = ["meet","reach","referral","city"]

# ---- tiny WoE baseline (stand-in for ConversionModel) ----
from collections import defaultdict
class WoE:
    def train(self, samples):
        self.n=len(samples); self.pos=sum(1 for _f,y in samples if y)
        self.base_rate=(self.pos/self.n) if self.n else 0.05
        cnt=defaultdict(lambda:[0,0])
        for f,y in samples:
            for k in FO:
                v=f.get(k,"Unknown"); cnt[(k,v)][0]+=1; cnt[(k,v)][1]+=1 if y else 0
        self.rates={key:(c[1]+0.5)/(c[0]+1.0) for key,c in cnt.items()}
        return self
    def score(self, feats):
        vals=[self.rates.get((k,feats.get(k,"Unknown")), self.base_rate) for k in FO]
        p=sum(vals)/len(vals) if vals else self.base_rate
        return min(max(p,0.01),0.99)
factory=lambda samp: WoE().train(samp)

# ---- synthetic dataset with real signal + time order ----
random.seed(7)
recs=[]
base_day=datetime(2025,1,1)
for i in range(700):
    meet=random.choice(["attended","scheduled","none","none"])
    reach=random.choice(["single","multi"])
    referral=random.choice(["yes","no","no"])
    city=random.choice(["Pune","Mumbai","Nashik","Unknown"])
    # true conversion probability driven mostly by meet + referral
    pr=0.08 + (0.55 if meet=="attended" else 0.0) + (0.15 if referral=="yes" else 0.0) \
       + (0.05 if reach=="multi" else 0.0)
    label = random.random() < min(pr,0.95)
    recs.append({"mobile": f"90000{i:05d}", "feats":{"meet":meet,"reach":reach,
                 "referral":referral,"city":city}, "label":label, "resolved":True,
                 "when": base_day + timedelta(days=i)})

out=tempfile.mkdtemp()

# on-mode: full pipeline (sklearn present)
res = ml.build_and_select(recs, factory, FO, out, mode="on")
check("baseline_full has score", hasattr(res["baseline_full"], "score"))
check("metrics n_resolved", res["metrics"]["n_resolved"]==700)
check("metrics has holdout", "holdout_n" in res["metrics"])
check("on-mode scorer present", res["scorer"] is not None)
p = res["scorer"].score({"meet":"attended","reach":"multi","referral":"yes","city":"Pune"})
check("scorer prob in range", 0.01 <= p <= 0.99)
p2 = res["scorer"].score({"meet":"none","reach":"single","referral":"no","city":"ZZZ-unseen"})
check("scorer handles unseen city", 0.01 <= p2 <= 0.99)
check("attended scores higher than none", p > p2)
check("metrics csv written", os.path.exists(os.path.join(out,"conversion_model_metrics.csv")))
print("   chosen model:", res["metrics"]["chosen"],
      "| baseline_brier", res["metrics"].get("baseline_brier"),
      "enhanced_brier", res["metrics"].get("enhanced_brier"),
      "| baseline_auc", res["metrics"].get("baseline_auc"),
      "enhanced_auc", res["metrics"].get("enhanced_auc"))

# shadow-mode: no visible scorer, but metrics logged
res_sh = ml.build_and_select(recs, factory, FO, out, mode="shadow")
check("shadow scorer is None", res_sh["scorer"] is None)
check("shadow still logs metrics", res_sh["metrics"]["n_resolved"]==700)

# insufficient data -> fallback
small=[{"mobile":str(i),"feats":{"meet":"none","reach":"single","referral":"no","city":"Pune"},
        "label": i%10==0, "resolved":True, "when":None} for i in range(40)]
res_small = ml.build_and_select(small, factory, FO, out, mode="on")
check("insufficient -> scorer None", res_small["scorer"] is None)
check("insufficient -> baseline_full present", res_small["baseline_full"] is not None)
check("insufficient note", "insufficient" in res_small["metrics"]["note"])

# dedup: duplicate mobile, converted wins
dup=[{"mobile":"555","feats":{"meet":"none"},"label":False,"resolved":True,"when":None},
     {"mobile":"555","feats":{"meet":"attended"},"label":True,"resolved":True,"when":None}]
dd=ml._dedup(dup)
check("dedup collapses to 1", len(dd)==1)
check("dedup converted wins", dd[0]["label"] is True)

print()
print("FAILURES:", fails) if fails else print("ALL CONVERSION_ML TESTS PASSED")
sys.exit(1 if fails else 0)
