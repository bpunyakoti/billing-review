"""The decisions you implement.

The graph is already wired. Finish these functions so each check stays in
application code, not in the model. Keep the function names and the failure
codes exactly as written. Use contracts.failed(...) for every failure.
"""
from .contracts import Settings, failed

#class Settings:
#    def __init__(self, max_model_calls=3, token_budget=6000, tokens_reserved_per_call=2000, approval_window=900):
#        self.max_model_calls = max_model_calls
#        self.token_budget = token_budget
#        self.tokens_reserved_per_call = tokens_reserved_per_call
#        self.approval_window = approval_window

#    def __repr__(self):
#        return (f"Settings(max_model_calls={self.max_model_calls}, "
#                f"token_budget={self.token_budget}, "
#                f"tokens_reserved_per_call={self.tokens_reserved_per_call}, "
#                f"approval_window={self.approval_window})")




def load_settings(values: dict | None = None) -> Settings:
    """Build Settings from a dictionary.

    Reject max_model_calls below 1 with ValueError whose message contains
    "at least 1". A zero-call setting must fail before any workflow starts.
    Missing keys keep the Settings defaults: 3 calls, 6000 token budget,
    2000 tokens reserved per call, and a 900 second approval window.
    """
    if values is None:
        values ={}

    max_model_calls = values.get("max_model_calls", 3)
    if max_model_calls < 1:
        raise ValueError("max_model_calls must be at least 1")

    token_budget = values.get("token_budget", 6000)
    tokens_reserved_per_call =values.get("tokens_reserved_per_call", 2000)
    approval_window = values.get("approval_window", 900)

    return Settings(
        max_model_calls=max_model_calls,
        token_budget=token_budget,
        tokens_reserved_per_call=tokens_reserved_per_call,
        approval_window=approval_window,
    )
 

#def failed(error_code, message):
#    """Helper function to raise an exception with a specific error code and message."""
#    raise Exception(f"{error_code}: {message}")


def check_access(principal, tenant_id: str):
    """Return None when this identity may read the case.

    Refuse with failed("ACCESS_DENIED", ...) when the principal's tenant_id
    differs from tenant_id, or when "case:read" is missing from permissions.
    A viewer and another company's employee both stop here, before any model call.
    """
    # Check if the tenant_id matches
    if principal.tenant_id != tenant_id:
        failed("ACCESS_DENIED", "Tenant ID mismatch")

    # Check if "case:read" permission exists
    #permissions = principal("permissions",[])
    if "case:read" not in principal.permissions:
        failed("ACCESS_DENIED", "Missing 'case:read' permission")

    # Access is allowed
    return None
    


def reserve_call(state: dict, settings: Settings) -> dict:
    """Admit one model call, or stop with a typed failure.

    Read model_calls and reserved_tokens from state. Missing values mean 0.

    If model_calls is already at settings.max_model_calls, return
    failed("ITERATION_LIMIT", ...). Do not increment the counters.

    If reserved_tokens + settings.reserve_tokens would pass
    settings.total_token_budget, return failed("TOKEN_BUDGET", ...).
    Do not increment the counters.

    Otherwise return a partial update:
    model_calls increased by 1, reserved_tokens increased by
    settings.reserve_tokens, and status "planning".
    """
    # Read values from state, defaulting to 0 if missing
    model_calls = state.get("model_calls", 0)
    reserved_tokens = state.get("reserved_tokens", 0)

    # Check if model_calls exceeds the maximum allowed
    if model_calls >= Settings.max_model_calls:
        failed("ITERATION_LIMIT", f"Maximum model calls ({Settings.max_model_calls}) reached.")

    # Check if reserved_tokens exceeds the token budget
    if reserved_tokens + settings.tokens_reserved_per_call > Settings.token_budget:
        failed("TOKEN_BUDGET", f"Token budget exceeded. Current: {reserved_tokens}, "
                                f"Attempted: {reserved_tokens + Settings.tokens_reserved_per_call}, "
                                f"Limit: {Settings.token_budget}.")

    # Increment counters and return the updated state
    return {
        "model_calls": model_calls + 1,
        "reserved_tokens": reserved_tokens + Settings.tokens_reserved_per_call,
        "status": "planning"
    }
    


def validate_proposal(evidence: dict, proposal: dict):
    """Return None when the proposal may be shown to a manager.

    The model drafts the summary. Your code checks the facts.

    Return failed("EVIDENCE_MISMATCH", ...) unless all of these are true:
    - proposal["action"] is exactly "create_review_task"
    - proposal["case_id"] equals evidence["case_id"]
    - proposal["invoice_id"] equals evidence["invoice_id"]
    - both of those identifiers appear in proposal["evidence_refs"]

    A convincing summary cannot replace a matching invoice id.
    """
    # Check if the action is "create_review_task"
    if proposal.get("action") != "create_review_task":
        failed("EVIDENCE_MISMATCH", "Action must be 'create_review_task'.")
    case_id = evidence.get("case_id")
    invoice_id = evidence.get("invoice_id")
    # Check if case_id matches
    if proposal.get("case_id") != evidence.get("case_id"):
        failed("EVIDENCE_MISMATCH", "Case ID does not match.")

    # Check if invoice_id matches
    if proposal.get("invoice_id") != evidence.get("invoice_id"):
        failed("EVIDENCE_MISMATCH", "Invoice ID does not match.")

    # Check if both identifiers appear in evidence_refs
    evidence_refs = proposal.get("evidence_refs")
    if not (evidence.get("case_id") in evidence_refs and evidence.get("invoice_id") in evidence_refs):
        failed("EVIDENCE_MISMATCH", "Identifiers are missing from evidence_refs.")

    # If all checks pass, return None
    return None
    


def approval_decision(principal, reply: dict, expected_hash: str, now: int, expires_at: int, tenant_id: str) -> dict:
    """Decide what the current person is allowed to do with this exact proposal.

    Check in this order:

    1. reply["approved"] must be a real boolean. The string "yes" is not enough.
       Return {"ok": False, "failure": failed("INVALID_APPROVAL", ...)}.
    2. reply["proposal_hash"] must equal expected_hash.
       Return {"ok": False, "failure": failed("STALE_APPROVAL", ...)}.
    3. principal.permissions must include "task:approve", and
       principal.tenant_id must equal tenant_id.
       Return {"ok": False, "failure": failed("APPROVAL_FORBIDDEN", ...)}.
       The approver comes from the current principal, never from model text.
    4. If now >= expires_at, return
       {"ok": False, "failure": failed("APPROVAL_EXPIRED", ...)}.
    5. If approved is True, return
       {"ok": True, "decision": "approved", "approved_by": principal.subject}.
    6. If approved is False, return {"ok": True, "decision": "rejected"}.
    """
     # 1. Check if reply["approved"] is a real boolean
    if not isinstance(reply.get("approved"), bool):
        return {"ok":False,"failure":failed("INVALID_APPROVAL", "The 'approved' field must be a boolean.")}

    # 2. Check if reply["proposal_hash"] matches expected_hash
    if reply.get("proposal_hash") != expected_hash:
        return {"ok":False,"failure":failed("STALE_APPROVAL", "The proposal hash does not match the expected hash.")}

    # 3. Check if principal has "task:approve" permission and tenant_id matches
    if "task:approve" not in principal.permissions:
        return {"ok":False,"failure":failed("APPROVAL_FORBIDDEN", "The principal does not have 'task:approve' permission.")}
    if principal.tenant_id != tenant_id:
        return {"ok":False,"failure":failed("APPROVAL_FORBIDDEN", "The principal's tenant ID does not match.")}

    # 4. Check if the approval has expired
    if now >= expires_at:
        return {"ok":False,"failure":failed("APPROVAL_EXPIRED", "The approval has expired.")}

    # 5. If approved is True, return approval decision
    if reply["approved"]:
        return {"ok": True, "decision": "approved", "approved_by": principal.subject}

    # 6. If approved is False, return rejection decision
    return {"ok": True, "decision": "rejected"}
    


def action_key(tenant_id: str, request_id: str, proposal_hash: str) -> str:
    """Stable identity for one approved action.

    Return tenant_id, request_id, and proposal_hash joined by colons:
    "acme-in:request-1:<64-character hash>".
    The same proposal must keep the same key after a restart.
    """
     # Concatenate the inputs with colons
    return f"{tenant_id}:{request_id}:{proposal_hash}"
    


class TaskLedger:
    """In-memory stand-in for the external task system."""

    def __init__(self):
        self._rows: dict[str, dict] = {}
        self._task_counter = 0  # Counter to generate unique task IDs
        self._receipts = []  # List to store receipts in insertion order


    def create(self, key: str, payload: dict) -> dict:
        """Create one task, or return the receipt that already exists for key.

        Same key and same payload: return the original receipt. Do not add a row.
        Same key and a different payload: raise ValueError. The message must
        contain "payload".
        New key: store a copy of payload and return
        {"action_key": key, "task_id": "TASK-1"} for the first task,
        "TASK-2" for the second, and so on.
        """
        # Check if the key already exists
        if key in self._rows:
            existing_payload = self._rows[key]["payload"]
            if existing_payload == payload:
                # Return the original receipt if the payload matches
                return self._rows[key]["receipt"]
            else:
                # Raise ValueError if the payload is different
                raise ValueError("payload mismatch for the given key")

        # Create a new task
        self._task_counter += 1
        task_id = f"TASK-{self._task_counter}"
        receipt = {"action_key": key, "task_id": task_id}

        # Store the payload and receipt
        self._rows[key] = {"payload": payload, "receipt": receipt}
        self._receipts.append(receipt)  # Maintain insertion order

        return dict(receipt)
        

    def all(self) -> list[dict]:
        """Return the receipts in insertion order."""
        return [dict(receipt) for receipt in self._receipts]
        
