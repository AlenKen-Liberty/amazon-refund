from src.db.connection import db
from src.db.migrations import create_tables


def main() -> None:
    db.init_pool()
    create_tables(db)
    db.close()


if __name__ == "__main__":
    main()
