# Copyright 2014 OpenStack Foundation
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#

"""Cisco device management

Revision ID: 2921fe565328
Revises: 28c0ffb8ebbd
Create Date: 2014-12-18 13:00:02.923237

"""

# revision identifiers, used by Alembic.
revision = '2921fe565328'
down_revision = 'kilo'

from alembic import op
import sqlalchemy as sa

from neutron.db import migration


def upgrade():
    op.create_table('cisco_hosting_device_templates',
        sa.Column('tenant_id', sa.String(length=255), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False,
                  server_default=sa.sql.false()),
        sa.Column('host_category', sa.String(length=255), nullable=False),
        sa.Column('service_types', sa.String(length=255), nullable=True),
        sa.Column('image', sa.String(length=255), nullable=True),
        sa.Column('flavor', sa.String(length=255), nullable=True),
        sa.Column('default_credentials_id', sa.String(length=36),
                  nullable=True),
        sa.Column('configuration_mechanism', sa.String(length=255),
                  nullable=True),
        sa.Column('protocol_port', sa.Integer(), nullable=True),
        sa.Column('booting_time', sa.Integer(), nullable=True,
                  server_default='0'),
        sa.Column('slot_capacity', sa.Integer(), autoincrement=False,
                  nullable=False),
        sa.Column('desired_slots_free', sa.Integer(), autoincrement=False,
                  nullable=False, server_default='0'),
        sa.Column('tenant_bound', sa.String(length=512), nullable=True),
        sa.Column('device_driver', sa.String(length=255), nullable=False),
        sa.Column('plugging_driver', sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table('cisco_slot_allocations',
        sa.Column('template_id', sa.String(length=36), nullable=False),
        sa.Column('hosting_device_id', sa.String(length=36), nullable=False),
        sa.Column('logical_resource_type', sa.String(155), nullable=False),
        sa.Column('logical_resource_service', sa.String(155), nullable=False),
        sa.Column('logical_resource_id', sa.String(length=36), nullable=False),
        sa.Column('logical_resource_owner', sa.String(length=36),
                  nullable=False),
        sa.Column('num_allocated', sa.Integer(), autoincrement=False,
                  nullable=False),
        sa.Column('tenant_bound', sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(['template_id'],
                                ['cisco_hosting_device_templates.id']),
        sa.ForeignKeyConstraint(['hosting_device_id'],
                                ['cisco_hosting_devices.id']),
        sa.PrimaryKeyConstraint('logical_resource_id')
    )
    if migration.schema_has_table('cisco_hosting_devices'):
        op.add_column('cisco_hosting_devices',
                      sa.Column('template_id', sa.String(length=36),
                                nullable=False))
        op.create_foreign_key('cisco_hosting_devices_ibfk_3',
                              source='cisco_hosting_devices',
                              referent='cisco_hosting_device_templates',
                              local_cols=['template_id'], remote_cols=['id'])
        op.create_index('template_id', 'cisco_hosting_devices',
                        ['template_id'])
        op.add_column('cisco_hosting_devices',
                      sa.Column('credentials_id', sa.String(length=36),
                                nullable=True))
        op.add_column('cisco_hosting_devices',
                      sa.Column('name', sa.String(255), nullable=True))
        op.add_column('cisco_hosting_devices',
                      sa.Column('description', sa.String(255), nullable=True))
        op.add_column('cisco_hosting_devices',
                      sa.Column('management_ip_address', sa.String(255),
                                nullable=True))
        op.add_column('cisco_hosting_devices',
                      sa.Column('tenant_bound', sa.String(length=36),
                                nullable=True))
        op.add_column('cisco_hosting_devices',
                      sa.Column('auto_delete', sa.Boolean(), nullable=False,
                                server_default=sa.sql.false()))
    op.create_index(op.f('ix_cisco_hosting_device_templates_tenant_id'),
                    'cisco_hosting_device_templates', ['tenant_id'],
                    unique=False)


def downgrade():
    op.drop_index(op.f('ix_cisco_hosting_device_templates_tenant_id'),
                  table_name='cisco_hosting_device_templates')
    op.drop_column('cisco_hosting_devices', 'auto_delete')
    op.drop_column('cisco_hosting_devices', 'tenant_bound')
    op.drop_column('cisco_hosting_devices', 'management_ip_address')
    op.drop_column('cisco_hosting_devices', 'description')
    op.drop_column('cisco_hosting_devices', 'name')
    op.drop_column('cisco_hosting_devices', 'credentials_id')
    op.drop_constraint('cisco_hosting_devices_ibfk_3',
                       'cisco_hosting_devices', type_='foreignkey')
    op.drop_column('cisco_hosting_devices', 'template_id')
    op.drop_table('cisco_slot_allocations')
    op.drop_table('cisco_hosting_device_templates')
