import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','chain_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
def chain_dict(c, counts=None):
    d={k:getattr(c,k) for k in ['id','name','dataset_id','status','approved','approved_by','approved_at','created_at','started_at','finished_at','dataset_checksum']}
    if counts is not None: d['counts']=counts
    return d
def chain_node_dict(n, extra=None):
    d={k:getattr(n,k) for k in ['id','key','name','lag','threshold','status','result','error','generation','started_at','finished_at']}
    if extra: d.update(extra)
    return d
