"""
数据库连接和会话管理
"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import create_engine
from app.config import get_settings

settings = get_settings()

# 异步引擎（FastAPI 使用）
async_engine = create_async_engine(
    settings.database_url,
    echo=settings.app_debug,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# 同步引擎（Celery Worker 使用）
sync_database_url = settings.database_url.replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)
sync_engine = create_engine(
    sync_database_url,
    echo=settings.app_debug,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入，获取异步数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """初始化数据库，创建所有表"""
    from app.models.database import Base
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
