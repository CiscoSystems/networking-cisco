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

import copy
import os
import subprocess

from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import importutils
import six
from sqlalchemy.orm import exc
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import expression as expr
from sqlalchemy.sql import false as sql_false

from networking_cisco._i18n import _, _LE, _LI, _LW

from neutron.api.v2 import attributes
from neutron.callbacks import events
from neutron.callbacks import registry
from neutron.callbacks import resources
from neutron.common import constants as bgp_constants
from neutron.common import exceptions as n_exc
from neutron.common import rpc as n_rpc
from neutron.common import utils
from neutron import context as n_context
from neutron.db import db_base_plugin_v2
from neutron.db import extraroute_db
from neutron.db import bgp_db
from neutron.extensions import bgp
from neutron.extensions import providernet as pr_net
from neutron import manager
from neutron.plugins.common import constants as svc_constants
# not sure about this
from neutron.services.bgp.common import constants as bgp_consts

from networking_cisco.plugins.cisco.common import cisco_constants
from networking_cisco.plugins.cisco.db.device_manager import hd_models
from networking_cisco.plugins.cisco.db.bgp import bgp_models
from networking_cisco.plugins.cisco.device_manager import config
from networking_cisco.plugins.cisco.extensions import ciscohostingdevicemanager
from networking_cisco.plugins.cisco.extensions import routerhostingdevice
# from networking_cisco.plugins.cisco.extensions import routerrole
from networking_cisco.plugins.cisco.extensions import speakertype
from networking_cisco.plugins.cisco.extensions import speakertypeawarescheduler
#from networking_cisco.plugins.cisco.bgp.drivers import driver_context

LOG = logging.getLogger(__name__)

SPEAKER_APPLIANCE_OPTS = [
    cfg.StrOpt('default_speaker_type',
                default=cisco_constants.ASR1K_SPEAKER_TYPE,
                help=_("Default type of bgp speaker to create")),
    cfg.StrOpt('namespace_speaker_type_name',
                default=cisco_constants.NAMESPACE_SPEAKER_TYPE,
                help=_("Name of bgp speaker type used for Linux "
                        "network namespace speakers")),
]

cfg.CONF.register_opts(SPEAKER_APPLIANCE_OPTS, 'bgp')

class BgpApplianceDBMixin(bgp_db.BgpDbMixin):
    """Mixin class implementing Neutron's BGP service using appliances"""

    # Dictionary with loaded scheduler modules for different speaker types
    _speaker_schedulers = {}

    # Dictionary with loaded driver modules for different speaker types
    _speaker_drivers = {}

    # Id of speaker type used to represent Neutron's "legacy" Linux network
    # namespace speakers
    _namespace_speaker_type_id = None

    # Set of ids of speakers for which new scheduling attempts should
    # be made and the refresh setting and heartbeat for that.
    _backlogged_speakers = set()
    _refresh_speaker_backlog = True
    _heartbeat = None

    def create_bgp_speaker(self, context, bgp_speaker):
        speaker_created, s_hd_db = self.do_create_bgp_speaker(
            context, bgp_speaker, None, True, True)
        return speaker_created
    
    def do_create_bgp_speaker(self, context, speaker, speaker_type_id, 
                    auto_schedule, share_host):
        with context.session.begin(subtransactions=True):
            speaker_created = super(BgpApplianceDBMixin, self).\
                                    create_bgp_speaker(context, speaker)
            query = context.session.query(hd_models.HostingDevice)
            hosts = query.all()
            host = hosts[0]
            if speaker_created['name'].startswith('p'):
                host = hosts[1]
            s_hd_b_db = bgp_models.SpeakerHostingDeviceBinding(
                speaker_id=speaker_created['id'],
                speaker_type_id=host['id'],
                auto_schedule=auto_schedule,
                share_hosting_device=share_host,
                hosting_device_id=host['id'])
            context.session.add(s_hd_b_db)
        return speaker_created, s_hd_b_db

    def delete_bgp_speaker(self, context, bgp_speaker_id, unschedule=True):
        with context.session.begin(subtransactions=True):
            bgp_hd_db = self._get_speaker_binding_info(context, bgp_speaker_id)
            self._bgp_rpc.bgp_speaker_deleted(context, bgp_hd_db)
            context.session.delete(bgp_hd_db)
            super(BgpApplianceDBMixin, self).delete_bgp_speaker(context, bgp_speaker_id)


    def _get_speaker_binding_info(self, context, id, load_hd_info=True):
        query = context.session.query(bgp_models.SpeakerHostingDeviceBinding)
        # if load_hd_info:
        #     query = query.options(joinedload('hosting_device'))
        query = query.filter(bgp_models.SpeakerHostingDeviceBinding.speaker_id ==
                             id)
        try:
            return query.one()
        except exc.NoResultFound:
            # This should not happen other than transiently because the
            # requested data is not committed to the DB yet
            LOG.debug('Transient DB inconsistency: No type and hosting info '
                      'currently associated with speaker %s', id)
            raise speakertype.SpeakerBindingInfoError(speaker_id=id)
        except exc.MultipleResultsFound:
            # This should not happen either
            LOG.error(_LE('DB inconsistency: Multiple type and hosting info '
                          'associated with speaker %s'), id)
            raise speakertype.SpeakerBindingInfoError(speaker_id=id)    

    def add_bgp_peer(self, context, bgp_speaker_id, bgp_peer_info):
        ret_value = super(BgpApplianceDBMixin, self).add_bgp_peer(context,
                                                        bgp_speaker_id,
                                                        bgp_peer_info)
        bgp_peer = self.get_bgp_peer(context, ret_value['bgp_peer_id'])
        bgp_hd_db = self._get_speaker_binding_info(context, bgp_speaker_id)
        if bgp_hd_db['speaker']['name'].startswith('p'):
            self._bgp_rpc.bgp_speaker_peer_added(context, bgp_hd_db, bgp_peer, True)
        else:
            self._bgp_rpc.bgp_speaker_peer_added(context, bgp_hd_db, bgp_peer)

    def remove_bgp_peer(self, context, bgp_speaker_id, bgp_peer_info):
        bgp_peer_id = self._get_id_for(bgp_peer_info, 'bgp_peer_id')
        bgp_peer = self.get_bgp_peer(context, bgp_peer_id)
        bgp_hd_db = self._get_speaker_binding_info(context, bgp_speaker_id)
        self._bgp_rpc.bgp_speaker_peer_removed(context, bgp_hd_db, bgp_peer)
        return super(BgpApplianceDBMixin, self).remove_bgp_peer(context,
                                                        bgp_speaker_id,
                                                        bgp_peer_info)

    def _is_master_process(self):
        ppid = os.getppid()
        parent_name = subprocess.check_output(
            ["ps", "-p", str(ppid), "-o", "comm="])
        is_master = parent_name != "python"
        LOG.debug('Executable for parent process(%d) is %s so this is %s '
                  'process (%d)' % (ppid, parent_name,
                                    'the MASTER' if is_master else 'a WORKER',
                                    os.getpid()))
        return is_master

    # def _create_speaker_types_from_config(self):
    #     """To be called late during plugin initialization so that any speaker
    #     type defined in the config file is properly inserted in the DB.
    #         """
    #     self._dev_mgr._setup_device_manager()
    #     st_dict = config.get_specific_config('cisco_speaker_type')
    #     attr_info = speakertype.RESOURCE_ATTRIBUTE_MAP[speakertype.SPEAKER_TYPES]
    #     adm_context = n_context.get_admin_context()

    #     for st_uuid, kv_dict in st_dict.items():
    #         try:
    #             # ensure hd_uuid is properly formatted
    #             st_uuid = config.uuidify(st_uuid)
    #             self.get_speakertype(adm_context, st_uuid)
    #             is_create = False
    #         except speakertype.SpeakerTypeNotFound:
    #             is_create = True
    #         kv_dict['id'] = st_uuid
    #         # need bgp_tenant_id() in _dev_mgr
    #         kv_dict['tenant_id'] = self._dev_mgr.bgp_tenant_id()
    #         config.verify_resource_dict(kv_dict, True, attr_info)
    #         hd = {'speakertype': kv_dict}
    #         try:
    #             if is_create:
    #                 self.create_speakertype(adm_context, hd)
    #             #else:
    #             #    self.update_speakertype(adm_context, kv_dict['id'], hd)
    #         except n_exc.NeutronException:
    #             with excutils.save_and_reraise_exception():
    #                 LOG.error(_LE('Invalid speaker type definition in '
    #                               'configuration file for device = %s'),
    #                             st_uuid)
    
    @property
    def _dev_mgr(self):
        return manager.NeutronManager.get_service_plugins().get(
                cisco_constants.DEVICE_MANAGER)


    # def backlog_speaker(self, context, binding_info_db):
    #     LOG.debug('Trying to backlog speaker %s' % binding_info_db.speaker_id)
    #     context.session.expire(binding_info_db)
    #     self._backlog_speaker(context, binding_info_db)

    # def _backlog_speaker(self, context, binding_info_db):
    #     # if (binding_info_db.speaker_type_id ==
    #     #         self.get_namespace_speaker_type_id(context) or
    #     #     binding_info_db.hosting_device_id is not None or
    #     #         binding_info_db.speaker_id in self._backlogged_speakers):
    #     #     LOG.debug('Aborting backlogging of speaker %s' %
    #     #               binding_info_db.speaker_id)
    #     #     return
    #     LOG.info(_LI('Backlogging speaker %s for renewed scheduling attempt '
    #                  'later'), binding_info_db.speaker_id)
    #     self._backlogged_speakers.add(binding_info_db.speaker_id)


    # def schedule_speaker_on_hosting_device(self, context, binding_info_db,
    #                             hosting_device_id=None, slot_need=None,
    #                             synchronized=True):
    #     if hosting_device_id is None:
    #         scheduler = 










    
