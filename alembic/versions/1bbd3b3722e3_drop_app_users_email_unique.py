"""drop app_users email unique constraint

Identity for ``app_users`` is ``external_id``, the exe.dev proxy's stable
handle; email is descriptive data the proxy reports alongside it and does not
itself guarantee unique. The ``UNIQUE`` on ``email`` asserted a rule the
upstream identity provider never made, and any collision (proxy re-issuing an
id for the same person, two identities sharing a mailbox, two operators
swapping addresses) raised ``IntegrityError`` inside ``get_dashboard_user`` —
locking that operator out of every dashboard page with a 500 (#177).

Nothing reads or joins on email: ``api_keys`` FKs on ``app_users.id`` and the
dashboard only displays it. Dropping the constraint removes both failure paths.

Revision ID: 1bbd3b3722e3
Revises: b7e41d902cca
Create Date: 2026-08-20 20:50:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1bbd3b3722e3"
down_revision: str | Sequence[str] | None = "b7e41d902cca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("app_users_email_key", "app_users", schema="information", type_="unique")


def downgrade() -> None:
    """Downgrade schema.

    Fails if rows sharing an email exist by then — deliberate: collapsing
    distinct proxy identities to restore a constraint would be data loss.
    """
    op.create_unique_constraint("app_users_email_key", "app_users", ["email"], schema="information")
