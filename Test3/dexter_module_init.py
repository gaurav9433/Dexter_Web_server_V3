# -*- coding: utf-8 -*-
# !/usr/local/bin/python
"""
dexter_module_init.py — Shared startup initialisation for Dexter HMS modules

Responsibilities:
  - Runs the DB schema migrations once at startup (DB-06).
  - Verifies WAL mode + FK enforcement on all registered databases (DB-01/02).
  - Optionally initialises the logical_params database (required by NVR/DVR
    modules that read integration flags).
  - Optionally creates and returns a BoundedBufferManager instance so callers
    can enqueue telemetry events (DB-03).

Key functions:
  init_dexter_module(use_buffer, use_logical_params)
      → BoundedBufferManager | None
  make_insert_fn(buffer_manager)
      → callable  (the per-module insert_json_to_db wrapper)

Dependencies:
  db_connection.verify_all_databases    — WAL + FK health check
  db_schema_migration.run_all_migrations — versioned schema rollout
  buffer_manager_fix.BoundedBufferManager — bounded telemetry buffer
  logical_params_module                  — integration flag DB

Author: Seple Novaedge Pvt. Ltd.

CQ Sprint B: This module eliminates the identical 8–12 line startup
  boilerplate that was copy-pasted into 14 polling modules:

      run_all_migrations()
      verify_all_databases()
      logical_params_module.initialize_database()
      _buffer_manager = BoundedBufferManager()
      def insert_json_to_db(payload):
          ...

  Replacing all of that with two lines per module:

      from dexter_module_init import init_dexter_module, make_insert_fn
      _buf = init_dexter_module()
      insert_json_to_db = make_insert_fn(_buf)
"""

import json
import logging
from typing import Optional, Union

log = logging.getLogger(__name__)


def init_dexter_module(
    use_buffer:         bool = True,
    use_logical_params: bool = True,
) -> 'Optional[BoundedBufferManager]':
    """
    Run standard Dexter HMS module startup sequence and return the
    BoundedBufferManager instance (or None if use_buffer=False).

    Call once at module level, before any DB access.

    Parameters:
        use_buffer (bool):
            True  — run_all_migrations, verify_all_databases,
                    logical_params.initialize_database (if use_logical_params),
                    and create + return a BoundedBufferManager.
            False — run_all_migrations + verify_all_databases only.
                    Returns None. Use for utility modules (clear_all_data,
                    webdone, webuptonly) that do not enqueue telemetry.

        use_logical_params (bool):
            True  — call logical_params_module.initialize_database().
                    Required by NVR/DVR/BACS modules that read integration
                    flags via logical_params_module.get_parameter().
            False — skip logical_params init (infrastructure modules that
                    do not read integration flags).

    Returns:
        BoundedBufferManager instance if use_buffer=True, else None.

    Example — NVR/DVR module (full init):
        from dexter_module_init import init_dexter_module, make_insert_fn
        _buf = init_dexter_module()
        insert_json_to_db = make_insert_fn(_buf)

    Example — utility module (migrations + WAL only):
        from dexter_module_init import init_dexter_module
        init_dexter_module(use_buffer=False, use_logical_params=False)
    """
    # DB-06: apply any pending schema migrations before touching any database
    from db_schema_migration import run_all_migrations
    run_all_migrations()
    log.debug("[dexter_module_init] Schema migrations applied")

    # DB-01 / DB-02: verify WAL mode + FK enforcement on all registered DBs
    from db_connection import verify_all_databases
    verify_all_databases()
    log.debug("[dexter_module_init] WAL + FK verified on all databases")

    # Logical params DB — needed by modules that check integration flags
    if use_logical_params:
        try:
            import logical_params_module
            logical_params_module.initialize_database()
            log.debug("[dexter_module_init] logical_params DB initialised")
        except Exception as exc:
            log.error("[dexter_module_init] logical_params init failed — %s", exc)

    # DB-03: bounded telemetry buffer
    if use_buffer:
        from buffer_manager_fix import BoundedBufferManager
        buf = BoundedBufferManager()
        log.debug("[dexter_module_init] BoundedBufferManager ready")
        return buf

    return None


def make_insert_fn(buffer_manager: 'BoundedBufferManager') -> callable:
    """
    Return a module-level insert_json_to_db() function bound to the given
    BoundedBufferManager instance.

    The returned function accepts either a JSON string or a dict and enqueues
    it to the bounded buffer (50K row hard cap, DB-03).

    Example:
        _buf = init_dexter_module()
        insert_json_to_db = make_insert_fn(_buf)

        # then anywhere in the module:
        insert_json_to_db(json.dumps({"key": "value"}))
        insert_json_to_db({"key": "value"})   # dict also accepted
    """
    if buffer_manager is None:
        raise ValueError(
            "make_insert_fn() called with buffer_manager=None. "
            "Call init_dexter_module(use_buffer=True) first."
        )

    def insert_json_to_db(payload: 'Union[str, dict]') -> bool:
        """
        Thread-safe, bounded insert into the upload buffer.
        DB-03: enforces 50,000 row hard cap — oldest events auto-purged on overflow.
        Accepts a JSON string or a dict.
        """
        data = json.loads(payload) if isinstance(payload, str) else payload
        return buffer_manager.enqueue(data)

    return insert_json_to_db
