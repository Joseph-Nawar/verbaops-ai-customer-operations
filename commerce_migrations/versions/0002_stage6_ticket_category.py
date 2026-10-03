"""Add the Stage 6 support-ticket category contract."""

import sqlalchemy as sa
from alembic import op

revision = "0002_stage6_ticket_category"
down_revision = "0001_create_commerce_schema"
branch_labels = None
depends_on = None

_CATEGORY_VALUES = (
    "order",
    "delivery",
    "returns_refunds",
    "product",
    "warranty",
    "payment",
    "account",
    "other",
)
_CATEGORY_CHECK = "category IN (" + ", ".join(f"'{value}'" for value in _CATEGORY_VALUES) + ")"
_CATEGORY_CONSTRAINT = "ck_support_tickets_support_tickets_category"


def upgrade() -> None:
    """Add a non-null category and backfill existing tickets to other."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("support_tickets")}
    if "category" not in columns:
        op.add_column(
            "support_tickets",
            sa.Column(
                "category",
                sa.String(length=15),
                nullable=False,
                server_default=sa.text("'other'"),
            ),
        )

    checks = {check["name"] for check in inspector.get_check_constraints("support_tickets")}
    if _CATEGORY_CONSTRAINT not in checks:
        op.create_check_constraint(
            "support_tickets_category",
            "support_tickets",
            _CATEGORY_CHECK,
        )


def downgrade() -> None:
    """Remove the Stage 6 ticket category constraint and column."""

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    checks = {check["name"] for check in inspector.get_check_constraints("support_tickets")}
    if _CATEGORY_CONSTRAINT in checks:
        op.drop_constraint("support_tickets_category", "support_tickets", type_="check")

    columns = {column["name"] for column in inspector.get_columns("support_tickets")}
    if "category" in columns:
        op.drop_column("support_tickets", "category")
