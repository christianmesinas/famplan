"""Add FamilyInvite model for invitation tokens

Revision ID: 91197a1620bb
Revises: a8427e80e9bc
Create Date: 2025-06-13 20:45:56.267428

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '91197a1620bb'
down_revision = 'a8427e80e9bc'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('family_invite',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('family_id', sa.Integer(), nullable=False),
    sa.Column('token', sa.String(length=32), nullable=False),
    sa.Column('invited_email', sa.String(length=120), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('accepted', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['family_id'], ['family.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token')
    )
    with op.batch_alter_table('family_invite', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_family_invite_family_id'), ['family_id'], unique=False)

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('family_invite', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_family_invite_family_id'))

    op.drop_table('family_invite')
    # ### end Alembic commands ###
