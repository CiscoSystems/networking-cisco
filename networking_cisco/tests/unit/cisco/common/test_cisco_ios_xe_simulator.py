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

# A tiny and simple Cisco IOS XE running config simulator.
# The intended use is to allow a developer to observe how the running config
# of an IOS XE device evolves as CLI commands are issued.
#
# Simple implies here that no CLI syntax or semantical checks are made so it
# is entirely up to the command issuer to ensure the correctness of the
# commands and their arguments.

from neutron.tests import base


class TestCiscoIOSXESimulator(base.BaseTestCase):
    def setUp(self):
        super(TestCiscoIOSXESimulator, self).setUp()


class TestMockNCClient(base.BaseTestCase):
    def setUp(self):
        super(TestMockNCClient, self).setUp()
