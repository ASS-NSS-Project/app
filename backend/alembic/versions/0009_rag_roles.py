"""Rename UserRole enum values to rag_* prefix

Revision ID: 0009
Revises: 0008
Create Date: 2025-04-26

Replaces admin/curator/analyst/user with rag_admin/rag_curator/rag_analyst/rag_user.
PostgreSQL does not support renaming enum labels directly — the migration creates a
new type, migrates the column with an inline CASE, drops the old type, and renames.

Each step is guarded so the migration is idempotent: safe to re-run after a partial
failure (e.g. pod crash between steps).
"""

from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$ BEGIN
            -- Step 1: create new type if it doesn't exist yet
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'userrole_new') THEN
                CREATE TYPE userrole_new AS ENUM (
                    'rag_admin', 'rag_curator', 'rag_analyst', 'rag_user'
                );
            END IF;

            -- Step 2: migrate column only if it still holds legacy values
            IF EXISTS (
                SELECT 1
                FROM   pg_attribute a
                JOIN   pg_class     c ON a.attrelid = c.oid
                JOIN   pg_type      t ON a.atttypid  = t.oid
                WHERE  c.relname = 'users'
                  AND  a.attname = 'role'
                  AND  t.typname = 'userrole'
                  AND  EXISTS (
                      SELECT 1 FROM pg_enum e
                      WHERE e.enumtypid = t.oid AND e.enumlabel = 'admin'
                  )
            ) THEN
                ALTER TABLE users
                    ALTER COLUMN role TYPE userrole_new
                    USING (CASE role::text
                        WHEN 'admin'   THEN 'rag_admin'
                        WHEN 'curator' THEN 'rag_curator'
                        WHEN 'analyst' THEN 'rag_analyst'
                        WHEN 'user'    THEN 'rag_user'
                        ELSE 'rag_user'
                    END)::userrole_new;
                ALTER TABLE users
                    ALTER COLUMN role SET DEFAULT 'rag_user'::userrole_new;
            END IF;

            -- Step 3: drop old type only if it still carries legacy labels
            IF EXISTS (
                SELECT 1 FROM pg_type t
                WHERE  t.typname = 'userrole'
                  AND  EXISTS (
                      SELECT 1 FROM pg_enum e
                      WHERE e.enumtypid = t.oid AND e.enumlabel = 'admin'
                  )
            ) THEN
                DROP TYPE userrole;
            END IF;

            -- Step 4: rename userrole_new → userrole if rename hasn't happened yet
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'userrole_new') THEN
                ALTER TYPE userrole_new RENAME TO userrole;
            END IF;
        END $$
    """)


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'userrole_old') THEN
                CREATE TYPE userrole_old AS ENUM (
                    'admin', 'curator', 'analyst', 'user'
                );
            END IF;

            IF EXISTS (
                SELECT 1
                FROM   pg_attribute a
                JOIN   pg_class     c ON a.attrelid = c.oid
                JOIN   pg_type      t ON a.atttypid  = t.oid
                WHERE  c.relname = 'users'
                  AND  a.attname = 'role'
                  AND  t.typname = 'userrole'
                  AND  EXISTS (
                      SELECT 1 FROM pg_enum e
                      WHERE e.enumtypid = t.oid AND e.enumlabel = 'rag_admin'
                  )
            ) THEN
                ALTER TABLE users
                    ALTER COLUMN role TYPE userrole_old
                    USING (CASE role::text
                        WHEN 'rag_admin'   THEN 'admin'
                        WHEN 'rag_curator' THEN 'curator'
                        WHEN 'rag_analyst' THEN 'analyst'
                        WHEN 'rag_user'    THEN 'user'
                        ELSE 'user'
                    END)::userrole_old;
                ALTER TABLE users
                    ALTER COLUMN role SET DEFAULT 'user'::userrole_old;
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_type t
                WHERE  t.typname = 'userrole'
                  AND  EXISTS (
                      SELECT 1 FROM pg_enum e
                      WHERE e.enumtypid = t.oid AND e.enumlabel = 'rag_admin'
                  )
            ) THEN
                DROP TYPE userrole;
            END IF;

            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'userrole_old') THEN
                ALTER TYPE userrole_old RENAME TO userrole;
            END IF;
        END $$
    """)
