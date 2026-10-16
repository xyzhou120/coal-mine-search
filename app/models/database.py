"""
SQLAlchemy 数据库模型定义
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Integer, Text, DateTime, Boolean, Float,
    UniqueConstraint, Index, ForeignKey, func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class CoalMine(Base):
    """煤矿主表"""
    __tablename__ = "coal_mines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mine_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="煤矿编码")
    mine_name: Mapped[str] = mapped_column(String(256), nullable=False, comment="煤矿名称")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    documents: Mapped[list["DocumentIndex"]] = relationship(
        "DocumentIndex", back_populates="mine", foreign_keys="DocumentIndex.mine_code",
        primaryjoin="CoalMine.mine_code == DocumentIndex.mine_code"
    )


class ListType(Base):
    """清单类型表（上报文件类型）"""
    __tablename__ = "list_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_name_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="清单类型ID")
    file_name: Mapped[str] = mapped_column(String(512), nullable=False, comment="清单类型名称")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())


class DocumentIndex(Base):
    """
    文档索引映射表（核心表）
    记录每份文件的元数据、PageIndex doc_id 和处理状态
    """
    __tablename__ = "document_index"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # --- 业务元数据（来自 Excel）---
    attachment_id: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, comment="附件ID（Excel attachment_id）"
    )
    attachment_name: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="附件名称"
    )
    attachment_link: Mapped[str] = mapped_column(
        Text, nullable=False, comment="MinIO HTTPS 文件地址"
    )
    mine_code: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="煤矿编码"
    )
    mine_name: Mapped[str] = mapped_column(
        String(256), nullable=False, comment="煤矿名称"
    )
    file_name_id: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="清单类型ID"
    )
    file_name: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="清单类型名称"
    )
    report_time: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="上报时间"
    )
    # update_rate=0 时由 cycle 枚举代表频率（日/周/旬/月/季/半年/年）
    # update_rate!=0 时数值 1/7/10/30/90/180/360 代表上报频率
    update_rate: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="更新频率数值（0=由cycle决定）"
    )
    cycle: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, comment="上报周期（日/周/旬/月/季/半年/年）"
    )
    # 解析后的可读频率描述，方便展示和检索
    frequency_label: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True, comment="上报频率标签（日报/周报/月报等）"
    )

    # --- 文件处理信息 ---
    file_type: Mapped[Optional[str]] = mapped_column(
        String(16), nullable=True, comment="文件类型：pdf/word/excel/unknown"
    )
    page_count: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="文档页数"
    )
    ocr_required: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否需要 OCR 处理"
    )

    # --- PageIndex 索引信息 ---
    doc_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True, comment="PageIndex doc_id"
    )

    # --- 处理状态 ---
    # pending: 等待处理
    # downloading: 下载中
    # processing: OCR/转换处理中
    # indexing: 建立索引中
    # completed: 完成
    # failed: 失败
    status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False, comment="处理状态"
    )
    error_msg: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="失败原因"
    )
    retry_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="已重试次数"
    )

    # --- 时间戳 ---
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    indexed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, comment="索引完成时间"
    )

    # --- 关联 ---
    mine: Mapped["CoalMine"] = relationship(
        "CoalMine", back_populates="documents",
        primaryjoin="DocumentIndex.mine_code == CoalMine.mine_code",
        foreign_keys=[mine_code]
    )

    __table_args__ = (
        Index("idx_mine_code", "mine_code"),
        Index("idx_mine_list", "mine_code", "file_name_id"),
        Index("idx_mine_list_time", "mine_code", "file_name_id", "report_time"),
        Index("idx_status", "status"),
        Index("idx_doc_id", "doc_id"),
    )


class ImportTask(Base):
    """
    Excel 导入任务记录表
    每次上传 Excel 文件创建一条记录，追踪整体导入进度
    """
    __tablename__ = "import_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, comment="任务ID（UUID）"
    )
    file_name: Mapped[str] = mapped_column(
        String(256), nullable=False, comment="上传的 Excel 文件名"
    )
    file_path: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Excel 文件保存路径"
    )

    # 进度统计
    total_count: Mapped[int] = mapped_column(Integer, default=0, comment="解析出的总文件数")
    pending_count: Mapped[int] = mapped_column(Integer, default=0, comment="待处理数")
    processing_count: Mapped[int] = mapped_column(Integer, default=0, comment="处理中数")
    completed_count: Mapped[int] = mapped_column(Integer, default=0, comment="完成数")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, comment="失败数")
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, comment="跳过数（已存在）")

    # 任务状态
    # created: 已创建
    # parsing: 解析Excel中
    # processing: 批量处理中
    # completed: 全部完成
    # partial: 部分完成（有失败）
    # failed: 解析失败
    status: Mapped[str] = mapped_column(String(32), default="created", comment="任务状态")
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="任务级别错误")

    celery_task_id: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, comment="Celery 批次任务 ID"
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
