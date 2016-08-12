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

import abc

from oslo_log import log as logging
import webob.exc

from networking_cisco._i18n import _, _LE

from neutron.api import extensions
from neutron.api.v2 import attributes as attr
from neutron.api.v2 import base
from neutron.api.v2 import resource
from neutron.common import exceptions
from neutron.common import rpc as n_rpc
from neutron.extensions import bgp
from neutron import manager
from neutron.plugins.common import constants as svc_constants
from neutron import policy
from neutron import wsgi

from networking_cisco.plugins.cisco.extensions import ciscohostingdevicemanager


LOG = logging.getLogger(__name__)

class InvalidHostingDevice(exceptions.NotFound):
    message = _("Hosting device %(hosting_device_id)s does not exist or has "
                "been disabled.")

class SpeakerHostedByHostingDevice(exceptions.Conflict):
    message = _("Failed scheduling speaker %(speaker_id)s to hosting device "
                "%(hosting_device_id)s")

class SpeakerSchedulingFailed(exceptions.Conflict):
    message = _("Failed scheduling speaker %(speaker_id)s to hosting device "
                "%(hosting_device_id)s")


class SpeakerReschedulingFailed(exceptions.Conflict):
    message = _("Failed rescheduling speaker %(speaker_id)s: no eligible "
                "hosting device found.")


class SpeakerNotHostedByHostingDevice(exceptions.Conflict):
    message = _("The speaker %(speaker_id)s is not hosted by hosting device "
                "%(hosting_device_id)s.")


class SpeakerHostingDeviceMismatch(exceptions.Conflict):
    message = _("Cannot host %(speaker_type)s speaker %(speaker_id)s "
                "on hosting device %(hosting_device_id)s.")

SPEAKERTYPE_AWARE_SCHEDULER_ALIAS = 'speakertype-aware-scheduler'
DEVICE_BGP_SPEAKER = 'hosting-device-bgp-speaker'
DEVICE_BGP_SPEAKERS = DEVICE_BGP_SPEAKER + 's'
BGP_SPEAKER_DEVICE = 'bgp-speaker-hosting-device'
BGP_SPEAKER_DEVICES = BGP_SPEAKER_DEVICE + 's'
AUTO_SCHEDULE_ATTR = SPEAKERTYPE_AWARE_SCHEDULER_ALIAS + ':auto_schedule'
SHARE_HOST_ATTR = SPEAKERTYPE_AWARE_SCHEDULER_ALIAS + ':share_hosting_device'

class SpeakerHostingDeviceSchedulerController(wsgi.Controller):
    # how will I get plugin? svc_constants has no bgp. neutron.core_plugin 
    # or neutron.service_plugins? Possible fix BGP_EXT_ALIAS
    def get_plugin(self):
        plugin = manager.NeutronManager.get_service_plugins().get(
            bgp.BGP_EXT_ALIAS)
        if not plugin:
            LOG.error(_LE('No BGP service plugin registered to '
                          'handle speakertype-aware scheduling'))
            msg = _('The resource could not be found.')
            raise webob.exc.HTTPNotFound(msg)
        return plugin

    def index(self, request, **kwargs):
        plugin = self.get_plugin()
        policy.enforce(request.context, "get_%s" % DEVICE_BGP_SPEAKERS, {})
        return plugin.list_speakers_on_hosting_device(
            request.context, kwargs['hosting_device_id'])

    def create(self, request, body, **kwargs):
        plugin = self.get_plugin()
        policy.enforce(request.context, "create_%s" % DEVICE_BGP_SPEAKER, {})
        hosting_device_id = kwargs['hosting_device_id']
        speaker_id = body['speaker_id']
        result = plugin.add_speaker_to_hosting_device(
            request.context, hosting_device_id, speaker_id)
        notify(request.context, 'hosting_device.speaker.add', speaker_id,
               hosting_device_id)
        return result

    def delete(self, request, **kwargs):
        plugin = self.get_plugin()
        policy.enforce(request.context, "delete_%s" % DEVICE_BGP_SPEAKER, {})
        hosting_device_id = kwargs['hosting_device_id']
        speaker_id = kwargs['id']
        result = plugin.remove_speaker_from_hosting_device(
            request.context, hosting_device_id, speaker_id)
        notify(request.context, 'hosting_device.speaker.remove', speaker_id,
               hosting_device_id)
        return result

class HostingDevicesHostingSpeakerController(wsgi.Controller):
    # again this method
    def get_plugin(self):
        plugin = manager.NeutronManager.get_service_plugins().get(
            bgp.BGP_EXT_ALIAS)
        if not plugin:
            LOG.error(_LE('No BGP service plugin registered to '
                          'handle routertype-aware scheduling'))
            msg = _('The resource could not be found.')
            raise webob.exc.HTTPNotFound(msg)
        return plugin

    def index(self, request, **kwargs):
        plugin = self.get_plugin()
        policy.enforce(request.context, "get_%s" % BGP_SPEAKER_DEVICES, {})
        return plugin.list_hosting_devices_hosting_speaker(request.context,
                                                          kwargs['speaker_id'])


EXTENDED_ATTRIBUTES_2_0 = {
    'routers': {
        AUTO_SCHEDULE_ATTR: {'allow_post': True, 'allow_put': True,
                             'convert_to': attr.convert_to_boolean,
                             'validate': {'type:boolean': None},
                             'default': attr.ATTR_NOT_SPECIFIED,
                             'is_visible': True},
        SHARE_HOST_ATTR: {'allow_post': True, 'allow_put': False,
                          'convert_to': attr.convert_to_boolean,
                          'validate': {'type:boolean': None},
                          'default': attr.ATTR_NOT_SPECIFIED,
                          'is_visible': True},
    }
}

class Speakertypeawarescheduler(extensions.ExtensionDescriptor):
    """Extension class supporting l3 agent scheduler."""
    @classmethod
    def get_name(cls):
        return "Cisco routertype aware Scheduler"

    @classmethod
    def get_alias(cls):
        return SPEAKERTYPE_AWARE_SCHEDULER_ALIAS

    @classmethod
    def get_description(cls):
        return "Schedule speakers to Cisco hosting devices"

    @classmethod
    def get_namespace(cls):
        return ("http://docs.openstack.org/ext/" +
                SPEAKERTYPE_AWARE_SCHEDULER_ALIAS + "/api/v1.0")

    @classmethod
    def get_updated(cls):
        return "2014-03-31T10:00:00-00:00"

    @classmethod
    def get_resources(cls):
        """Returns Ext Resources."""
        exts = []
        parent = dict(member_name=ciscohostingdevicemanager.DEVICE,
                      collection_name=ciscohostingdevicemanager.DEVICES)
        controller = resource.Resource(
            SpeakerHostingDeviceSchedulerController(), base.FAULT_MAP)
        exts.append(extensions.ResourceExtension(
            DEVICE_L3_ROUTERS, controller, parent, path_prefix="/dev_mgr"))
        parent = dict(member_name="speaker",
                      collection_name=l3.ROUTERS)
        controller = resource.Resource(
            HostingDevicesHostingSpeakerController(), base.FAULT_MAP)
        exts.append(extensions.ResourceExtension(BGP_SPEAKER_DEVICES, controller,
                                                 parent))
        return exts

    def get_extended_resources(self, version):
        if version == "2.0":
            return EXTENDED_ATTRIBUTES_2_0
        else:
            return {}


class SpeakerTypeAwareSchedulerPluginBase(object):
    """REST API to operate the routertype-aware scheduler.
    All of method must be in an admin context.
    """
    @abc.abstractmethod
    def add_speaker_to_hosting_device(self, context, hosting_device_id,
                                     speaker_id):
        pass

    @abc.abstractmethod
    def remove_speaker_from_hosting_device(self, context, hosting_device_id,
                                          speaker_id):
        pass

    @abc.abstractmethod
    def list_speakers_on_hosting_device(self, context, hosting_device_id):
        pass

    @abc.abstractmethod
    def list_hosting_devices_hosting_speaker(self, context, speaker_id):
        pass

    def notify(context, action, speaker_id, hosting_device_id):
        info = {'id': hosting_device_id, 'speaker_id': speaker_id}
        notifier = n_rpc.get_notifier('speaker')
        notifier.info(context, action, {'hosting_device': info})        















