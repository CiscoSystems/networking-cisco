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

import sys

import mock
import netaddr
from oslo_config import cfg
from oslo_utils import uuidutils

from networking_cisco.plugins.cisco.cfg_agent.device_drivers.asr1k import (
    aci_asr1k_routing_driver as driver)
from networking_cisco.plugins.cisco.cfg_agent.device_drivers.asr1k import (
    aci_asr1k_snippets as snippets)
from networking_cisco.plugins.cisco.cfg_agent.device_drivers.asr1k import (
    asr1k_snippets as asr_snippets)
from networking_cisco.plugins.cisco.cfg_agent.service_helpers import (
    routing_svc_helper)
from networking_cisco.tests.unit.cisco.cfg_agent import (
    test_asr1k_routing_driver as asr1ktest)
from neutron.common import constants as l3_constants

sys.modules['ncclient'] = mock.MagicMock()
sys.modules['ciscoconfparse'] = mock.MagicMock()

_uuid = uuidutils.generate_uuid
HA_INFO = 'ha_info'
FAKE_ID = _uuid()
PORT_ID = _uuid()


class ASR1kRoutingDriverAci(asr1ktest.ASR1kRoutingDriver):
    def setUp(self):
        super(ASR1kRoutingDriverAci, self).setUp()

        device_params = {'management_ip_address': 'fake_ip',
                         'protocol_port': 22,
                         'credentials': {"user_name": "stack",
                                         "password": "cisco"},
                         'timeout': None,
                         'id': '0000-1',
                         'device_id': 'ASR-1'
                         }
        self.driver = driver.AciASR1kRoutingDriver(**device_params)
        self.driver._ncc_connection = mock.MagicMock()
        self.driver._check_response = mock.MagicMock(return_value=True)
        self.driver._check_acl = mock.MagicMock(return_value=False)
        self.ri_global.router['tenant_id'] = _uuid()
        self.router['tenant_id'] = _uuid()
        self.ri = routing_svc_helper.RouterInfo(FAKE_ID, self.router)
        self.vrf = self.ri.router['tenant_id']
        self.driver._get_vrfs = mock.Mock(return_value=[self.vrf])
        self.transit_next_hop = '1.103.2.254'
        self.transit_gw_ip = '1.103.2.1'
        self.transit_gw_vip = '1.103.2.2'
        self.transit_cidr = '1.103.2.0/24'
        self.transit_vlan = '1035'
        self.int_port = {'id': PORT_ID,
                         'ip_cidr': self.gw_ip_cidr,
                         'fixed_ips': [{'ip_address': self.gw_ip}],
                         'subnets': [{'cidr': self.gw_ip_cidr,
                                      'gateway_ip': self.gw_ip}],
                         'hosting_info': {
                             'physical_interface': self.phy_infc,
                             'segmentation_id': self.transit_vlan,
                             'gateway_ip': self.transit_gw_ip,
                             'next_hop': self.transit_next_hop,
                             'cidr_exposed': self.transit_cidr
                         },
                         HA_INFO: self.gw_ha_info}
        self.gw_port = {'id': PORT_ID,
                        'ip_cidr': self.gw_ip_cidr,
                        'fixed_ips': [{'ip_address': self.gw_ip}],
                        'subnets': [{'cidr': self.gw_ip_cidr,
                                     'gateway_ip': self.gw_ip}],
                        'hosting_info': {
                            'physical_interface': self.phy_infc,
                            'segmentation_id': self.vlan_int},
                        HA_INFO: self.gw_ha_info}
        self.port = self.int_port
        int_ports = [self.port]
        self.router[l3_constants.INTERFACE_KEY] = int_ports
        self.ri.internal_ports = int_ports
        self.ri_global.internal_ports = int_ports

    def test_internal_network_added(self):
        cfg.CONF.set_override('enable_multi_region', False, 'multi_region')
        self.driver.internal_network_added(self.ri, self.port)
        sub_interface = self.phy_infc + '.' + str(self.transit_vlan)
        net = netaddr.IPNetwork(self.gw_ip_cidr).network
        mask = netaddr.IPNetwork(self.gw_ip_cidr).netmask
        cfg_args_route = (self.vrf, net, mask, sub_interface,
            self.transit_next_hop)
        self.assert_edit_run_cfg(
            snippets.SET_TENANT_ROUTE_WITH_INTF, cfg_args_route)

        sub_interface = self.phy_infc + '.' + str(self.transit_vlan)
        mask = netaddr.IPNetwork(self.transit_cidr).netmask
        cfg_args_sub = (sub_interface, self.transit_vlan, self.vrf,
                        self.transit_gw_ip, mask)
        self.assert_edit_run_cfg(
            asr_snippets.CREATE_SUBINTERFACE_WITH_ID, cfg_args_sub)

        cfg_args_hsrp = self._generate_hsrp_cfg_args(
            sub_interface, self.gw_ha_group,
            self.ha_priority, self.transit_gw_vip,
            self.transit_vlan)
        self.assert_edit_run_cfg(
            asr_snippets.SET_INTC_ASR_HSRP_EXTERNAL, cfg_args_hsrp)

    def test_internal_network_added_with_multi_region(self):
        cfg.CONF.set_override('enable_multi_region', True, 'multi_region')
        is_multi_region_enabled = cfg.CONF.multi_region.enable_multi_region
        self.assertEqual(True, is_multi_region_enabled)

        region_id = cfg.CONF.multi_region.region_id

        vrf = self.vrf + "-" + region_id

        self.driver.internal_network_added(self.ri, self.port)

        sub_interface = self.phy_infc + '.' + str(self.transit_vlan)
        net = netaddr.IPNetwork(self.gw_ip_cidr).network
        mask = netaddr.IPNetwork(self.gw_ip_cidr).netmask
        cfg_args_route = (vrf, net, mask, sub_interface,
            self.transit_next_hop)
        self.assert_edit_run_cfg(
            snippets.SET_TENANT_ROUTE_WITH_INTF, cfg_args_route)

        sub_interface = self.phy_infc + '.' + str(self.transit_vlan)
        mask = netaddr.IPNetwork(self.transit_cidr).netmask
        cfg_args_sub = (sub_interface, region_id, self.transit_vlan, vrf,
                        self.transit_gw_ip, mask)
        self.assert_edit_run_cfg(
            asr_snippets.CREATE_SUBINTERFACE_REGION_ID_WITH_ID, cfg_args_sub)

        cfg_args_hsrp = self._generate_hsrp_cfg_args(
            sub_interface, self.gw_ha_group,
            self.ha_priority, self.transit_gw_vip,
            self.transit_vlan)
        self.assert_edit_run_cfg(
            asr_snippets.SET_INTC_ASR_HSRP_EXTERNAL, cfg_args_hsrp)

        cfg.CONF.set_override('enable_multi_region', False, 'multi_region')

    def test_internal_network_added_global_router(self):
        self.port = self.gw_port
        super(ASR1kRoutingDriverAci,
            self).test_internal_network_added_global_router()
        self.port = self.int_port

    def test_internal_network_added_global_router_with_multi_region(self):
        self.port = self.gw_port
        super(ASR1kRoutingDriverAci,
            self).test_internal_network_added_global_router_with_multi_region()
        self.port = self.int_port

    def test_driver_enable_internal_network_NAT(self):
        self.port = self.gw_port
        super(ASR1kRoutingDriverAci,
            self).test_driver_enable_internal_network_NAT()
        self.port = self.int_port

    def test_driver_enable_internal_network_NAT_with_multi_region(self):
        self.port = self.gw_port
        super(ASR1kRoutingDriverAci,
            self).test_driver_enable_internal_network_NAT_with_multi_region()
        self.port = self.int_port

    def test_driver_disable_internal_network_NAT_with_multi_region(self):
        self.port = self.gw_port
        super(ASR1kRoutingDriverAci,
            self).test_driver_disable_internal_network_NAT_with_multi_region()
        self.port = self.int_port

    def test_driver_disable_internal_network_NAT(self):
        self.port = self.gw_port
        super(ASR1kRoutingDriverAci,
            self).test_driver_disable_internal_network_NAT()
        self.port = self.int_port

    def test_internal_network_removed(self):
        self.driver._do_remove_sub_interface = mock.MagicMock()
        self.driver.internal_network_removed(self.ri, self.port)
        self.assertFalse(self.driver._do_remove_sub_interface.called)
