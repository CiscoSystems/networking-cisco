# Copyright 2015 Cisco Systems, Inc.  All rights reserved.
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

import logging
import netaddr

from oslo_config import cfg

from networking_cisco.plugins.cisco.cfg_agent import cfg_exceptions as cfg_exc
from networking_cisco.plugins.cisco.cfg_agent.device_drivers.asr1k import (
    aci_asr1k_snippets as snippets)
from networking_cisco.plugins.cisco.cfg_agent.device_drivers.asr1k import (
    asr1k_routing_driver as asr1k)
from networking_cisco.plugins.cisco.cfg_agent.device_drivers.asr1k import (
    asr1k_snippets)
from networking_cisco.plugins.cisco.common import cisco_constants
from networking_cisco.plugins.cisco.extensions import ha
from networking_cisco.plugins.cisco.extensions import routerrole
from neutron.common import constants
from neutron.i18n import _LI


LOG = logging.getLogger(__name__)


DEVICE_OWNER_ROUTER_GW = constants.DEVICE_OWNER_ROUTER_GW
HA_INFO = 'ha_info'
ROUTER_ROLE_ATTR = routerrole.ROUTER_ROLE_ATTR
ROUTER_ROLE_HA_REDUNDANCY = cisco_constants.ROUTER_ROLE_HA_REDUNDANCY
ROUTER_ROLE_GLOBAL = cisco_constants.ROUTER_ROLE_GLOBAL


class AciASR1kRoutingDriver(asr1k.ASR1kRoutingDriver):

    def __init__(self, **device_params):
        super(AciASR1kRoutingDriver, self).__init__(**device_params)
        self._fullsync = False
        self._deployment_id = "zxy"
        self.hosting_device = {'id': device_params.get('id'),
                               'device_id': device_params.get('device_id')}

    # ============== Public functions ==============

    def internal_network_added(self, ri, port):
        if not self._is_port_v6(port):
            if self._is_global_router(ri):
                # The global router is modeled as the default vrf
                # in the ASR.  When an external gateway is configured,
                # a normal "internal" interface is created in the default
                # vrf that is in the same subnet as the ext-net.
                LOG.debug("global router handling")
                self.external_gateway_added(ri, port)
            else:
                LOG.debug("Adding IPv4 internal network port: %(port)s "
                          "for router %(r_id)s", {'port': port, 'r_id': ri.id})
                self._create_sub_interface(
                    ri, port, is_external=False)
                self._add_tenant_net_route(ri, port)

    def _create_sub_interface(self, ri, port, is_external=False, gw_ip=""):
        vlan = self._get_interface_vlan_from_hosting_port(port)
        if (self._fullsync and
                int(vlan) in self._existing_cfg_dict['interfaces']):
            LOG.info(_LI("Sub-interface already exists, skipping"))
            return
        vrf_name = self._get_vrf_name(ri)
        hsrp_ip = self._get_interface_ip_from_hosting_port(port,
            is_external=is_external)
        net_mask = self._get_interface_subnet_from_hosting_port(port,
            is_external=is_external)
        sub_interface = self._get_interface_name_from_hosting_port(port)
        self._do_create_sub_interface(sub_interface, vlan, vrf_name, hsrp_ip,
                                      net_mask, is_external)
        # Always do HSRP
        if ri.router.get(ha.ENABLED, False):
            if port.get(ha.HA_INFO) is not None:
                self._add_ha_hsrp(ri, port, is_external=is_external)
            else:
                # We are missing HA data, candidate for retrying
                params = {'r_id': ri.router_id, 'p_id': port['id'],
                          'port': port}
                raise cfg_exc.HAParamsMissingException(**params)

    def _add_ha_hsrp(self, ri, port, is_external=False):
        priority = None
        if ri.router.get(ROUTER_ROLE_ATTR) in (ROUTER_ROLE_HA_REDUNDANCY,
                                               ROUTER_ROLE_GLOBAL):
            for router in ri.router[ha.DETAILS][ha.REDUNDANCY_ROUTERS]:
                if ri.router['id'] == router['id']:
                    priority = router[ha.PRIORITY]
        else:
            priority = ri.router[ha.DETAILS][ha.PRIORITY]
        port_ha_info = port[ha.HA_INFO]
        group = port_ha_info['group']
        ip = self._get_interface_ip_from_hosting_port(port,
            is_external=is_external)
        if is_external:
            ha_ip = port_ha_info['ha_port']['fixed_ips'][0]['ip_address']
        else:
            # TODO(tbachman): needs fixing
            ha_ip = netaddr.IPAddress(netaddr.IPAddress(ip).value + 1).format()
        vlan = self._get_interface_vlan_from_hosting_port(port)
        if ip and group and priority:
            vrf_name = self._get_vrf_name(ri)
            sub_interface = self._get_interface_name_from_hosting_port(port)
            self._do_set_ha_hsrp(sub_interface, vrf_name,
                                 priority, group, ha_ip, vlan)

    def _add_tenant_net_route(self, ri, port):
        if self._fullsync and (ri.router_id in
                               self._existing_cfg_dict['routes']):
            LOG.debug("Tenant network route already exists, skipping")
            return
        cidr = port['subnets'][0]['cidr']
        if cidr:
            vrf_name = self._get_vrf_name(ri)
            out_itfc = self._get_interface_name_from_hosting_port(port)
            ip = netaddr.IPNetwork(cidr)
            subnet, mask = ip.network.format(), ip.netmask.format()
            next_hop = self._get_interface_next_hop_from_hosting_port(port)
            conf_str = snippets.SET_TENANT_ROUTE_WITH_INTF % (
                vrf_name, subnet, mask, out_itfc, next_hop)
            self._edit_running_config(conf_str, 'SET_TENANT_ROUTE_WITH_INTF')

    def _remove_tenant_net_route(self, ri, port):
        cidr = port['subnets'][0]['cidr']
        if cidr:
            vrf_name = self._get_vrf_name(ri)
            out_itfc = self._get_interface_name_from_hosting_port(port)
            ip = netaddr.IPNetwork(cidr)
            subnet, mask = ip.network.format(), ip.netmask.format()
            next_hop = self._get_interface_next_hop_from_hosting_port(port)
            conf_str = snippets.REMOVE_TENANT_ROUTE_WITH_INTF % (
                vrf_name, subnet, mask, out_itfc, next_hop)
            self._edit_running_config(conf_str,
                                      'REMOVE_TENANT_ROUTE_WITH_INTF')

    def _get_interface_ip_from_hosting_port(self, port, is_external=False):
        """
        Extract the underlying subinterface IP for a port
        e.g. 1.103.2.1
        """
        if is_external:
            return port['fixed_ips'][0]['ip_address']
        else:
            try:
                ip = port['hosting_info']['gateway_ip']
                return ip
            except KeyError as e:
                params = {'key': e}
                raise cfg_exc.DriverExpectedKeyNotSetException(**params)

    def _get_interface_next_hop_from_hosting_port(self, port):
        """
        Extract the next hop IP for a subinterface
        e.g. 1.103.2.254
        """
        try:
            ip = port['hosting_info']['next_hop']
            return ip
        except KeyError as e:
            params = {'key': e}
            raise cfg_exc.DriverExpectedKeyNotSetException(**params)

    def _get_interface_subnet_from_hosting_port(self, port, is_external=False):
        """
        Extract the CIDR information for the interposing subnet
        e.g. 1.103.2.0/24
        """
        if is_external:
            return netaddr.IPNetwork(port['ip_cidr']).netmask.format()
        else:
            try:
                cidr_exposed = port['hosting_info']['cidr_exposed']
                return netaddr.IPNetwork(cidr_exposed).netmask.format()
            except KeyError as e:
                params = {'key': e}
                raise cfg_exc.DriverExpectedKeyNotSetException(**params)

    def internal_network_removed(self, ri, port):
        self._remove_tenant_net_route(ri, port)

    # ============== Internal "preparation" functions  ==============

    def _get_vrf_name(self, ri):
        """
        For ACI, a tenant is mapped to a VRF.
        """
        tenant_id = ri.router['tenant_id']
        is_multi_region_enabled = cfg.CONF.multi_region.enable_multi_region

        if is_multi_region_enabled:
            region_id = cfg.CONF.multi_region.region_id
            vrf_name = "%s-%s" % (tenant_id, region_id)
        else:
            vrf_name = tenant_id
        return vrf_name

    def _asr_do_add_floating_ip(self, floating_ip, fixed_ip, vrf, ex_gw_port):
        """
        To implement a floating ip, an ip static nat is configured in the
        underlying router ex_gw_port contains data to derive the vlan
        associated with related subnet for the fixed ip.  The vlan in turn
        is applied to the redundancy parameter for setting the IP NAT.
        """
        LOG.debug("add floating_ip: %(fip)s, fixed_ip: %(fixed_ip)s, "
                  "vrf: %(vrf)s, ex_gw_port: %(port)s",
                  {'fip': floating_ip, 'fixed_ip': fixed_ip, 'vrf': vrf,
                   'port': ex_gw_port})

        if ex_gw_port.get(ha.HA_INFO):
            hsrp_grp = ex_gw_port[ha.HA_INFO]['group']
            vlan = ex_gw_port['hosting_info']['segmentation_id']

            confstr = (asr1k_snippets.SET_STATIC_SRC_TRL_NO_VRF_MATCH %
                (fixed_ip, floating_ip, vrf, hsrp_grp, vlan))
        else:
            confstr = (snippets.SET_STATIC_SRC_TRL_NO_VRF_MATCH %
                (fixed_ip, floating_ip, vrf))
        self._edit_running_config(confstr, 'SET_STATIC_SRC_TRL_NO_VRF_MATCH')

    def _asr_do_remove_floating_ip(self, floating_ip,
                                   fixed_ip, vrf, ex_gw_port):
        if ex_gw_port.get(ha.HA_INFO):
            hsrp_grp = ex_gw_port[ha.HA_INFO]['group']
            vlan = ex_gw_port['hosting_info']['segmentation_id']

            confstr = (asr1k_snippets.REMOVE_STATIC_SRC_TRL_NO_VRF_MATCH %
                (fixed_ip, floating_ip, vrf, hsrp_grp, vlan))
        else:
            confstr = (snippets.REMOVE_STATIC_SRC_TRL_NO_VRF_MATCH %
                (fixed_ip, floating_ip, vrf))
        self._edit_running_config(confstr,
                                  'REMOVE_STATIC_SRC_TRL_NO_VRF_MATCH')
