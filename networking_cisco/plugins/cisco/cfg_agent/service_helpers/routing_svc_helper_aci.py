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

from oslo_log import log as logging

from neutron.common import constants as l3_constants

from networking_cisco.plugins.cisco.cfg_agent.service_helpers import (
    routing_svc_helper as helper)
from networking_cisco.plugins.cisco.extensions import routerrole

ROUTER_ROLE_ATTR = routerrole.ROUTER_ROLE_ATTR
LOG = logging.getLogger(__name__)


class RoutingServiceHelperAci(helper.RoutingServiceHelper):

    def __init__(self, host, conf, cfg_agent):
        super(RoutingServiceHelperAci, self).__init__(
            host, conf, cfg_agent)
        self._router_ids_by_vrf = {}

    def _process_new_ports(self, ri, new_ports, ex_gw_port, list_port_ids_up):
        # Only add internal networks if we have an
        # eternal gateway -- otherwise we have no parameters
        # to use to configure the interface (e.g. VRF, IP, etc.)
        if ex_gw_port:
            super(RoutingServiceHelperAci,
                  self)._process_new_ports(
                      ri, new_ports, ex_gw_port, list_port_ids_up)

    def _process_old_ports(self, ri, old_ports, ex_gw_port):
        gw_port = ri.router.get('gw_port') or ri.ex_gw_port
        for p in old_ports:
            LOG.debug("++ removing port id = %s (gw = %s)" %
                      (p['id'], gw_port))
            # We can only clear the port if we stil have all
            # the relevant information (VRF and external network
            # parameters), which come from the GW port. Go ahead
            # and remove the interface from our internal state
            if gw_port:
                self._internal_network_removed(ri, p, gw_port)
            ri.internal_ports.remove(p)

    def _process_gateway_set(self, ri, ex_gw_port, list_port_ids_up):
        super(RoutingServiceHelperAci,
              self)._process_gateway_set(ri, ex_gw_port, list_port_ids_up)
        # transiiioned -- go enable any interfaces
        interfaces = ri.router.get(l3_constants.INTERFACE_KEY, [])
        new_ports = [p for p in interfaces
                     if (p['admin_state_up'] and
                         p not in ri.internal_ports)]
        super(RoutingServiceHelperAci,
              self)._process_new_ports(
                  ri, new_ports, ex_gw_port, list_port_ids_up)

    def _process_gateway_cleared(self, ri, ex_gw_port):
        super(RoutingServiceHelperAci,
              self)._process_gateway_cleared(ri, ex_gw_port)
        # remove the internal networks at this time,
        # while the gateway information is still available
        # (has VRF network parameters)
        old_ports = [p for p in ri.internal_ports
                     if p['admin_state_up']]
        super(RoutingServiceHelperAci,
              self)._process_old_ports(ri, old_ports, ex_gw_port)

    def _add_rid_to_vrf_list(self, ri):
        """Add router ID to a VRF list.

        In order to properly manage VRFs in the ASR, their
        usage has to be tracked. VRFs are provided with neutron
        router objects in their hosting_info fields of the gateway ports.
        This means that the VRF is only available when the gateway port
        of the router is set. VRFs can span routers, and even OpenStack
        tenants, so lists of routers that belong to the same VRF are
        kept in a dictionary, with the VRF name as the key.
        """
        if ri.ex_gw_port or ri.router.get('gw_port'):
            driver = self.driver_manager.get_driver(ri.id)
            vrf_name = driver._get_vrf_name(ri)
            if not vrf_name:
                return
            if not self._router_ids_by_vrf.get(vrf_name):
                LOG.debug("++ CREATING VRF %s" % vrf_name)
                driver._do_create_vrf(vrf_name)
            self._router_ids_by_vrf.setdefault(vrf_name, set()).add(
                ri.router['id'])

    def _remove_rid_from_vrf_list(self, ri):
        """Remove router ID from a VRF list.

        In order to properly manage VRFs in the ASR, their
        usage has to be tracked. VRFs are provided with neutron
        router objects in their hosting_info fields of the gateway ports.
        This means that the VRF is only available when the gateway port
        of the router is set. VRFs can span routers, and even OpenStack
        tenants, so lists of routers that belong to the same VRF are
        kept in a dictionary, with the VRF name as the key.
        """
        if ri.ex_gw_port or ri.router.get('gw_port'):
            driver = self.driver_manager.get_driver(ri.id)
            vrf_name = driver._get_vrf_name(ri)
            if self._router_ids_by_vrf.get(vrf_name) and (
                    ri.router['id'] in self._router_ids_by_vrf[vrf_name]):
                self._router_ids_by_vrf[vrf_name].remove(ri.router['id'])
                # If this is the last router in a VRF, then we can safely
                # delete the VRF from the router config (handled by the driver)
                if not self._router_ids_by_vrf.get(vrf_name):
                    LOG.debug("++ REMOVING VRF %s" % vrf_name)
                    driver._remove_vrf(ri)
                    del self._router_ids_by_vrf[vrf_name]
