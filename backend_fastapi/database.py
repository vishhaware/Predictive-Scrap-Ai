import os
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError, InterfaceError
from sqlalchemy.orm import Session
try:
    from .models import Base
except ImportError:
    from models import Base
import time
import functools

# Default to SQLite for zero-config startup, or use Postgres if DATABASE_URL is set
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    DB_PATH = os.path.join(os.path.dirname(__file__), "factory_brain_fastapi.db")
    DATABASE_URL = f"sqlite:///{DB_PATH}"
    print(f"📦 Using Local SQLite: {DB_PATH}")
else:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    print(f"🗄️ Using Database: {DATABASE_URL.split('@')[-1]}")

IS_SQLITE = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL, 
    connect_args=(
        {"check_same_thread": False, "timeout": 30}
        if IS_SQLITE
        else {}
    ),
    pool_pre_ping=True
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _sqlite_table_exists(conn, table_name: str) -> bool:
    rows = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:table_name"),
        {"table_name": table_name},
    ).fetchall()
    return bool(rows)


def _sqlite_table_columns(conn, table_name: str):
    return [row[1] for row in conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()]


def _apply_sqlite_compat_migrations():
    """
    Lightweight compatibility migrations for SQLite installations where
    create_all(checkfirst=True) cannot add newly introduced columns.
    """
    if not IS_SQLITE:
        return

    machine_stats_columns = {
        "last_status": "VARCHAR DEFAULT 'ok'",
        "last_oee": "INTEGER DEFAULT 0",
        "last_temp": "FLOAT DEFAULT 230.0",
        "last_cushion": "FLOAT DEFAULT 0.0",
        "last_cycles_count": "INTEGER DEFAULT 0",
        "abnormal_params": "JSON",
        "maintenance_urgency": "VARCHAR DEFAULT 'LOW'",
        "last_part_number": "VARCHAR",
    }

    with engine.begin() as conn:
        if not _sqlite_table_exists(conn, "machine_stats"):
            return

        existing = set(_sqlite_table_columns(conn, "machine_stats"))
        for column_name, column_sql in machine_stats_columns.items():
            if column_name in existing:
                continue
            conn.execute(text(f"ALTER TABLE machine_stats ADD COLUMN {column_name} {column_sql}"))
            print(f"🛠️ SQLite migration: added machine_stats.{column_name}")

def force_rebuild_engine():
    """If not connected, rebuilds the connection engine entirely."""
    global engine, SessionLocal
    print("🚧 Forcing absolute database engine rebuild...")
    try:
        engine.dispose()
    except Exception:
        pass
    
    engine = create_engine(
        DATABASE_URL, 
        connect_args=(
            {"check_same_thread": False, "timeout": 30}
            if IS_SQLITE
            else {}
        ),
        pool_pre_ping=True
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    print("✅ Engine rebuild requested.")

if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=30000;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

def with_reconnect(max_retries=3, delay=1):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_ex = None
            for i in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (OperationalError, InterfaceError) as e:
                    last_ex = e
                    print(f"🔄 Connection issue detected. Retry {i+1}/{max_retries} for {func.__name__}...")
                    time.sleep(delay * (2 ** i)) # Exponential backoff
            print(f"❌ Failed after {max_retries} retries.")
            raise last_ex
        return wrapper
    return decorator

def init_db():
    try:
        # Check connection before creating tables
        if not check_db_connection():
            print("⚠ Database not reachable at startup. Attempting creation anyway...")
        Base.metadata.create_all(bind=engine, checkfirst=True)
        _apply_sqlite_compat_migrations()
    except OperationalError as exc:
        if "already exists" in str(exc).lower():
            print("⚠ DB init race detected (table already exists). Continuing startup.")
            return
        raise

def get_db():
    """Dependency for structured DB sessions with health checks."""
    db = SessionLocal()
    try:
        # Proactive check before yielding to FastAPI route
        db.execute(text("SELECT 1"))
        yield db
    except (OperationalError, InterfaceError):
        print("🔌 Session stale. Attempting refresh...")
        db.close()
        db = SessionLocal() # Try once to refresh
        yield db
    finally:
        db.close()

def check_db_connection(auto_repair=True) -> bool:
    """Verifies that the database is reachable and responding. Rebuilds if down."""
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"❌ Database connection check failed: {e}")
        db.close()
        if auto_repair:
            force_rebuild_engine()
            # Verify once more after rebuild
            try:
                test_db = SessionLocal()
                test_db.execute(text("SELECT 1"))
                test_db.close()
                print("✅ Database repaired and successfully connected.")
                return True
            except Exception:
                print("❌ Database still unreachable after absolute rebuild.")
                return False
        return False
    finally:
        try:
            db.close()
        except Exception:
            pass
