from __future__ import annotations

"""
Shared context for pipeline runs.
"""

from pathlib import Path

from sqlalchemy.orm import Session

from database.db import Base, SessionLocal, engine


class PipelineContext:
    """
    Holds shared resources for a single pipeline run, like a DB session.
    Manages resource setup and teardown.
    """

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.db_session: Session | None = None
        self.project_root = self._project_root()

    @staticmethod
    def _project_root() -> Path:
        # .../pipeline/orchestrator/context.py -> project root
        return Path(__file__).resolve().parents[2]

    def __enter__(self) -> PipelineContext:
        Base.metadata.create_all(bind=engine)
        self.db_session = SessionLocal()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.db_session is None:
            return

        try:
            if exc_type is not None:
                print(f"Pipeline failed with an exception, rolling back DB changes.")
                self.db_session.rollback()
            else:
                if self.dry_run:
                    print("Dry run: rolling back DB changes.")
                    self.db_session.rollback()
                else:
                    print("Committing DB changes.")
                    self.db_session.commit()
        finally:
            self.db_session.close()
