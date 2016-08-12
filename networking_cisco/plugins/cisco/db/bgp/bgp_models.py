# Copyright 2014 Cisco Systems, Inc.  All rights reserved.
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

import sqlalchemy as sa
from sqlalchemy import orm

from neutron.db import model_base
from neutron.db import models_v2
from neutron.db import bgp_db

from networking_cisco.plugins.cisco.db.device_manager import hd_models

class SpeakerType(model_base.BASEV2, models_v2.HasId, models_v2.HasTenant):
    """Represents Neutron BGP speaker types.
    
    A speaker type is associated with a with hosting device template.
    The template is used when hosting device for the speaker type is created.
    """
    __tablename__ = 'cisco_speaker_types'

    # name of speaker type, should preferably be unique
    name = sa.Column(sa.String(255), nullable=False)
    # description of this router type
    description = sa.Column(sa.String(255))
    # template to use to create hosting devices for this router type
    template_id = sa.Column(sa.String(36),
                            sa.ForeignKey('cisco_hosting_device_templates.id',
                                          ondelete='CASCADE'))
    template = orm.relationship(hd_models.HostingDeviceTemplate)
    # The number of slots this router type consume in hosting device
    slot_need = sa.Column(sa.Integer, autoincrement=False)
    # module to be used as scheduler for router of this type
    scheduler = sa.Column(sa.String(255), nullable=False)
    # module to be used by router plugin as router type driver
    driver = sa.Column(sa.String(255), nullable=False)
    # module to be used by configuration agent as service helper driver
    cfg_agent_service_helper = sa.Column(sa.String(255), nullable=False)
    # module to be used by configuration agent for in-device configurations
    cfg_agent_driver = sa.Column(sa.String(255), nullable=False)

class SpeakerHostingDeviceBinding(model_base.BASEV2):
    """Represents binding between BGP speakers and their hosting devices."""
    __tablename__ = 'cisco_speaker_hd_mappings'
    # what is the foregin key?
    speaker_id = sa.Column(sa.String(36),
                            sa.ForeignKey('bgp_speakers.id', ondelete='CASCADE'),
                            primary_key=True)
    speaker = orm.relationship(bgp_db.BgpSpeaker, 
        backref=orm.backref('hosting_info', cascade='all', uselist=False))
    speaker_type_id = sa.Column(
        sa.String(36),
        sa.ForeignKey('cisco_speaker_types.id'),
        primary_key=True,
        nullable=False)
    speaker_type = orm.relationship(SpeakerType)

    auto_schedule = sa.Column(sa.Boolean, default=True, nullable=False)
    share_hosting_device = sa.Column(sa.Boolean, nullable=False,
                                server_default=sa.sql.true())
    hosting_device_id = sa.Column(sa.String(36),
                                  sa.ForeignKey('cisco_hosting_devices.id',
                                                ondelete='SET NULL'))
    hosting_device = orm.relationship(hd_models.HostingDevice)







