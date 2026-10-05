from app.db.base import Base
from app.db.models import Agent, ModelConfig, User  # noqa: F401
from app.db.session import SessionLocal, engine
from app.services.user_service import ensure_initial_admin


def main():
    Base.metadata.create_all(engine)
    print("tables created")
    db = SessionLocal()
    try:
        # 与应用启动同一套规则（docs/15 OP-04）：口令取 INITIAL_ADMIN_PASSWORD，没配置时用内置默认口令并要求首次登录改密；不打印口令
        source = ensure_initial_admin(db)
        if source == "configured":
            print("created admin user (password from INITIAL_ADMIN_PASSWORD)")
        elif source == "default":
            print("created admin user with the built-in default password; it must be changed at first login")
        else:
            print("admin user already exists")
    finally:
        db.close()


if __name__ == "__main__":
    main()
