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

from networking_cisco.plugins.cisco.extensions import routerhostingdevice
from networking_cisco.plugins.cisco.l3.drivers.asr1k import (
    asr1k_routertype_driver as asr1k)
from neutron.common import constants as l3_constants
from neutron import context as nctx
from neutron.i18n import _LE, _LI
from neutron import manager

from oslo_log import log as logging
from oslo_utils import importutils

LOG = logging.getLogger(__name__)


APIC_ML2_L3DRIVER_KLASS = (
    'apic_ml2.neutron.services.l3_router.apic_driver.ApicL3Driver')
GBP_L3DRIVER_KLASS = (
    'gbpservice.neutron.services.l3_router.apic_driver.ApicGBPL3Driver')
HOSTING_DEVICE_ATTR = routerhostingdevice.HOSTING_DEVICE_ATTR


class AciASR1kL3RouterDriver(asr1k.ASR1kL3RouterDriver):

    def __init__(self):
        super(AciASR1kL3RouterDriver, self).__init__()
        self._apic_driver = None

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
                if manager.NeutronManager.get_service_plugins()[
                    'GROUP_POLICY'].policy_driver_manager.policy_drivers[
                        'apic'].obj:
                    self._apic_driver = importutils.import_object(
                        GBP_L3DRIVER_KLASS,
                        nctx.get_admin_context_without_session()
                    )
                    self._apic_driver._plugin = self._l3_plugin
            except KeyError:
                    LOG.info(_LI("GBP service plugin not present -- skipping "
                                 "dynamic load of GBP L3 APIC driver."))
            except Exception:
                    LOG.error(_LE("GBP service plugin present, but dynamic "
                                  "load of GBP L3 APIC driver failed."))
                    return self._apic_driver
            if not self._apic_driver:
                try:
                    core_plugin = self._l3_plugin._core_plugin
                    if core_plugin.mechanism_manager.mech_drivers[
                            'cisco_apic_ml2'].obj:
                        self._apic_driver = importutils.import_object(
                            APIC_ML2_L3DRIVER_KLASS,
                            nctx.get_admin_context_without_session()
                        )
                        self._apic_driver._plugin = self._l3_plugin
                except KeyError:
                        LOG.error(_LE("APIC ML2 service plugin not present: "
                                      "no APIC L3 driver could be found "
                                      "(skipping dynamic load of APIC ML2 "
                                      "L3 driver."))
                except Exception:
                    LOG.error(_LE("APIC ML2 service plugin present, but "
                                  "dynamic load of APIC ML2 L3 driver "
                                  "failed."))
        return self._apic_driver

    def _get_router_id_from_port(self, r_port_context):
        current = r_port_context.current
        if (current['device_owner'] != l3_constants.DEVICE_OWNER_ROUTER_GW and
            current['device_owner'] != l3_constants.DEVICE_OWNER_ROUTER_INTF):
            # TODO(tbachman): raise exception?
            return None
        else:
            return current['device_id']

    def create_router_precommit(self, context, router_context):
        pass

    def create_router_postcommit(self, context, router_context):
        pass

    def update_router_precommit(self, context, router_context):
        pass

    def update_router_postcommit(self, context, router_context):
        current = router_context.current
        if current[HOSTING_DEVICE_ATTR] is None:
            return
        super(AciASR1kL3RouterDriver, self).update_router_postcommit(
            context, router_context)

        context._plugin = self
        router = router_context.current
        if router and router['tenant_id'] != '':
            self.apic_driver.update_router_postcommit(context, router)

    def delete_router_precommit(self, context, router_context):
        # TODO(tbachman): remove setting of _plugin?
        context._plugin = self
        router = router_context.current
        router_id = router['id']
        if router and router['tenant_id'] != '':
            self.apic_driver.delete_router_precommit(context, router_id)

    def delete_router_postcommit(self, context, router_context):
        pass

    def schedule_router_precommit(self, context, router_context):
        pass

    def schedule_router_postcommit(self, context, router_context):
        super(AciASR1kL3RouterDriver, self).schedule_router_postcommit(
            context, router_context)

    def unschedule_router_precommit(self, context, router_context):
        pass

    def unschedule_router_postcommit(self, context, router_context):
        super(AciASR1kL3RouterDriver, self).unschedule_router_postcommit(
            context, router_context)

    def add_router_interface_precommit(self, context, r_port_context):
        pass

    def add_router_interface_postcommit(self, context, r_port_context):
        port = r_port_context.current
        router_id = r_port_context.current_router
        interface_info = {'port_id': port['id']}
        if port and port['tenant_id'] != '':
            self.apic_driver.add_router_interface_postcommit(
                context, router_id, interface_info)

    def remove_router_interface_precommit(self, context, r_port_context):
        port = r_port_context.current
        router_id = self._get_router_id_from_port(r_port_context)
        interface_info = {'port_id': port['id']}
        if port and port['tenant_id'] != '':
            self.apic_driver.remove_router_interface_precommit(
                context, router_id, interface_info)

    def remove_router_interface_postcommit(self, context, r_port_context):
        pass

    def create_floatingip_postcommit(self, context, fip_context):
        self.apic_driver.create_floatingip_postcommit(
            context, fip_context.current)

    def update_floatingip_precommit(self, context, fip_context):
        floatingip = fip_context.current
        fip_id = getattr(floatingip, 'id', None)
        if fip_id is None:
            fip_id = fip_context.original['id']
        self.apic_driver.update_floatingip_precommit(
            context, fip_id, floatingip)

    def update_floatingip_postcommit(self, context, fip_context):
        floatingip = fip_context.current
        context.current = floatingip
        fip_id = getattr(floatingip, 'id', None)
        if fip_id is None:
            fip_id = fip_context.original['id']
        self.apic_driver.update_floatingip_postcommit(
            context, fip_id, floatingip)

    def delete_floatingip_precommit(self, context, fip_context):
        self.apic_driver.delete_floatingip_precommit(
            context, fip_context.current)

    def delete_floatingip_postcommit(self, context, fip_context):
        self.apic_driver.delete_floatingip_postcommit(
            context, fip_context.current)
