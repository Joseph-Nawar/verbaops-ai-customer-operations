"""Create the NovaCommerce M2A schema."""

from alembic import op

from novacommerce.db import Base
from novacommerce.db import models as _models  # noqa: F401  # register model metadata

revision = "0001_create_commerce_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all and only the NovaCommerce application tables."""

    bind = op.get_bind()
    for table in Base.metadata.sorted_tables:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    """Remove the NovaCommerce application tables in dependency order."""

    bind = op.get_bind()
    for table in reversed(Base.metadata.sorted_tables):
        table.drop(bind=bind, checkfirst=True)
