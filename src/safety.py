"""Token-based confirmation system for destructive operations.

MCP tools cannot directly prompt users, so destructive operations use a
two-phase commit pattern:

Phase 1 - Request: The destructive tool generates a UUID token, stores the
    pending action, and returns a warning message + token to the AI client.
Phase 2 - Confirm: The AI client shows the warning to the user. If approved,
    it calls confirm_action(token=...) which executes the stored action.

Tokens expire after 5 minutes.
"""

import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# In-memory store of pending destructive actions
_pending_actions: dict[str, dict[str, Any]] = {}

TOKEN_EXPIRY_SECONDS = 300  # 5 minutes


def _cleanup_expired_tokens() -> None:
    """Remove expired tokens from the pending actions store."""
    now = time.time()
    expired = [
        token
        for token, action in _pending_actions.items()
        if now - action["created_at"] > TOKEN_EXPIRY_SECONDS
    ]
    for token in expired:
        del _pending_actions[token]
        logger.info("Cleaned up expired token: %s", token[:8])


def create_confirmation_token(
    action_name: str,
    description: str,
    callback: Callable[[], Awaitable[str]],
) -> str:
    """Create a confirmation token for a destructive action.

    Args:
        action_name: Name of the destructive tool (e.g., 'delete_file').
        description: Human-readable description of what will happen.
        callback: Async function to execute if confirmed.

    Returns:
        JSON string with status, token, warning, and instructions.
    """
    _cleanup_expired_tokens()

    token = str(uuid.uuid4())
    _pending_actions[token] = {
        "action_name": action_name,
        "description": description,
        "callback": callback,
        "created_at": time.time(),
    }

    result = {
        "status": "confirmation_required",
        "token": token,
        "action": action_name,
        "warning": f"⚠️  DESTRUCTIVE ACTION: {description}",
        "message": (
            f"This action ({action_name}) is destructive and may not be reversible. "
            f"To proceed, call the confirm_action tool with token: {token}"
        ),
        "expires_in_seconds": TOKEN_EXPIRY_SECONDS,
    }

    logger.info(
        "Created confirmation token %s for action: %s", token[:8], action_name
    )
    return json.dumps(result, indent=2)


async def execute_confirmed_action(token: str) -> str:
    """Execute a previously confirmed destructive action.

    Args:
        token: The confirmation token returned by the destructive action request.

    Returns:
        Result of the action execution, or an error message.
    """
    if token not in _pending_actions:
        return json.dumps({
            "status": "error",
            "message": "Invalid or expired confirmation token. Please re-request the action.",
        })

    action = _pending_actions[token]
    elapsed = time.time() - action["created_at"]

    if elapsed > TOKEN_EXPIRY_SECONDS:
        del _pending_actions[token]
        return json.dumps({
            "status": "error",
            "message": (
                f"Confirmation token has expired (was valid for {TOKEN_EXPIRY_SECONDS} seconds). "
                "Please re-request the action."
            ),
        })

    # Execute the action
    action_name = action["action_name"]
    del _pending_actions[token]

    logger.info("Executing confirmed action: %s (token: %s)", action_name, token[:8])

    try:
        result = await action["callback"]()
        return json.dumps({
            "status": "success",
            "action": action_name,
            "result": result,
        })
    except Exception as e:
        logger.error("Error executing action %s: %s", action_name, e)
        return json.dumps({
            "status": "error",
            "action": action_name,
            "message": f"Action failed: {e}",
        })


def register_confirmation_tool(mcp) -> None:
    """Register the confirm_action tool with the MCP server."""

    @mcp.tool()
    async def confirm_action(token: str) -> str:
        """Confirm and execute a previously requested destructive action.

        When a destructive tool (delete, uninstall, kill process, etc.) is called,
        it returns a confirmation token instead of executing immediately. Pass that
        token to this tool to actually execute the action.

        Args:
            token: The confirmation token returned by the destructive action request.
        """
        return await execute_confirmed_action(token)
