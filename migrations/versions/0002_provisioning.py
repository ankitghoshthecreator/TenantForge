"""
Alembic migration 0002: add grace_period_days to tenants.

grace_period_days controls how long after soft-delete the tenant's data
is retained before the archival worker hard-deletes it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_provisioning"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "grace_period_days",
            sa.Integer,
            nullable=False,
            server_default="30",
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "grace_period_days")
