"""研究链：多级复核的编排、冻结启动、按依赖调度、补跑失效与整链批准。"""
import time, json, logging
from fastapi import HTTPException
from sqlalchemy import select, update, delete
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Chain, ChainNode, ChainEdge, Dataset, Report
from src.services.business import evaluate_chain_node
from src.services.audit import record
from src.utils.serialization import chain_dict, chain_node_dict

TERMINAL = ('completed', 'empty', 'failed', 'blocked')
SUCCESS = ('completed', 'empty')  # 空候选也是明确结束，后代继续推进（候选为空）


def enqueue(chain_id):
    try:
        r = Redis.from_url(REDIS_URL); r.rpush('chain:queue', chain_id); r.close()
    except Exception:
        pass  # SQL running 状态是持久兜底，worker 周期扫描会接管


def find_cycle(keys, edges):
    """Kahn 拓扑排序；存在环路返回环上节点标识列表，否则 None。"""
    indeg = {k: 0 for k in keys}
    adj = {k: [] for k in keys}
    for e in edges:
        adj[e.from_key].append(e.to_key)
        indeg[e.to_key] += 1
    queue, seen = [k for k, d in indeg.items() if d == 0], 0
    while queue:
        for nxt in adj[queue.pop()]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
        seen += 1
    return sorted(k for k, d in indeg.items() if d > 0) if seen != len(keys) else None


def _validate_definition(db, data):
    if not db.get(Dataset, data.dataset_id):
        raise HTTPException(404, '数据批次不存在')
    keys = [n.key for n in data.nodes]
    if len(set(keys)) != len(keys):
        raise HTTPException(422, '节点标识重复；按标识幂等，重试不会重复建节点')
    for e in data.edges:
        if e.from_key == e.to_key:
            raise HTTPException(422, '节点不能依赖自身')
        if e.from_key not in keys or e.to_key not in keys:
            raise HTTPException(422, '依赖边引用了不存在的节点标识')
    if len({(e.from_key, e.to_key) for e in data.edges}) != len(data.edges):
        raise HTTPException(422, '依赖边重复')


def _persist_graph(db, chain, data):
    for n in data.nodes:
        db.add(ChainNode(chain_id=chain.id, key=n.key, name=n.name.strip(), lag=n.lag, threshold=n.threshold))
    for e in data.edges:
        db.add(ChainEdge(chain_id=chain.id, from_key=e.from_key, to_key=e.to_key))
    db.flush()


def create(db, data, user):
    _validate_definition(db, data)
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(422, '研究链名称去除空格后至少需要两个字符')
    if db.scalar(select(Chain).where(Chain.name == name)):
        raise HTTPException(409, '研究链名称已存在，重复提交不会重建')
    c = Chain(name=name, dataset_id=data.dataset_id, status='draft', created_by=user.id, created_at=time.time())
    db.add(c); db.flush()
    _persist_graph(db, c, data)
    return c


def replace(db, chain, data):
    if chain.status != 'draft':
        raise HTTPException(409, '仅编排中的研究链可以修改；启动后样本、参数与依赖已冻结')
    _validate_definition(db, data)
    name = data.name.strip()
    if db.scalar(select(Chain).where(Chain.name == name, Chain.id != chain.id)):
        raise HTTPException(409, '研究链名称已存在')
    chain.name = name
    chain.dataset_id = data.dataset_id
    db.execute(delete(ChainEdge).where(ChainEdge.chain_id == chain.id))
    db.execute(delete(ChainNode).where(ChainNode.chain_id == chain.id))
    _persist_graph(db, chain, data)
    return chain


def start(db, chain):
    """启动：校验环路，冻结样本快照、参数与依赖；重复启动拒绝。"""
    if chain.status != 'draft':
        raise HTTPException(409, '研究链已启动，重复启动无效')
    nodes = db.scalars(select(ChainNode).where(ChainNode.chain_id == chain.id)).all()
    edges = db.scalars(select(ChainEdge).where(ChainEdge.chain_id == chain.id)).all()
    if not nodes:
        raise HTTPException(422, '至少需要一个研究节点')
    cycle = find_cycle([n.key for n in nodes], edges)
    if cycle:
        raise HTTPException(422, '研究链存在环路（' + '、'.join(cycle) + '），拒绝启动')
    d = db.get(Dataset, chain.dataset_id)
    if not d:
        raise HTTPException(404, '数据批次不存在')
    chain.records = d.records
    chain.dataset_checksum = d.checksum
    chain.status = 'running'
    chain.started_at = time.time()
    chain.finished_at = None
    chain.approved = False
    chain.approved_by = ''
    chain.approved_at = None
    chain.briefing = {}
    for n in nodes:
        n.status = 'pending'; n.result = {}; n.error = ''
        n.generation += 1; n.started_at = None; n.finished_at = None
    db.flush()
    return len(nodes)


def _descendants(key, edges):
    adj = {}
    for e in edges:
        adj.setdefault(e.from_key, []).append(e.to_key)
    seen, stack = set(), [key]
    while stack:
        for nxt in adj.get(stack.pop(), []):
            if nxt not in seen:
                seen.add(nxt); stack.append(nxt)
    return seen


def rerun(db, chain, node):
    """补跑：目标节点与其全部后代失效（代次递增、结果清空），在途旧结果不再写回。"""
    if chain.status == 'draft':
        raise HTTPException(409, '研究链尚未启动')
    if node.status not in ('completed', 'empty', 'failed'):
        raise HTTPException(409, '仅已结束的节点可以补跑；被阻塞的节点请先补跑失败的前置')
    edges = db.scalars(select(ChainEdge).where(ChainEdge.chain_id == chain.id)).all()
    nodes = {n.key: n for n in db.scalars(select(ChainNode).where(ChainNode.chain_id == chain.id))}
    revoked = chain.approved
    if chain.approved:
        chain.approved = False; chain.approved_by = ''; chain.approved_at = None; chain.briefing = {}
        # 简报随补跑失效：引用该链的启用中分发计划自动停用，待重新批准后人工启用
        db.execute(update(Report).where(Report.chain_id == chain.id, Report.enabled == True).values(enabled=False))
    chain.status = 'running'
    chain.finished_at = None
    affected = []
    for key in [node.key] + sorted(_descendants(node.key, edges)):
        n = nodes[key]
        if key != node.key and n.status == 'pending':
            continue  # 未出结果的后代无需失效
        n.generation += 1
        n.status = 'pending'; n.result = {}; n.error = ''
        n.started_at = None; n.finished_at = None
        affected.append(n.key)
    db.flush()
    return affected, revoked


def approve(db, chain, user):
    """整链完成才可批准；批准时固定各级采用结果为简报。节点不能单独批准。"""
    if chain.status != 'completed':
        raise HTTPException(409, '整链完成后才能批准分发；存在失败或阻塞节点时请先补跑前置')
    if chain.approved:
        raise HTTPException(409, '研究链已批准，简报已固定')
    nodes = db.scalars(select(ChainNode).where(ChainNode.chain_id == chain.id).order_by(ChainNode.id)).all()
    chain.approved = True
    chain.approved_by = user.email
    chain.approved_at = time.time()
    chain.briefing = build_briefing(chain, nodes)
    return chain


def build_briefing(chain, nodes):
    return {'chain': chain.name, 'chain_id': chain.id, 'dataset_checksum': chain.dataset_checksum,
            'approved_by': chain.approved_by, 'approved_at': chain.approved_at,
            'levels': [{'key': n.key, 'name': n.name, 'lag': n.lag, 'lead_minutes': n.lag * 30,
                        'threshold': n.threshold, 'status': n.status,
                        'passed': n.result.get('passed', []), 'stations': n.result.get('stations', [])} for n in nodes]}


def claim_next(db, chain_id):
    """阻塞传播后领取一个可执行节点（前置全部通过的 pending 节点）。返回节点 id 或 None。"""
    nodes = db.scalars(select(ChainNode).where(ChainNode.chain_id == chain_id).order_by(ChainNode.id)).all()
    if not nodes:
        return None
    edges = db.scalars(select(ChainEdge).where(ChainEdge.chain_id == chain_id)).all()
    by_key = {n.key: n for n in nodes}
    preds = {n.key: [by_key[e.from_key] for e in edges if e.to_key == n.key and e.from_key in by_key] for n in nodes}
    # 前置失败只阻塞后代：前置全部终态且含失败/阻塞时标记 blocked，并沿链传播
    for _ in range(len(nodes)):
        changed = False
        for n in nodes:
            ps = preds[n.key]
            if n.status == 'pending' and ps and all(p.status in TERMINAL for p in ps) and any(p.status in ('failed', 'blocked') for p in ps):
                n.status = 'blocked'
                n.error = '前置失败：' + '、'.join(p.name for p in ps if p.status in ('failed', 'blocked'))
                n.finished_at = time.time()
                record(db, 'worker', 'chain.node.blocked', {'chain': chain_id, 'node': n.key, 'reason': n.error})
                changed = True
        if not changed:
            break
    db.flush()
    for n in nodes:
        if n.status == 'pending' and all(p.status in SUCCESS for p in preds[n.key]):
            claimed = db.execute(
                update(ChainNode).where(ChainNode.id == n.id, ChainNode.status == 'pending')
                .values(status='running', started_at=time.time())).rowcount
            if claimed:
                return n.id
    return None


def run_node(node_id):
    """执行已领取节点；写回按代次守卫，补跑后的在途旧结果不再写回。"""
    with Session() as db:
        node = db.get(ChainNode, node_id)
        if not node or node.status != 'running':
            return
        generation, chain_id, key = node.generation, node.chain_id, node.key
        chain = db.get(Chain, chain_id)
        edges = db.scalars(select(ChainEdge).where(ChainEdge.chain_id == chain_id)).all()
        nodes = {n.key: n for n in db.scalars(select(ChainNode).where(ChainNode.chain_id == chain_id))}
        pred_keys = [e.from_key for e in edges if e.to_key == key]
        if pred_keys:
            # 后继只研究所有前置共同通过的站点
            candidates = sorted(set.intersection(*[set(nodes[k].result.get('passed', [])) for k in pred_keys]))
        else:
            candidates = sorted({str(r.get('station')) for r in chain.records})
        if not candidates:
            status, result, error = 'empty', {'candidates': [], 'passed': [], 'stations': [],
                                              'reason': '所有前置共同通过的站点为空' if pred_keys else '冻结样本中没有可研究站点'}, ''
        else:
            try:
                outcome = evaluate_chain_node(chain.records, candidates, node.lag, node.threshold)
                json.dumps(outcome, allow_nan=False)
                status, result, error = 'completed', outcome, ''
            except Exception as e:
                logging.exception('Chain node failed')
                status, result, error = 'failed', {}, str(e)[:990]
    with Session() as db:
        updated = db.execute(
            update(ChainNode).where(ChainNode.id == node_id, ChainNode.generation == generation, ChainNode.status == 'running')
            .values(status=status, result=result, error=error, finished_at=time.time())).rowcount
        if updated:
            record(db, 'worker', 'chain.node.' + status, {'chain': chain_id, 'node': key, 'passed': len(result.get('passed', []))})
        else:
            record(db, 'worker', 'chain.node.stale', {'chain': chain_id, 'node': key, 'note': '在途旧结果已按代次丢弃'})
        db.commit()


def finalize(db, chain_id):
    """无待执行节点时收尾：全部通过为 completed，否则 failed。"""
    chain = db.get(Chain, chain_id)
    if not chain or chain.status != 'running':
        return False
    nodes = db.scalars(select(ChainNode).where(ChainNode.chain_id == chain_id)).all()
    if not nodes or any(n.status in ('pending', 'running') for n in nodes):
        return False
    chain.status = 'completed' if all(n.status in SUCCESS for n in nodes) else 'failed'
    chain.finished_at = time.time()
    record(db, 'worker', 'chain.' + chain.status, {'id': chain_id})
    return True


def counts(nodes):
    c = {'total': len(nodes), 'pending': 0, 'running': 0, 'completed': 0, 'empty': 0, 'failed': 0, 'blocked': 0}
    for n in nodes:
        c[n.status] = c.get(n.status, 0) + 1
    return c


def detail_payload(db, chain):
    nodes = db.scalars(select(ChainNode).where(ChainNode.chain_id == chain.id).order_by(ChainNode.id)).all()
    edges = db.scalars(select(ChainEdge).where(ChainEdge.chain_id == chain.id)).all()
    by_key = {n.key: n for n in nodes}
    pred_map, succ_map = {}, {}
    for e in edges:
        pred_map.setdefault(e.to_key, []).append(e.from_key)
        succ_map.setdefault(e.from_key, []).append(e.to_key)
    payload_nodes = []
    for n in nodes:
        ps = [by_key[k] for k in pred_map.get(n.key, []) if k in by_key]
        extra = {'predecessors': [{'key': p.key, 'name': p.name, 'status': p.status} for p in ps],
                 'successors': sorted(succ_map.get(n.key, [])),
                 'expected_candidates': None}
        if chain.status != 'draft' and n.status == 'pending' and all(p.status in SUCCESS for p in ps):
            extra['expected_candidates'] = sorted(set.intersection(*[set(p.result.get('passed', [])) for p in ps])) if ps else sorted({str(r.get('station')) for r in chain.records})
        payload_nodes.append(chain_node_dict(n, extra))
    if chain.records:
        stations = sorted({str(r.get('station')) for r in chain.records})
        sample_rows = len(chain.records)
    else:
        d = db.get(Dataset, chain.dataset_id)
        stations = sorted({str(r.get('station')) for r in d.records}) if d else []
        sample_rows = len(d.records) if d else 0
    payload = chain_dict(chain, counts(nodes))
    payload.update({'nodes': payload_nodes,
                    'edges': [{'from_key': e.from_key, 'to_key': e.to_key} for e in edges],
                    'stations': stations, 'sample_rows': sample_rows,
                    'briefing': chain.briefing or None})
    return payload
