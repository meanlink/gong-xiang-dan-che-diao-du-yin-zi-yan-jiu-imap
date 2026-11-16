import time, os, csv, io, hashlib, json
from fastapi import HTTPException
from src.models import Job, Report, Delivery, Chain
from src.config.settings import ARTIFACT_DIR
def create(db, data):
    if data.job_id and data.chain_id: raise HTTPException(422,'分发来源只能选择一个')
    if data.chain_id:
        c=db.get(Chain,data.chain_id)
        if not c or c.status!='completed' or not c.approved or not c.briefing:
            raise HTTPException(409,'请先选择整链完成且获批准的研究链')
        r=Report(name=data.name, chain_id=c.id, destination=data.destination, interval_seconds=data.interval_seconds, next_run=time.time()+data.delay_seconds, enabled=True)
    else:
        if not data.job_id: raise HTTPException(422,'请选择分析任务或研究链作为分发来源')
        j=db.get(Job,data.job_id)
        if not j or j.status!='completed' or not j.approved:
            raise HTTPException(409,'请先选择已完成且获批准的分析结果')
        r=Report(name=data.name, job_id=j.id, destination=data.destination, interval_seconds=data.interval_seconds, next_run=time.time()+data.delay_seconds, enabled=True)
    db.add(r); db.flush()
    return r
def safe(v):
    if isinstance(v,(int,float)) and not isinstance(v,bool): return v
    text=str(v)
    return "'"+text if text.startswith(('=','+','-','@','\t','\r')) else text
def _job_payload(db, report):
    j=db.get(Job,report.job_id)
    if not j or not j.approved: return None
    out=io.StringIO()
    out.write('\ufeff')
    table=j.result.get('table',{})
    cols=table.get('columns',[])
    writer=csv.writer(out)
    writer.writerow([safe(c['label']) for c in cols])
    for row in table.get('rows',[]): writer.writerow([safe(row.get(c['key'],'')) for c in cols])
    return out.getvalue().encode('utf-8'), {'job':j.name,'params':j.params,'result':j.result}
def _chain_payload(db, report):
    c=db.get(Chain,report.chain_id)
    if not c or not c.approved or not c.briefing: return None
    out=io.StringIO()
    out.write('\ufeff')
    writer=csv.writer(out)
    writer.writerow(['层级节点','提前量(分钟)','偏相关门槛','站点','有效配对','原始相关r','偏相关r','参考p值','是否通过','筛选说明'])
    for level in c.briefing.get('levels',[]):
        stations=level.get('stations',[])
        if not stations:
            writer.writerow([safe(level['name']),level['lead_minutes'],level['threshold'],'（无候选站点）',0,'','','','未通过',safe(level.get('status')=='empty' and '空候选明确结束' or '')])
        for s in stations:
            writer.writerow([safe(level['name']),level['lead_minutes'],level['threshold'],safe(s.get('station','')),s.get('pairs') or 0,
                             s.get('raw') if s.get('raw') is not None else '',s.get('partial') if s.get('partial') is not None else '',
                             s.get('p') if s.get('p') is not None else '','通过' if s.get('passed') else '未通过',safe(s.get('note') or '')])
    return out.getvalue().encode('utf-8'), {'chain':c.name,'briefing':c.briefing}
def deliver(db, report):
    payload=_chain_payload(db,report) if report.chain_id else _job_payload(db,report)
    if payload is None: return
    data,meta=payload
    delivery=Delivery(report_id=report.id, created_at=time.time(), checksum=hashlib.sha256(data).hexdigest(), filename='', destination=report.destination)
    db.add(delivery); db.flush()
    delivery.filename=f'report-{report.id}-delivery-{delivery.id}.csv'
    os.makedirs(ARTIFACT_DIR,exist_ok=True)
    with open(os.path.join(ARTIFACT_DIR,delivery.filename),'wb') as f:f.write(data)
    with open(os.path.join(ARTIFACT_DIR,delivery.filename+'.json'),'w') as f: json.dump({**meta,'checksum':delivery.checksum},f,ensure_ascii=False,allow_nan=False)
    report.next_run=time.time()+report.interval_seconds
    return delivery
