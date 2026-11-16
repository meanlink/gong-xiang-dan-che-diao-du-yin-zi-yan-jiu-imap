from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from src.config.database import get_db
from src.models import Chain, ChainNode, ChainEdge
from src.schemas.chain import ChainInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import chains as service
from src.services.audit import record
from src.utils.serialization import chain_dict
router=APIRouter(prefix='/chains')
@router.get('')
def listing(db=Depends(get_db),u=Depends(current_user)):
    out=[]
    for c in db.scalars(select(Chain).order_by(Chain.id.desc()).limit(100)):
        nodes=db.scalars(select(ChainNode).where(ChainNode.chain_id==c.id)).all()
        out.append(chain_dict(c,service.counts(nodes)))
    return out
@router.post('',status_code=201)
def create(data:ChainInput,db=Depends(get_db),u=Depends(can_write)):
    c=service.create(db,data,u); record(db,u.email,'chain.create',{'id':c.id,'nodes':len(data.nodes),'edges':len(data.edges)})
    db.commit(); return service.detail_payload(db,c)
@router.get('/{id}')
def detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    c=db.get(Chain,id)
    if not c: raise HTTPException(404,'研究链不存在')
    return service.detail_payload(db,c)
@router.put('/{id}')
def replace(id:int,data:ChainInput,db=Depends(get_db),u=Depends(can_write)):
    c=db.get(Chain,id)
    if not c: raise HTTPException(404,'研究链不存在')
    service.replace(db,c,data); record(db,u.email,'chain.update',{'id':id,'nodes':len(data.nodes),'edges':len(data.edges)})
    db.commit(); return service.detail_payload(db,c)
@router.delete('/{id}')
def remove(id:int,db=Depends(get_db),u=Depends(can_write)):
    c=db.get(Chain,id)
    if not c: raise HTTPException(404,'研究链不存在')
    if c.status!='draft': raise HTTPException(409,'仅编排中的研究链可以删除；已启动的链保留复核轨迹')
    db.execute(delete(ChainEdge).where(ChainEdge.chain_id==id))
    db.execute(delete(ChainNode).where(ChainNode.chain_id==id))
    db.delete(c); record(db,u.email,'chain.delete',{'id':id}); db.commit()
    return {'deleted':id}
@router.post('/{id}/start')
def start(id:int,db=Depends(get_db),u=Depends(can_write)):
    c=db.get(Chain,id)
    if not c: raise HTTPException(404,'研究链不存在')
    n=service.start(db,c); record(db,u.email,'chain.start',{'id':id,'nodes':n,'checksum':c.dataset_checksum})
    db.commit(); service.enqueue(id)
    return service.detail_payload(db,c)
@router.post('/{id}/nodes/{node_id}/rerun')
def rerun(id:int,node_id:int,db=Depends(get_db),u=Depends(can_write)):
    c=db.get(Chain,id)
    if not c: raise HTTPException(404,'研究链不存在')
    node=db.get(ChainNode,node_id)
    if not node or node.chain_id!=id: raise HTTPException(404,'研究节点不存在')
    affected,revoked=service.rerun(db,c,node)
    record(db,u.email,'chain.node.rerun',{'chain':id,'node':node.key,'invalidated':affected})
    if revoked: record(db,u.email,'chain.approval_revoked',{'id':id})
    db.commit(); service.enqueue(id)
    return service.detail_payload(db,c)
@router.post('/{id}/approve')
def approve(id:int,db=Depends(get_db),u=Depends(admin_only)):
    c=db.get(Chain,id)
    if not c: raise HTTPException(404,'研究链不存在')
    service.approve(db,c,u); record(db,u.email,'chain.approve',{'id':id,'levels':len(c.briefing.get('levels',[]))})
    db.commit(); return service.detail_payload(db,c)
