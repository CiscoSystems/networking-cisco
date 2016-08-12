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

import collections
import eventlet
import netaddr
import pprint as pp

# from ncclient.transport import errors as ncc_errors
from oslo_config import cfg
from oslo_log import log as logging
import oslo_messaging
from oslo_utils import excutils
from oslo_utils import importutils
import six

from neutron.services.bgp import bgp_plugin
# from neutron.extensions import bgp as bgp_ext
from neutron.services.bgp.common import constants as bgp_consts
from neutron.callbacks import registry
from neutron.callbacks import resources
from neutron.common import constants as n_const
from neutron.common import rpc as n_rpc
from neutron.common import topics

from networking_cisco.plugins.cisco.db.bgp import bgp_speaker_appliance_db
from networking_cisco.plugins.cisco.db.bgp import speakertype_db
from networking_cisco.plugins.cisco.db.scheduler import bgp_speakertype_aware_schedulers_db
from networking_cisco.plugins.cisco.db.bgp import bgp_models
from networking_cisco.plugins.cisco.bgp.rpc import bgp_speaker_rpc_cfg_agent_api

from networking_cisco.plugins.cisco.l3.rpc import l3_router_rpc_cfg_agent_api
from networking_cisco.plugins.cisco.l3.rpc import l3_router_cfg_agent_rpc_cb
from networking_cisco.plugins.cisco.service_plugins import cisco_router_plugin
class CiscoBgpPlugin(
    bgp_speaker_appliance_db.BgpApplianceDBMixin, 
    # speakertype_db.SpeakertypeDbMixin, 
    bgp_speakertype_aware_schedulers_db.BgpSpeakerTypeAwareSchedulerDbMixin, 
    bgp_plugin.BgpPlugin,
    cisco_router_plugin.CiscoRouterPlugin):
    
    def __init__(self):
        super(CiscoBgpPlugin, self).__init__()
        # self._bgp_rpc = bgp_speaker_rpc_cfg_agent_api.BgpSpeakerCfgAgentNotifyAPI(self)
        self._bgp_rpc = l3_router_rpc_cfg_agent_api.L3RouterCfgAgentNotifyAPI(self)
        # self._bs_rpc = l3_router_cfg_agent_rpc_cb.L3RouterCfgRpcCallback(self)
        # self.endpoints.append(self._bs_rpc)
        # self.topic = topics.L3PLUGIN
        # self.conn.create_consumer(self.topic, self.endpoints, fanout=False)
        # self.conn.consume_in_threads()



    def create_bgp_speaker(self, context, bgp_speaker):
        # add rpc call to tell the svc agent
        return super(CiscoBgpPlugin, self).create_bgp_speaker(context, bgp_speaker)

    def delete_bgp_speaker(self, context, bgp_speaker_id):
        hosting_devices = self.list_hosting_devices_hosting_speaker(
                                                                context,
                                                        bgp_speaker_id)
        super(CiscoBgpPlugin, self).delete_bgp_speaker(context, bgp_speaker_id)

    def add_bgp_peer(self, context, bgp_speaker_id, bgp_peer_info):
        ret_value = super(CiscoBgpPlugin, self).add_bgp_peer(context, bgp_speaker_id,
                                                                bgp_peer_info)
        # hosting_devices = self.list_hosting_devices_hosting_speaker(
                                                    # context, bgp_speaker_id)
        # for host in hosting_devices['hosting_devices']:
        #     self._bgp_rpc.bgp_peer_associated(context, bgp_speaker_id,
        #                                     ret_value['bgp_peer_id'],
        #                                     host)
        return ret_value

    def remove_bgp_peer(self, context, bgp_speaker_id, bgp_peer_info):
        # hosting_devices = self.list_hosting_devices_hosting_speaker(
        #         context, bgp_speaker_id)

        ret_value = super(CiscoBgpPlugin, self).remove_bgp_peer(context,
                                                            bgp_speaker_id,
                                                            bgp_peer_info)

        # for host in hosting_devices['hosting_devices']:
        #     self._bgp_rpc.bgp_peer_disassociated(context, bgp_speaker_id,
        #                                         ret_value['bgp_peer_id'], 
        #                                         host)

    def start_route_advertisements(self, ctx, bgp_rpc, bgp_speaker_id,
                                    routes):
        hosting_devices = self.list_hosting_devices_hosting_speaker(
                context, bgp_speaker_id)
        for host in hosting_devices['hosting_devices']:
            self._bgp_rpc.bgp_routes_advertisement(ctx, bgp_speaker_id,
                                                routes, 
                                                ret_value['bgp_peer_id'], 
                                                host)    

    def stop_route_advertisements(self, ctx, bgp_rpc, bgp_speaker_id,
                                    routes):
        hosting_devices = self.list_hosting_devices_hosting_speaker(
                context, bgp_speaker_id)
        for host in hosting_devices['hosting_devices']:
            self._bgp_rpc.bgp_routes_withdrawal(ctx, bgp_speaker_id,
                                                routes, 
                                                ret_value['bgp_peer_id'], 
                                                host)    





