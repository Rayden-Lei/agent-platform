from app.core.security import hash_password
from app.db.base import Base
from app.db.models import Agent, ModelConfig, User  # noqa: F401
from app.db.session import SessionLocal, engine


def main():
    Base.metadata.create_all(engine)
    print("tables created")
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.username == "admin").first():
            u = User(username="admin", password_hash=hash_password("admin123"), role="admin")
            db.add(u)
            db.commit()
            print("created admin user: admin / admin123")
        else:
            print("admin user already exists")
    finally:
        db.close()


if __name__ == "__main__":
    main()
