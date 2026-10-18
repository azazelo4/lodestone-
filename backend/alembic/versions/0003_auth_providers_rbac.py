"""sign-in providers in the DB, setup state, RBAC roles and group bindings

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18 12:30:00
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

# frozen copy of the builtin project roles at this revision (app/rbac.py may change later)
_ALL = ['project.read', 'project.manage', 'members.manage', 'issues.create', 'issues.edit', 'issues.delete',
        'comments.create', 'comments.moderate', 'labels.manage', 'sprints.manage']
PROJECT_ROLES = [
    ('admin', 'Project admin', _ALL),
    ('member', 'Member', ['project.read', 'issues.create', 'issues.edit', 'comments.create', 'labels.manage',
                          'sprints.manage']),
    ('viewer', 'Viewer', ['project.read']),
]


def upgrade() -> None:
    op.create_table('auth_providers',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('slug', sa.String(length=40), nullable=False),
    sa.Column('type', sa.String(length=10), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('secrets', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug'),
    sa.CheckConstraint("type IN ('local', 'ldap', 'oidc')", name='ck_auth_providers_type'),
    )
    op.create_index('uq_auth_providers_one_local', 'auth_providers', ['type'], unique=True,
                    postgresql_where=sa.text("type = 'local'"))
    op.create_table('app_settings',
    sa.Column('key', sa.String(length=60), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('roles',
    sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
    sa.Column('key', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('description', sa.Text(), nullable=False, server_default=''),
    sa.Column('scope', sa.String(length=10), nullable=False),
    sa.Column('permissions', postgresql.ARRAY(sa.String(length=40)), nullable=False),
    sa.Column('builtin', sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key'),
    sa.CheckConstraint("scope IN ('global', 'project')", name='ck_roles_scope'),
    )
    roles = sa.table('roles', sa.column('key', sa.String), sa.column('name', sa.String),
                     sa.column('scope', sa.String), sa.column('permissions', postgresql.ARRAY(sa.String)),
                     sa.column('builtin', sa.Boolean))
    op.bulk_insert(roles, [{'key': k, 'name': n, 'scope': 'project', 'permissions': p, 'builtin': True}
                           for k, n, p in PROJECT_ROLES])

    op.create_table('user_roles',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('role_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'role_id')
    )
    op.create_table('user_groups',
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('provider_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=500), nullable=False),
    sa.ForeignKeyConstraint(['provider_id'], ['auth_providers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'provider_id', 'name')
    )
    op.create_index('ix_user_groups_name', 'user_groups', ['name'])
    op.create_table('group_bindings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('provider_id', sa.UUID(), nullable=True),
    sa.Column('group', sa.String(length=500), nullable=False),
    sa.Column('role_id', sa.UUID(), nullable=False),
    sa.Column('project_id', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['provider_id'], ['auth_providers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_group_bindings_project_id'), 'group_bindings', ['project_id'], unique=False)

    op.add_column('users', sa.Column('provider_id', sa.UUID(), nullable=True))
    op.add_column('users', sa.Column('external_id', sa.String(length=255), nullable=True))
    op.create_foreign_key('fk_users_provider_id', 'users', 'auth_providers', ['provider_id'], ['id'],
                          ondelete='SET NULL')
    op.create_index('uq_users_provider_external', 'users', ['provider_id', 'external_id'], unique=True,
                    postgresql_where=sa.text('external_id IS NOT NULL'))

    # project_members.role (enum) -> role_id (builtin roles with the same keys)
    op.add_column('project_members', sa.Column('role_id', sa.UUID(), nullable=True))
    op.execute("UPDATE project_members m SET role_id = r.id FROM roles r WHERE r.key = m.role::text")
    op.alter_column('project_members', 'role_id', nullable=False)
    op.create_foreign_key('fk_project_members_role_id', 'project_members', 'roles', ['role_id'], ['id'],
                          ondelete='RESTRICT')
    op.drop_column('project_members', 'role')
    op.execute('DROP TYPE member_role')


def downgrade() -> None:
    op.execute("CREATE TYPE member_role AS ENUM ('admin', 'member', 'viewer')")
    op.add_column('project_members', sa.Column('role', postgresql.ENUM(name='member_role', create_type=False),
                                               nullable=True))
    # custom roles fold into the closest builtin by their permissions
    op.execute("""
        UPDATE project_members m SET role = (CASE
            WHEN r.key IN ('admin', 'member', 'viewer') THEN r.key
            WHEN 'members.manage' = ANY(r.permissions) THEN 'admin'
            WHEN 'issues.edit' = ANY(r.permissions) THEN 'member'
            ELSE 'viewer' END)::member_role
        FROM roles r WHERE r.id = m.role_id""")
    op.alter_column('project_members', 'role', nullable=False)
    op.drop_constraint('fk_project_members_role_id', 'project_members', type_='foreignkey')
    op.drop_column('project_members', 'role_id')
    op.drop_index('uq_users_provider_external', table_name='users')
    op.drop_constraint('fk_users_provider_id', 'users', type_='foreignkey')
    op.drop_column('users', 'external_id')
    op.drop_column('users', 'provider_id')
    op.drop_index(op.f('ix_group_bindings_project_id'), table_name='group_bindings')
    op.drop_table('group_bindings')
    op.drop_index('ix_user_groups_name', table_name='user_groups')
    op.drop_table('user_groups')
    op.drop_table('user_roles')
    op.drop_table('roles')
    op.drop_table('app_settings')
    op.drop_index('uq_auth_providers_one_local', table_name='auth_providers')
    op.drop_table('auth_providers')
