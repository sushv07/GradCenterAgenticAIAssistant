"""
api — thin FastAPI service layer exposing the existing backend over HTTP.

  app.py — the FastAPI app: POST /query, GET /health, GET /. No business
           logic lives here — every route calls straight into
           backend.entrypoint.handle_user_query() and returns its result
           unmodified.
"""
