from sqlalchemy import String, JSON, Double, ForeignKey, Boolean, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Chain(Base):
    __tablename__ = 'chains'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    status: Mapped[str] = mapped_column(String(20), default='draft')  # draft/running/completed/failed
    records: Mapped[list] = mapped_column(JSON, default=list)  # 启动时冻结的样本快照
    dataset_checksum: Mapped[str] = mapped_column(String(64), default='')
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_by: Mapped[str] = mapped_column(String(150), default='')
    approved_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    briefing: Mapped[dict] = mapped_column(JSON, default=dict)  # 批准时固定的各级采用结果
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    created_at: Mapped[float] = mapped_column(Double)
    started_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
class ChainNode(Base):
    __tablename__ = 'chain_nodes'
    __table_args__ = (UniqueConstraint('chain_id', 'key', name='uq_chain_node_key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    chain_id: Mapped[int] = mapped_column(ForeignKey('chains.id'))
    key: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(160))
    lag: Mapped[int] = mapped_column(Integer)
    threshold: Mapped[float] = mapped_column(Double)
    status: Mapped[str] = mapped_column(String(20), default='pending')  # pending/running/completed/empty/failed/blocked
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    generation: Mapped[int] = mapped_column(Integer, default=1)  # 代次：补跑使后代失效，在途旧结果按代次拒绝写回
    started_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
class ChainEdge(Base):
    __tablename__ = 'chain_edges'
    __table_args__ = (UniqueConstraint('chain_id', 'from_key', 'to_key', name='uq_chain_edge'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    chain_id: Mapped[int] = mapped_column(ForeignKey('chains.id'))
    from_key: Mapped[str] = mapped_column(String(40))
    to_key: Mapped[str] = mapped_column(String(40))
