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

# =============================================================================
# Set tenant network ip route with interface
# Syntax: ip route vrf <vrf-name> <tenant subnet> <mask> <interface> <next hop>
# eg:
#   $(config)ip route vrf nrouter-e7d4y5 40.0.0.0 255.255.255.0 pc.4 1.0.10.255
# =============================================================================
SET_TENANT_ROUTE_WITH_INTF = """
<config>
        <cli-config-data>
            <cmd>ip route vrf %s %s %s %s %s</cmd>
        </cli-config-data>
</config>
"""

# =============================================================================
# Remove tenant network ip route
# Syntax: ip route vrf <vrf-name> <tenant subnet> <mask> <interface> <next hop>
# eg:
#   $(config)ip route vrf nrouter-e7d4y5 40.0.0.0 255.255.255.0 pc.4 1.0.10.255
# =============================================================================
REMOVE_TENANT_ROUTE_WITH_INTF = """
<config>
        <cli-config-data>
            <cmd>ip route vrf %s %s %s %s %s</cmd>
        </cli-config-data>
</config>
"""

# =============================================================================
# Set default ipv6 route with interface
# Syntax: ipv6 route vrf <vrf-name> ::/0 <interface> nexthop-vrf default
# eg:
# $(config)ipv6 route vrf nrouter-e7d4y5 ::/0 po10.304 nexthop-vrf default
# =============================================================================
# ToDo(Hareesh): Seems unused, remove commented below after testing
# DEFAULT_ROUTE_V6_WITH_INTF_CFG = 'ipv6 route vrf %s ::/0 %s %s'

SET_TENANT_ROUTE_V6_WITH_INTF = """
<config>
        <cli-config-data>
            <cmd>ipv6 route vrf %s ::/0 %s nexthop-vrf default</cmd>
        </cli-config-data>
</config>
"""

# ============================================================================
# Remove default ipv6 route
# Syntax: no ipv6 route vrf <vrf-name> ::/0 <interface> nexthop-vrf default
# eg:
# $(config)no ipv6 route vrf nrouter-e7d4y5 ::/0 po10.304 nexthop-vrf default
# ============================================================================
REMOVE_TENANT_ROUTE_V6_WITH_INTF = """
<config>
        <cli-config-data>
            <cmd>no ipv6 route vrf %s ::/0 %s nexthop-vrf default</cmd>
        </cli-config-data>
</config>
"""
