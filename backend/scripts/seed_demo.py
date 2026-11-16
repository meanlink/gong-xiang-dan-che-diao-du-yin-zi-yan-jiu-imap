import time, json
from sqlalchemy import select, func
from src.config.database import Session
from migrations.initial import migrate
from src.models import User, Dataset, Job, Report, Delivery, Audit, Chain, ChainNode, ChainEdge
from src.services.business import metadata, seed_records, analyze, evaluate_chain_node
from src.services.chains import build_briefing
from src.services.reports import deliver
from src.utils.security import hash_password
from src.utils.serialization import checksum
def seed():
    migrate()
    with Session() as db:
        for role,name in [('admin','林知 · 业务负责人'),('analyst','陈舟 · 分析员'),('viewer','周禾 · 观察员')]:
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)):
                db.add(User(email=email,name=name,role=role,password=hash_password('Demo123!')))
        db.flush()
        m=metadata()
        d=db.scalar(select(Dataset).where(Dataset.name==m['dataset_name']))
        if not d:
            rows=seed_records()
            d=Dataset(name=m['dataset_name'],source=m['short']+'-202611.csv',records=rows,checksum=checksum(rows),created_at=time.time())
            db.add(d); db.flush()
        admin=db.scalar(select(User).where(User.role=='admin'))
        if not db.scalar(select(Job).where(Job.name=='基线复核 · '+m['name'])):
            params={p['key']:p['default'] for p in m.get('parameters',[])}
            result=analyze(d.records,params)
            json.dumps(result,ensure_ascii=False,allow_nan=False)
            j=Job(name='基线复核 · '+m['name'],dataset_id=d.id,params=params,status='completed',result=result,created_by=admin.id,created_at=time.time()-3600,finished_at=time.time()-3595,approved=True)
            db.add(j);db.flush()
            r=Report(name='每日业务复核简报',job_id=j.id,destination='业务复核组 · 本地收件箱',interval_seconds=86400,next_run=time.time()+86400,enabled=True)
            db.add(r);db.flush();deliver(db,r)
            db.add(Audit(actor='seed',action='demo.baseline',detail={'dataset':d.id},at=time.time()))
        if not db.scalar(select(Chain).where(Chain.name=='多级复核 · 补车候选研究链')):
            spec=[('screen','初筛 · 30 分钟提前量',1,0.3,[]),
                  ('strict','严格复核 · 门槛收紧',1,0.7,['screen']),
                  ('lead60','提前量对照 · 60 分钟',2,0.3,['screen']),
                  ('final','汇合终审 · 共同通过',1,0.5,['strict','lead60'])]
            c=Chain(name='多级复核 · 补车候选研究链',dataset_id=d.id,status='running',records=d.records,dataset_checksum=d.checksum,
                    created_by=admin.id,created_at=time.time()-3500,started_at=time.time()-3490)
            db.add(c); db.flush()
            nodes={}
            for key,name,lag,threshold,preds in spec:
                n=ChainNode(chain_id=c.id,key=key,name=name,lag=lag,threshold=threshold,status='pending')
                db.add(n); nodes[key]=n
                for p in preds: db.add(ChainEdge(chain_id=c.id,from_key=p,to_key=key))
            db.flush()
            for key,name,lag,threshold,preds in spec:
                n=nodes[key]
                candidates=sorted(set.intersection(*[set(nodes[p].result.get('passed',[])) for p in preds])) if preds else sorted({r['station'] for r in d.records})
                if not candidates:
                    n.status='empty'; n.result={'candidates':[],'passed':[],'stations':[],'reason':'所有前置共同通过的站点为空'}
                else:
                    n.status='completed'; n.result=evaluate_chain_node(d.records,candidates,lag,threshold)
                n.finished_at=time.time()-3400
            c.status='completed'; c.finished_at=time.time()-3400
            c.approved=True; c.approved_by='admin@demo.local'; c.approved_at=time.time()-3300
            c.briefing=build_briefing(c,[nodes[k] for k,_,_,_,_ in spec])
            db.add(Audit(actor='seed',action='chain.seed',detail={'id':c.id},at=time.time()))
        db.commit()
        counts={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in [User,Dataset,Job,Report,Delivery,Chain,Audit]}
        print(json.dumps(counts,ensure_ascii=False))
        return counts
if __name__=='__main__':seed()
