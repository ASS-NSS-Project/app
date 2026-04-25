"""
services/keycloak_service.py - Keycloak Admin REST API

Syncs role changes made in the WebRAG UI back to Keycloak so they persist
across SSO logins (which would otherwise re-apply the Keycloak group role).

Requires service account rag-rbac-sa with realm-management / manage-users.
No-op when KEYCLOAK_ADMIN_CLIENT_ID is not set (local dev without Keycloak).
"""

import logging

import httpx

from config import get_settings
from models import UserRole

logger = logging.getLogger(__name__)

# App role → Keycloak group name (inverse of _GROUP_TO_ROLE in auth_keycloak.py)
_ROLE_TO_GROUP: dict[UserRole, str] = {
    UserRole.admin:   "admin",
    UserRole.curator: "curator",
    UserRole.analyst: "analytic",  # Keycloak group is "analytic", app role is "analyst"
    UserRole.user:    "user",
}

_MANAGED_GROUPS = set(_ROLE_TO_GROUP.values())


class KeycloakSyncError(Exception):
    pass


async def _admin_token() -> str:
    s = get_settings()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{s.keycloak_url}/realms/{s.keycloak_realm}/protocol/openid-connect/token",
            data={
                "grant_type":    "client_credentials",
                "client_id":     s.keycloak_admin_client_id,
                "client_secret": s.keycloak_admin_client_secret,
            },
        )
    if resp.status_code != 200:
        raise KeycloakSyncError(f"Could not obtain admin token: {resp.text}")
    return resp.json()["access_token"]


async def _list_groups(token: str) -> dict[str, str]:
    """Returns {group_name: group_id} for all top-level realm groups."""
    s = get_settings()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{s.keycloak_url}/admin/realms/{s.keycloak_realm}/groups",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        raise KeycloakSyncError(f"Could not list groups: {resp.text}")
    return {g["name"]: g["id"] for g in resp.json()}


async def assign_role(keycloak_sub: str, new_role: UserRole) -> None:
    """
    Update a Keycloak user's group membership to match new_role.
    Always a no-op (logs warning) when Keycloak is not configured or unreachable —
    the caller's local DB change should never be rolled back due to a Keycloak failure.
    """
    s = get_settings()
    if not s.keycloak_admin_client_id or not s.keycloak_admin_client_secret:
        logger.debug("Keycloak admin client not configured — skipping role sync")
        return

    try:
        token = await _admin_token()
        groups = await _list_groups(token)

        target_group = _ROLE_TO_GROUP[new_role]
        if target_group not in groups:
            raise KeycloakSyncError(
                f"Group '{target_group}' not found in Keycloak realm '{s.keycloak_realm}'"
            )

        base = f"{s.keycloak_url}/admin/realms/{s.keycloak_realm}/users/{keycloak_sub}/groups"

        async with httpx.AsyncClient(timeout=10) as client:
            for name in _MANAGED_GROUPS:
                gid = groups.get(name)
                if gid:
                    await client.delete(
                        f"{base}/{gid}",
                        headers={"Authorization": f"Bearer {token}"},
                    )

            resp = await client.put(
                f"{base}/{groups[target_group]}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code not in (200, 204):
                raise KeycloakSyncError(
                    f"Failed to add user to group '{target_group}': {resp.text}"
                )

        logger.info(
            "Synced Keycloak role for sub=%s → %s (group: %s)",
            keycloak_sub, new_role.value, target_group,
            extra={"event": "keycloak_role_synced", "sub": keycloak_sub, "role": new_role.value},
        )

    except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError) as exc:
        logger.warning(
            "Keycloak unreachable — role synced locally only (sub=%s): %s",
            keycloak_sub, exc,
            extra={"event": "keycloak_sync_skipped", "sub": keycloak_sub, "reason": str(exc)},
        )
    except Exception as exc:
        logger.warning(
            "Keycloak role sync failed — local change preserved (sub=%s): %s",
            keycloak_sub, exc,
            extra={"event": "keycloak_sync_failed", "sub": keycloak_sub, "reason": str(exc)},
        )
