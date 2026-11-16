from sqlalchemy import inspect, text
from src.config.database import Base, engine
from src import models
def migrate():
    Base.metadata.create_all(engine)
    # 老库幂等升级：reports 增加研究链来源，job_id 放宽为可空
    with engine.begin() as conn:
        cols={c['name']:c for c in inspect(conn).get_columns('reports')}
        if 'chain_id' not in cols:
            conn.execute(text('ALTER TABLE reports ADD COLUMN chain_id INTEGER'))
        if cols.get('job_id') and not cols['job_id']['nullable']:
            try:
                conn.execute(text('ALTER TABLE reports ALTER COLUMN job_id DROP NOT NULL'))
            except Exception:
                pass  # SQLite 旧库请删除后重建；新建库已默认可空
if __name__=='__main__':migrate()
