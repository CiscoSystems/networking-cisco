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
from neutron.i18n import _LE
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
                # If interface config is present, then use that
                # to perform additional configuration to the interface
                # (used to configure dynamic routing per sub-interface).
                # If it's not present, assume static routing is used,
                # so configure routes for the tenant networks
                if_configs = port['hosting_info'].get('interface_config')
                if if_configs and isinstance(if_configs, list):
                    self._set_subinterface(port, if_configs)
                else:
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

    def _set_subinterface(self, port, if_configs):
        sub_interface = self._get_interface_name_from_hosting_port(port)
        for if_config in if_configs:
            conf_str = (snippets.SET_INTERFACE_CONFIG % (
                           sub_interface, if_config))
            self._edit_running_config(conf_str, 'SET_INTERFACE_CONFIG')

    def _remove_subinterface(self, port, if_configs):
        sub_interface = self._get_interface_name_from_hosting_port(port)
        for if_config in if_configs:
            conf_str = (snippets.REMOVE_INTERFACE_CONFIG % (
                           sub_interface, if_config))
            self._edit_running_config(conf_str, 'REMOVE_INTERFACE_CONFIG')

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
            gateway_ip = self._get_interface_gateway_ip_from_hosting_port(port)
            conf_str = snippets.SET_TENANT_ROUTE_WITH_INTF % (
                vrf_name, subnet, mask, out_itfc, gateway_ip)
            self._edit_running_config(conf_str, 'SET_TENANT_ROUTE_WITH_INTF')

    def _remove_tenant_net_route(self, ri, port):
        cidr = port['subnets'][0]['cidr']
        if cidr:
            vrf_name = self._get_vrf_name(ri)
            out_itfc = self._get_interface_name_from_hosting_port(port)
            ip = netaddr.IPNetwork(cidr)
            subnet, mask = ip.network.format(), ip.netmask.format()
            gateway_ip = self._get_interface_gateway_ip_from_hosting_port(port)
            conf_str = snippets.REMOVE_TENANT_ROUTE_WITH_INTF % (
                vrf_name, subnet, mask, out_itfc, gateway_ip)
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
                cidr = port['hosting_info']['cidr_exposed']
                return cidr.split("/")[0]
            except KeyError as e:
                params = {'key': e}
                raise cfg_exc.DriverExpectedKeyNotSetException(**params)

    def _get_interface_gateway_ip_from_hosting_port(self, port):
        """
        Extract the next hop IP for a subinterface
        e.g. 1.103.2.254
        """
        try:
            ip = port['hosting_info']['gateway_ip']
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
        if_configs = port['hosting_info'].get('interface_config')
        if if_configs and isinstance(if_configs, list):
            self._remove_subinterface(port, if_configs)
        else:
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

    def _add_floating_ip(self, ri, ex_gw_port, floating_ip, fixed_ip):
        vrf_name = self._get_vrf_name(ri)
        self._asr_do_add_floating_ip(ri, floating_ip, fixed_ip,
                                     vrf_name, ex_gw_port)

        # We need to make sure that our external interface has an IP address
        # on the same subnet as the floating IP (needed in order to handle ARPs
        # on the external interface). Search for the matching subnet for this
        # FIP, and use the highest host address as a secondary address on that
        # interface
        subnets = ri.router['gw_port'].get('extra_subnets', [])
        subnet = self._get_matching_subnet(subnets, floating_ip)
        if subnet:
            secondary_ip = netaddr.IPAddress(subnet.value +
                                             (subnet.hostmask.value - 1))
            self._asr_do_add_secondary_ip(secondary_ip,
                                          ex_gw_port, subnet.netmask)

    def _remove_floating_ip(self, ri, ext_gw_port, floating_ip, fixed_ip):
        vrf_name = self._get_vrf_name(ri)
        self._asr_do_remove_floating_ip(ri, floating_ip,
                                        fixed_ip,
                                        vrf_name,
                                        ext_gw_port)
        # A secondary IP address may need to be removed from the external
        # interface. Check the known subnets to see which one contains
        # the floating IP, then search for any other floating IPs on that
        # subnet. If there aren't any, then the secondary IP can safely
        # be removed.
        subnets = ri.router['gw_port'].get('extra_subnets', [])
        subnet = self._get_matching_subnet(subnets, floating_ip)
        if not subnet:
            return
        secondary_ip = netaddr.IPAddress(subnet.value +
                                         (subnet.hostmask.value - 1))
        # We only remove the secondary IP if there aren't any more FIPs
        # for this subnet
        # FIXME(tbachman): should check across all routers
        # FIXME(tbachman): should already have this list (local cache?)
        other_fips = False
        for curr_fip in ri.router.get(constants.FLOATINGIP_KEY, []):
            # skip the FIP we're deleting
            if curr_fip['floating_ip_address'] == floating_ip:
                continue
            fip = netaddr.IPAddress(curr_fip['floating_ip_address'])
            if (fip.value & subnet.netmask.value) == subnet.value:
                other_fips = True
                break
        if other_fips:
            return

        self._asr_do_remove_secondary_ip(secondary_ip,
                                         ext_gw_port, subnet.netmask)

    def _get_matching_subnet(self, subnets, ip):
        target_ip = netaddr.IPAddress(ip)
        for subnet in subnets:
            net = netaddr.IPNetwork(subnet['cidr'])
            if (target_ip.value & net.netmask.value) == net.value:
                return net
        return None

    def _asr_do_add_secondary_ip(self, secondary_ip, port, netmask):
        sub_interface = self._get_interface_name_from_hosting_port(port)
        conf_str = (snippets.ADD_SECONDARY_IP % (
                       sub_interface, secondary_ip, netmask))
        self._edit_running_config(conf_str, 'ADD_SECONDARY_IP')

    def _asr_do_remove_secondary_ip(self, secondary_ip, port, netmask):
        sub_interface = self._get_interface_name_from_hosting_port(port)
        conf_str = (snippets.REMOVE_SECONDARY_IP % (
                       sub_interface, secondary_ip, netmask))
        self._edit_running_config(conf_str, 'REMOVE_SECONDARY_IP')

    def _asr_do_add_floating_ip(self, ri, floating_ip,
                                fixed_ip, vrf, ex_gw_port):
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

    def _asr_do_remove_floating_ip(self, ri, floating_ip,
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

    def _do_set_snat_pool(self, pool_name, pool_start,
                          pool_end, pool_net, is_delete):
        try:
            if is_delete:
                conf_str = asr1k_snippets.DELETE_NAT_POOL % (
                    pool_name, pool_start, pool_end, pool_net)
                # TODO(update so that hosting device name is passed down)
                self._edit_running_config(conf_str, 'DELETE_NAT_POOL')

            else:
                conf_str = asr1k_snippets.CREATE_NAT_POOL % (
                    pool_name, pool_start, pool_end, pool_net)
                # TODO(update so that hosting device name is passed down)
                self._edit_running_config(conf_str, 'CREATE_NAT_POOL')
        except Exception as cse:
            LOG.error(_LE("Temporary disable NAT_POOL exception handling: "
                          "%s"), cse)

    def _set_snat_pools_from_hosting_info(self, ri, gw_port, is_delete):
        # TODO(tbachma ): unique naming for more than one pool
        vrf_name = self._get_vrf_name(ri)
        for subnet in gw_port['hosting_info'].get('snat_subnets', []):
            net = netaddr.IPNetwork(subnet['cidr'])
            pool_name = "%s_nat_pool" % (vrf_name)
            self._do_set_snat_pool(pool_name, subnet['ip'],
                                   subnet['ip'], str(net.netmask), is_delete)
            secondary_ip = netaddr.IPAddress(net.value +
                                             (net.hostmask.value - 1))
            if is_delete:
                self._asr_do_remove_secondary_ip(secondary_ip,
                                                 gw_port, str(net.netmask))
            else:
                self._asr_do_add_secondary_ip(secondary_ip,
                                              gw_port, str(net.netmask))

    def _set_nat_pool(self, ri, gw_port, is_delete):
        if gw_port['hosting_info'].get('snat_subnets'):
            self._set_snat_pools_from_hosting_info(ri, gw_port, is_delete)
