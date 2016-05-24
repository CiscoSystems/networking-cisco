# Copyright 2016 Cisco Systems, Inc.  All rights reserved.
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

import re

from oslo_config import cfg
from oslo_log import log as logging

from neutron.common import constants as l3_constants
from neutron.common import exceptions as n_exc
from neutron import manager
from neutron.plugins.common import constants as svc_constants

from networking_cisco.plugins.cisco.device_manager.plugging_drivers import (
    hw_vlan_trunking_driver as hw_vlan)

LOG = logging.getLogger(__name__)

APIC_OWNED = 'apic_owned_'
APIC_SNAT = 'host-snat-pool-for-internal-use'
UUID_REGEX = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
DEVICE_OWNER_ROUTER_GW = l3_constants.DEVICE_OWNER_ROUTER_GW
DEVICE_OWNER_ROUTER_INTF = l3_constants.DEVICE_OWNER_ROUTER_INTF

ACI_ASR1K_DRIVER_OPTS = [
    cfg.StrOpt('aci_transit_nets_config_file', default=None,
               help=_("ACI with ASR transit network configuration file.")),
]

cfg.CONF.register_opts(ACI_ASR1K_DRIVER_OPTS, "general")

DEFAULT_EXT_DICT = {'gateway_ip': '1.103.2.254',
                    'cidr_exposed': '1.103.2.1/24'}


class AciDriverConfigMissingGatewayIp(n_exc.BadRequest):
    message = _("The ACI Driver config is missing a gateway_ip "
                "parameter for %(ext_net)s.")


class AciDriverConfigMissingCidrExposed(n_exc.BadRequest):
    message = _("The ACI Driver config is missing a cidr_exposed "
                "parameter for %(ext_net)s.")


class AciVLANTrunkingPlugDriver(hw_vlan.HwVLANTrunkingPlugDriver):
    """Driver class for Cisco ACI-based devices.

    The driver works with VLAN segmented Neutron networks. It
    determines which workflow is active (GBP or Neutron), and
    uses that implementation to get the information needed for
    the networks between the hosting device and the ACI fabric.
    """
    # once initialized _device_network_interface_map is dictionary
    _device_network_interface_map = None
    _apic_driver = None
    _l3_plugin = None

    def __init__(self):
        super(AciVLANTrunkingPlugDriver, self).__init__()
        self._cfg_file = cfg.CONF.general.aci_transit_nets_config_file
        self._get_ext_net_name = None
        self._default_ext_dict = DEFAULT_EXT_DICT
        self._transit_nets_cfg = {}
        self._get_vrf_context = None
        self._get_vrf_details = None

    def _sanity_check_config(self, config):
        for network in config.keys():
            if config.get(network).get('gateway_ip') is None:
                raise AciDriverConfigMissingGatewayIp(ext_net=network)
            if config.get(network).get('cidr_exposed') is None:
                raise AciDriverConfigMissingCidrExposed(ext_net=network)

    @property
    def transit_nets_cfg(self):
        if self._cfg_file:
            networks_dict = open(self._cfg_file, 'r').read()
            self._transit_nets_cfg = eval(networks_dict)
        else:
            self._transit_nets_cfg = {}
        return self._transit_nets_cfg

    @property
    def get_ext_net_name(self):
        # FIXME(tbachman): sadly, only exists to enable UT
        if self.apic_driver:
            return self._get_ext_net_name
        else:
            return None

    @property
    def get_vrf_context(self):
        if self.apic_driver:
            return self._get_vrf_context
        else:
            return None

    @property
    def get_vrf_details(self):
        if self.apic_driver:
            return self._get_vrf_details
        else:
            return None

    def _get_vrf_context_gbp(self, context, router_id, port_db):
        l2p = self.apic_driver._network_id_to_l2p(
            context, port_db['network_id'])
        l3p = self.apic_driver.gbp_plugin.get_l3_policy(
            context, l2p['l3_policy_id'])
        return {'vrf_id': l3p['id']}

    def _get_vrf_context_neutron(self, context, router_id, port_db):
        router = self.l3_plugin.get_router(context, router_id)
        return {'vrf_id': router['tenant_id']}

    def _get_vrf_details_gbp(self, context, **kwargs):
        details = self.apic_driver.get_vrf_details(context, **kwargs)
        # The L3 out VLAN allocation uses UUIDs instead of names
        details['vrf_name'] = details['l3_policy_id']
        # get rid of VRF tenant -- not needed  for GBP
        if details.get('vrf_tenant'):
            details['vrf_tenant'] = None
        return details

    def _get_vrf_details_neutron(self, context, **kwargs):
        return self.apic_driver.get_vrf_details(context, **kwargs)

    def _get_external_network_dict(self, context, port_db):
        """Get external network information

        Get the information about the external network,
        so that it can be used to create the hidden port,
        subnet, and network.
        """
        if port_db.device_owner == DEVICE_OWNER_ROUTER_GW:
            network = self._core_plugin.get_network(context,
                port_db.network_id)
        else:
            router = self.l3_plugin.get_router(context,
                port_db.device_id)
            network_id = router['external_gateway_info']['network_id']
            network = self._core_plugin.get_network(context, network_id)

        # network names in GBP workflow need to be reduced, since
        # the network may contain UUIDs
        external_network = self.get_ext_net_name(network['name'])
        transit_net = self.transit_nets_cfg.get(
            external_network) or self._default_ext_dict
        return transit_net, network

    @property
    def l3_plugin(self):
        if not self._l3_plugin:
            self._l3_plugin = manager.NeutronManager.get_service_plugins().get(
                svc_constants.L3_ROUTER_NAT)
        return self._l3_plugin

    @property
    def apic_driver(self):
        """Get APIC driver

        There are different drivers for the GBP workflow
        and Neutron workflow for APIC. First see if the GBP
        workflow is active, and if so get the APIC driver for it.
        If the GBP service isn't installed, try to get the driver
        from the Neutron (APIC ML2) workflow.
        """
        if not self._apic_driver:
            try:
                self._apic_driver = (
                    manager.NeutronManager.get_service_plugins()[
                        'GROUP_POLICY'].policy_driver_manager.policy_drivers[
                            'apic'].obj)
                self._get_ext_net_name = self._get_ext_net_name_gbp
                self._get_vrf_context = self._get_vrf_context_gbp
                self._get_vrf_details = self._get_vrf_details_gbp
            except KeyError:
                    LOG.info(_("GBP service plugin not present -- will "
                               "try APIC ML2 plugin."))
            if not self._apic_driver:
                try:
                    self._apic_driver = (
                        self._core_plugin.mechanism_manager.mech_drivers[
                            'cisco_apic_ml2'].obj)
                    self._get_ext_net_name = self._get_ext_net_name_neutron
                    self._get_vrf_context = self._get_vrf_context_neutron
                    self._get_vrf_details = self._get_vrf_details_neutron
                except KeyError:
                    LOG.error(_("APIC ML2 plugin not present: "
                                "no APIC ML2 driver could be found."))
        return self._apic_driver

    def extend_hosting_port_info(self, context, port_db, hosting_device,
                                 hosting_info):
        """Get the segmenetation ID and interface

        This extends the hosting info attribute with the segmentation ID
        and physical interface used on the external router to connect to
        the ACI fabric. The segmentation ID should have been set already
        by the call to allocate_hosting_port, but if it's not present, use
        the value from the port resource.
        """
        if hosting_info.get('segmentation_id') is None:
            LOG.debug('No segmentation ID in hosting_info -- assigning')
            hosting_info['segmentation_id'] = (
                port_db.hosting_info.segmentation_id)
        is_external = (port_db.device_owner == DEVICE_OWNER_ROUTER_GW)
        hosting_info['physical_interface'] = self._get_interface_info(
            hosting_device['id'], port_db.network_id, is_external)
        ext_dict, net = self._get_external_network_dict(context, port_db)
        if not is_external:
            hosting_info['cidr_exposed'] = ext_dict['cidr_exposed']
            hosting_info['gateway_ip'] = ext_dict['gateway_ip']
        else:
            # If an OpFlex network is used on the external network,
            # the actual segment ID comes from the confgi file
            if net.get('provider:network_type') == 'opflex':
                if ext_dict.get('segmentation_id'):
                    hosting_info['segmentation_id'] = (
                        ext_dict['segmentation_id'])
            snat_subnets = self._core_plugin.get_subnets(
                context.elevated(), {'name': [APIC_SNAT]})
            if snat_subnets:
                hosting_info['snat_subnets'] = []
                for subnet in snat_subnets:
                    snat_subnet = {'id': subnet['id'], 'cidr': subnet['cidr']}
                    hosting_info['snat_subnets'].append(snat_subnet)

    def allocate_hosting_port(self, context, router_id, port_db, network_type,
                              hosting_device_id):
        """Get the VLAN and port for this hosting device

        The VLAN used between the APIC and the external router is stored
        by the APIC driver.  This calls into the APIC driver to first get
        the ACI VRF information associated with this port, then uses that
        to look up the VLAN to use for this port to the external router
        (kept as part of the L3 Out policy in ACI).
        """
        if self.apic_driver is None:
            return None

        # If this is a router interface, the VLAN comes from APIC.
        # If it's the gateway, the VLAN comes from the segment ID
        if port_db.get('device_owner') == DEVICE_OWNER_ROUTER_GW:
            return super(AciVLANTrunkingPlugDriver,
                         self).allocate_hosting_port(
                             context, router_id,
                             port_db, network_type, hosting_device_id
                         )

        # shouldn't happen, but just in case
        if port_db.get('device_owner') != DEVICE_OWNER_ROUTER_INTF:
            return None

        # get the external network that this port connects to.
        # if there isn't an external gateway yet on the router,
        # then don't allocate a port

        router = self.l3_plugin.get_router(context, router_id)
        network_id = router.get('external_gateway_info', {}).get('network_id')
        if network_id is None:
            return None

        networks = self._core_plugin.get_networks(
            context.elevated(), {'id': [network_id]})
        l3out_network = networks[0]
        l3out_name = self.get_ext_net_name(l3out_network['name'])
        # For VLAN apic driver provides VLAN tag
        kwargs = self.get_vrf_context(context, router_id, port_db)
        details = self.get_vrf_details(context, **kwargs)
        if details is None:
            LOG.debug('aci_vlan_trunking_driver: No vrf_details')
            return
        vrf_name = details.get('vrf_name')
        vrf_tenant = details.get('vrf_tenant')
        allocated_vlan = self.apic_driver.l3out_vlan_alloc.get_vlan_allocated(
            l3out_name, vrf_name, vrf_tenant=vrf_tenant)
        if allocated_vlan is None:
            if vrf_tenant is None or vrf_tenant == '':
                # TODO(tbachman): I can't remember why this is here
                return super(AciVLANTrunkingPlugDriver,
                             self).allocate_hosting_port(
                                 context, router_id,
                                 port_db, network_type, hosting_device_id
                             )
            # Database must have been messed up if this happens ...
            return
        return {'allocated_port_id': port_db.id,
                'allocated_vlan': allocated_vlan}

    # TODO(tbahcman): get these from the drivers
    def _get_ext_net_name_gbp(self, network_name):
        """Get the external network name

        The name of the external network used in the APIC
        configuration file can be different from the name
        of the external network in Neutron, especially using
        the GBP workflow
        """
        prefix = network_name[:re.search(UUID_REGEX, network_name).start() - 1]
        return prefix.strip(APIC_OWNED)

    def _get_ext_net_name_neutron(self, network_name):
        """Get the external network name

        For Neutron workflow, the network name is returned
        as-is.
        """
        return network_name
