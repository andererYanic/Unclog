"""Per-client artifact store (brief §12, §14).

Layout (one isolated tree per client; nothing is shared across clients)::

    clients/<client_id>/
      raw/<sha256><ext>                 original uploads (immutable)
      sources/<source_id>.json          IngestResult (scrubbed, normalized)
      artifacts/<Entity>/<id>.json      validated schema records + provenance envelope
      audit.jsonl                       append-only log of every write/read/delete

Rules enforced here:
- Only schema-validated models are stored (G1).
- An artifact is owned by the agent that first wrote it; other agents cannot overwrite it
  ("agents never write to another's output", brief §12). New versions keep history.
- Client ids and artifact ids are path-safe; no cross-client access through one store.
"""

from .client_store import (
    ArtifactEnvelope,
    ClientStore,
    OwnershipError,
    delete_client,
)

__all__ = ["ArtifactEnvelope", "ClientStore", "OwnershipError", "delete_client"]
