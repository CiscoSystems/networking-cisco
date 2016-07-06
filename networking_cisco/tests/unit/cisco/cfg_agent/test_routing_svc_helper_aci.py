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


import mock
from networking_cisco.plugins.cisco.cfg_agent.service_helpers import (
    routing_svc_helper_aci as svc_helper)
from networking_cisco.tests.unit.cisco.cfg_agent import (
    test_routing_svc_helper as helper)


class TestBasicRoutingOperationsAci(helper.TestBasicRoutingOperations):

    def setUp(self):
        super(TestBasicRoutingOperationsAci, self).setUp()
        self.routing_helper = svc_helper.RoutingServiceHelperAci(
            helper.HOST, self.conf, self.agent)
        self.routing_helper._internal_network_added = mock.Mock()
        self.routing_helper._external_gateway_added = mock.Mock()
        self.routing_helper._internal_network_removed = mock.Mock()
        self.routing_helper._external_gateway_removed = mock.Mock()
        self.driver = self._mock_driver_and_hosting_device(
            self.routing_helper)
