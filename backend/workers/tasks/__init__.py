"""Celery task definitions.

Tasks are registered with the Celery app via ``include=[...]`` in
``workers.celery_app`` (not by importing them here), so this package stays a plain
namespace and registration order is deterministic.
"""
