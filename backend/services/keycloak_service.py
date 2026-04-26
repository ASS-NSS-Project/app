"""
services/keycloak_service.py - Keycloak Admin REST API

Two responsibilities:
  1. assign_role() — pushes role changes made in the app UI back to Keycloak
     so they survive the next SSO login (which would otherwise re-apply the
     Keycloak group role).
  2. sync_users_from_keycloak() — pulls all realm users into the local DB at
     startup and on a 10-minute schedule, so the app's user list mirrors
     Keycloak before anyone logs in for the first time.

Requires service account rag-rbac-sa with realm-management / manage-users.
No-op when KEYCLOAK_ADMIN_CLIENT_ID is not set (local dev without Keycloak).
"""

import logging

import httpx
from sqlalchemy.orm import Session

from config import get_settings
from models import User, UserRole

logger = logging.getLogger(__name__)

# Keycloak group name → app UserRole
_GROUP_TO_ROLE: dict[str, UserRole] = {
    "admin":    UserRole.admin,
    "curator":  UserRole.curator,
    "analytic": UserRole.analyst,  # Keycloak group is "analytic", app role is "analyst"
    "user":     UserRole.user,
}

# App role → Keycloak group name (inverse)
_ROLE_TO_GROUP: dict[UserRole, str] = {
    UserRole.admin:   "admin",
    UserRole.curator: "curator",
    UserRole.analyst: "analytic",
    UserRole.user:    "user",
}

_MANAGED_GROUPS = set(_ROLE_TO_GROUP.values())


def _map_role(groups: list[str]) -> UserRole:
    """Highest-privilege matching group wins. Defaults to 'user'."""
    for group in ("admin", "curator", "analytic", "user"):
        if group in groups:
            return _GROUP_TO_ROLE[group]
    return UserRole.user


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


async def sync_users_from_keycloak(db: Session) -> dict:
    """
    Pull all realm users from Keycloak and upsert them into the local DB.

    For each Keycloak user:
      - If a local user with matching oauth_id exists: update email, name, and role.
      - Else if a local user with matching email exists: link to Keycloak and update role.
      - Else: create a new local user (is_active=True).

    Returns {"created": int, "updated": int, "skipped": int}.
    Always a no-op when KEYCLOAK_ADMIN_CLIENT_ID is not configured.
    """
    s = get_settings()
    if not s.keycloak_admin_client_id or not s.keycloak_admin_client_secret:
        logger.debug("Keycloak admin client not configured — skipping user sync")
        return {"created": 0, "updated": 0, "skipped": 0}

    try:
        token = await _admin_token()

        created = updated = skipped = 0

        async with httpx.AsyncClient(timeout=30) as client:
            headers = {"Authorization": f"Bearer {token}"}
            base = f"{s.keycloak_url}/admin/realms/{s.keycloak_realm}"

            # Paginate through all realm users in batches of 500
            all_users: list[dict] = []
            first = 0
            batch_size = 500
            while True:
                resp = await client.get(
                    f"{base}/users",
                    headers=headers,
                    params={"first": first, "max": batch_size},
                )
                if resp.status_code != 200:
                    raise KeycloakSyncError(f"Could not list users: {resp.text}")
                batch = resp.json()
                all_users.extend(batch)
                if len(batch) < batch_size:
                    break
                first += batch_size

            for kc_user in all_users:
                sub: str | None = kc_user.get("id")
                email: str | None = kc_user.get("email")
                if not sub or not email:
                    skipped += 1
                    continue

                first_name = kc_user.get("firstName") or ""
                last_name = kc_user.get("lastName") or ""
                full_name = f"{first_name} {last_name}".strip() or None

                # Fetch this user's group memberships to determine role
                grp_resp = await client.get(
                    f"{base}/users/{sub}/groups",
                    headers=headers,
                )
                if grp_resp.status_code != 200:
                    skipped += 1
                    continue
                user_groups = [g["name"] for g in grp_resp.json()]
                role = _map_role(user_groups)

                # Upsert: match by Keycloak sub first, then by email
                user = db.query(User).filter(
                    User.oauth_provider == "keycloak",
                    User.oauth_id == sub,
                ).first()

                if user:
                    user.role = role
                    user.email = email
                    if full_name:
                        user.full_name = full_name
                    updated += 1
                else:
                    user = db.query(User).filter(User.email == email).first()
                    if user:
                        user.oauth_provider = "keycloak"
                        user.oauth_id = sub
                        user.role = role
                        if full_name and not user.full_name:
                            user.full_name = full_name
                        updated += 1
                    else:
                        db.add(User(
                            email=email,
                            full_name=full_name,
                            hashed_password=None,
                            oauth_provider="keycloak",
                            oauth_id=sub,
                            role=role,
                            is_active=True,
                        ))
                        created += 1

        db.commit()
        logger.info(
            "Keycloak user sync complete: created=%d updated=%d skipped=%d",
            created, updated, skipped,
            extra={
                "event": "keycloak_user_sync",
                "created": created,
                "updated": updated,
                "skipped": skipped,
            },
        )
        return {"created": created, "updated": updated, "skipped": skipped}

    except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError) as exc:
        logger.warning(
            "Keycloak unreachable during user sync: %s", exc,
            extra={"event": "keycloak_sync_skipped", "reason": str(exc)},
        )
        return {"created": 0, "updated": 0, "skipped": -1}
    except Exception as exc:
        logger.warning(
            "Keycloak user sync failed: %s", exc,
            extra={"event": "keycloak_sync_failed", "reason": str(exc)},
        )
        return {"created": 0, "updated": 0, "skipped": -1}
