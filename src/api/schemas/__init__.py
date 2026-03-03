"""Pydantic request and response models scoped to the HTTP API surface.

Schema classes in this package model the JSON (or form-encoded) payloads
exchanged between clients and the FastAPI routers.  They are distinct from
domain entities and application DTOs — conversions happen in the router layer.

Conventions
-----------
* Request schemas are suffixed ``Request`` (e.g. ``LoginRequest``).
* Response schemas are suffixed ``Response`` (e.g. ``UserResponse``).
* Schemas never import from ``src.infrastructure`` or ``src.domain`` directly;
  they are pure Pydantic models with no ORM or DB coupling.
* ``model_config = ConfigDict(from_attributes=True)`` is set where the schema
  needs to be constructed from a domain entity or SQLModel row.
"""
