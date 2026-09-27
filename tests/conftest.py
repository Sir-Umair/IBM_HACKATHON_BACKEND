"""Pytest shared fixtures.

Strategy:
  - The `seeded_db` fixture creates a FRESH in-memory engine per test function.
  - This avoids any cross-test contamination from LangGraph workflow commits.
  - The seed data generation is fast (< 1s), so per-test seeding is fine.
  - The `db` fixture provides an EMPTY in-memory engine for edge-case tests.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base


def _populate(engine):
    """Populate an engine with the standard test dataset."""
    from app.models import db_models  # noqa: F401 — registers all ORM models
    from seed_data import (
        generate_january, generate_february, generate_march,
        CATEGORIES, SUPPLIERS, PRODUCTS,
    )
    from app.models.db_models import Transaction, Category, Supplier, Product

    # Ensure all tables exist on this engine
    Base.metadata.create_all(bind=engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    for c in CATEGORIES:
        session.add(Category(name=c["name"], description=c["description"]))
    for s in SUPPLIERS:
        session.add(Supplier(name=s["name"], category=s["category"]))
    for p in PRODUCTS:
        session.add(Product(
            name=p["name"], category=p["category"],
            base_price=p["base_price"], base_cost=p["base_cost"],
            supplier=p.get("supplier"),
        ))
    for tx_data in generate_january() + generate_february() + generate_march():
        session.add(Transaction(**tx_data))

    session.commit()
    session.close()
    return Session


def _make_engine(name: str = "default"):
    """
    Create a named in-memory SQLite engine.
    Using a named shared-cache URI ensures all sessions share the same DB.
    """
    uri = f"sqlite:///file:{name}?mode=memory&cache=shared&uri=true"
    engine = create_engine(uri, connect_args={"check_same_thread": False, "uri": True})
    return engine


@pytest.fixture(scope="function")
def seeded_db(tmp_path, request):
    """
    Function-scoped: fresh seeded in-memory DB per test.
    Uses a unique name per test to avoid cross-test contamination.
    """
    name = f"test_{request.node.nodeid.replace('/', '_').replace('::', '_').replace('.', '_')}"
    engine = _make_engine(name)
    Session = _populate(engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(scope="function")
def db(request):
    """Empty in-memory DB session for edge-case tests."""
    name = f"empty_{id(request)}"
    engine = _make_engine(name)
    from app.models import db_models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(scope="function")
def seeded_session_factory(request):
    """
    Returns a session factory for use in API test client overrides.
    All sessions from this factory connect to the same named in-memory DB.
    """
    name = f"api_{id(request)}"
    engine = _make_engine(name)
    factory = _populate(engine)
    yield factory
    engine.dispose()
