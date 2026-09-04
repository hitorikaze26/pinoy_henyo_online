"""Raw SQL query helpers.

Provides ``query_one``, ``query_all``, and ``execute`` for use by the
repository layer.  All functions work on the Flask-SQLAlchemy session so
transactions, commits, and rollbacks are handled automatically.

The helpers return plain dictionaries (``dict``) so callers never depend
on SQLAlchemy ORM model objects.
"""

from .extensions import db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row):
    """Convert a SQLAlchemy Row proxy to a plain dict."""
    if row is None:
        return None
    return dict(row._mapping)


def _rows_to_dicts(rows):
    """Convert a list of Row proxies to a list of dicts."""
    return [dict(r._mapping) for r in rows]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def query_one(sql, params=None):
    """Execute *sql* and return the first result row as a ``dict``, or ``None``."""
    result = db.session.execute(db.text(sql), params or {})
    row = result.first()
    return _row_to_dict(row)


def query_all(sql, params=None):
    """Execute *sql* and return all result rows as a list of ``dict``."""
    result = db.session.execute(db.text(sql), params or {})
    return _rows_to_dicts(result.fetchall())


def execute(sql, params=None):
    """Execute a non-SELECT statement (INSERT / UPDATE / DELETE).

    Returns the number of affected rows.
    """
    result = db.session.execute(db.text(sql), params or {})
    return result.rowcount


def insert(sql, params=None, pk_column="id"):
    """Execute an INSERT and return the generated primary key (if any).

    MySQL/SQLite expose the generated id via ``result.lastrowid``. PostgreSQL
    (psycopg2) does not populate ``lastrowid`` for SERIAL/IDENTITY columns, so
    a ``RETURNING <pk_column>`` clause is appended for the ``postgresql``
    dialect instead. Override ``pk_column`` for tables whose primary key is not
    named ``id``.
    """
    params = params or {}
    if db.engine.dialect.name == "postgresql":
        stmt = sql.rstrip().rstrip(";") + " RETURNING " + pk_column
        result = db.session.execute(db.text(stmt), params)
        row = result.first()
        return row[pk_column] if row is not None else None
    result = db.session.execute(db.text(sql), params)
    return result.lastrowid


def flush():
    """Flush pending writes without committing.

    Useful for obtaining auto-generated PKs inside a transaction.
    """
    db.session.flush()


def commit():
    """Manually commit the current transaction."""
    db.session.commit()


def rollback():
    """Manually roll back the current transaction."""
    db.session.rollback()
