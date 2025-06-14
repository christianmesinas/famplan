"""Add unique constraint to Membership(user_id, family_id)

Revision ID: 1f90bb246085
Revises: 91197a1620bb
Create Date: 2025-06-13 22:13:36.125568

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1f90bb246085'
down_revision = '91197a1620bb'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('membership', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_membership_user_family', ['user_id', 'family_id'])

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('membership', schema=None) as batch_op:
        batch_op.drop_constraint('uq_membership_user_family', type_='unique')

    # ### end Alembic commands ###
