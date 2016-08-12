#    Copyright 2014 Cisco Systems, Inc.  All rights reserved.
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

from oslo_log import log as logging
import oslo_messaging

from neutron.common import constants
from neutron.common import rpc as n_rpc
from neutron.common import topics
from neutron.common import utils
from neutron import manager

from networking_cisco.plugins.cisco.common import cisco_constants
from networking_cisco.plugins.cisco.extensions import ciscocfgagentscheduler

LOG = logging.getLogger(__name__)

# don't know about these constants, will need to change cisco_constants
# for BGP stuff
# L3AGENT_SCHED = constants.L3_AGENT_SCHEDULER_EXT_ALIAS
CFGAGENT_SCHED = ciscocfgagentscheduler.CFG_AGENT_SCHEDULER_ALIAS
CFG_AGENT_BGP = cisco_constants.CFG_AGENT_BGP
CFG_AGENT_L3_ROUTING = cisco_constants.CFG_AGENT_L3_ROUTING

class BgpSpeakerCfgAgentNotifyAPI(object):
    """API for plugin to notify Cisco cfg agent."""
    # what methods do I write? notifying multiple agents?
    
    def __init__(self, bgp_plugin, topic=CFG_AGENT_L3_ROUTING):
        self._bgp_plugin = bgp_plugin
        target = oslo_messaging.Target(topic=topic, version='1.0')
        self.client = n_rpc.get_client(target)

    def bgp_routes_advertisement(self, context, bgp_speaker_id,
                                routes, host):
        """Tell the  Cisco cfg agent handling a particular host
        
        to begin advertising given routes.
        """
        self._agent_notification(context, 'bgp_routes_advertisement_end',
                {'advertise_routes': {'speaker_id': bgp_speaker_id,
                                    'routes': routes}}, host)


    def bgp_routes_withdrawal(self, context, bgp_speaker_id,
                              routes, host):
        """Tell Cisco cfg agent to configure hosting device to 
         stop advertising the given route.

        Invoked on FIP disassociation, removal of a router port on a
        network, and removal of DVR port-host binding, and subnet delete(?).
        """
        self._agent_notification(context, 'bgp_routes_withdrawal_end',
                {'withdraw_routes': {'speaker_id': bgp_speaker_id,
                                     'routes': routes}}, host)

    def bgp_peer_disassociated(self, context, bgp_speaker_id,
                               bgp_peer_ip, host):
        """Tell Cisco cfg agent about a new BGP Peer association.

        This effectively tells the Cisco cfg agent to stop a peering session.
        """
        self._agent_notification(context, 'bgp_peer_disassociation_end',
                {'bgp_peer': {'speaker_id': bgp_speaker_id,
                              'peer_ip': bgp_peer_ip}}, host)


    def bgp_peer_associated(self, context, bgp_speaker_id,
                            bgp_peer_id, host):
        """Tell Cisco cfg agent about a BGP Peer disassociation.

        This effectively tells the cisco_cfg_agent to open a peering session.
        """
        self._agent_notification(context, 'bgp_peer_association_end',
                {'bgp_peer': {'speaker_id': bgp_speaker_id,
                              'peer_id': bgp_peer_id}}, host)

    def bgp_speaker_created(self, context, bgp_speaker, host):
        """Tell Cisco cfg agent about the creation of a BGP Speaker.

        Because a BGP Speaker can be created with BgpPeer binding in place,
        we need to inform the Cisco cfg agent of a new BGP Speaker in case a
        peering session needs to opened immediately.
        """
        self._agent_notification(context, 'bgp_speaker_create_end', bgp_speaker)

    def bgp_speaker_removed(self, context, bgp_speaker_id, host):
        """Tell Cisco cfg agent about the removal of a BGP Speaker.

        Because a BGP Speaker can be removed with BGP Peer binding in
        place, we need to inform the Cisco cfg agent of the removal of a
        BGP Speaker in case peering sessions need to be stopped.
        """
        self._agent_notification(context, 'bgp_speaker_remove_end',
                {'bgp_speaker': {'id': bgp_speaker_id}}, host)

    # def _notification(self, context, method, speaker):
    #     """Notify all or individual Cisco cfg agents."""
    #     if utils.is_extension_supported(self._l3plugin, L3AGENT_SCHED):
    #         adm_context = (context.is_admin and context or context.elevated())
    #         # This is where hosting device gets scheduled to Cisco cfg agent
    #         # self._l3plugin.schedule_routers(adm_context, routers)
    #         self._agent_notification(
    #             context, method, speaker)
    #     else:
    #         cctxt = self.client.prepare(topics=topics.L3_AGENT, fanout=True)
    #         cctxt.cast(context, method, routers=[r['id'] for r in routers])

    def _agent_notification(self, context, method, speaker):
        admin_context = context.is_admin and context or context.elevated()
        dmplugin = manager.NeutronManager.get_service_plugins().get(
            cisco_constants.DEVICE_MANAGER)
        if (speaker['hosting_device'] is not None and
                utils.is_extension_supported(dmplugin, CFGAGENT_SCHED)):
            agents = dmplugin.get_cfg_agents_for_hosting_devices(
                admin_context, [speaker['hosting_device']['id']],
                admin_state_up=True, schedule=True)
            for agent in agents:
                cctxt = self.client.prepare(server=agent.host)
                cctxt.cast(context, method, bgp_speaker=speaker, host=speaker['hosting_device'])







