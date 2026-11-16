import time, json, logging
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Job, Dataset, Report, Chain, ChainNode
from src.services.business import analyze
from src.services import chains as chains_service
from src.services.reports import deliver
from src.services.audit import record
logging.basicConfig(level=logging.INFO)
def execute(job_id):
    with Session() as db:
        j=db.get(Job,job_id)
        if not j or j.status!='queued':return
        j.status='running'; db.commit()
        try:
            d=db.get(Dataset,j.dataset_id)
            result=analyze(d.records,j.params)
            json.dumps(result,allow_nan=False)
            j.result=result;j.status='completed';j.finished_at=time.time()
            record(db,'worker','job.completed',{'id':j.id})
        except Exception as e:
            logging.exception('Analysis failed')
            j.status='failed';j.error=str(e)[:990];j.finished_at=time.time()
            record(db,'worker','job.failed',{'id':j.id,'error':j.error})
        db.commit()
def execute_chain(chain_id):
    # 按依赖推进：每轮领取一个前置全部通过的节点执行，直到没有可推进节点
    while True:
        with Session() as db:
            node_id=chains_service.claim_next(db,chain_id)
            db.commit()
        if node_id is None:break
        chains_service.run_node(node_id)
    with Session() as db:
        chains_service.finalize(db,chain_id)
        db.commit()
def tick():
    with Session() as db:
        queued=list(db.scalars(select(Job.id).where(Job.status=='queued').limit(3)))
    for job_id in queued:execute(job_id)
    with Session() as db:
        running=list(db.scalars(select(Chain.id).where(Chain.status=='running')))
    for chain_id in running:execute_chain(chain_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())):
            d=deliver(db,r)
            if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
        db.commit()
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # This Compose stack has a single worker. A crash must not strand its jobs.
    with Session() as db:
        for j in db.scalars(select(Job).where(Job.status=='running')):
            j.status='queued';record(db,'worker','job.recovered',{'id':j.id})
        for n in db.scalars(select(ChainNode).where(ChainNode.status=='running')):
            n.status='pending';record(db,'worker','chain.node.recovered',{'id':n.id})
        db.commit()
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop(['analysis:queue','chain:queue'],timeout=1)
            if item:
                key=item[0].decode() if isinstance(item[0],bytes) else item[0]
                if key=='chain:queue':execute_chain(int(item[1]))
                else:execute(int(item[1]))
            tick()
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
if __name__=='__main__':main()
