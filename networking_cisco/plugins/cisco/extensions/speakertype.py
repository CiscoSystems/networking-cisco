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

from networking_cisco._i18n import _

from neutron.api import extensions
from neutron.api.v2 import attributes as attr
from neutron.api.v2 import resource_helper
from neutron.common import exceptions
from neutron.plugins.common import constants
from neutron.services.bgp.common import constants as bgp_consts
from networking_cisco.plugins.cisco.common import utils

LOG = logging.getLogger(__name__)

SPEAKERTYPE = 'speakertype'
SPEAKERTYPE_ALIAS = SPEAKERTYPE
TYPE_ATTR = SPEAKERTYPE + ':id'
SPEAKER_TYPES = SPEAKERTYPE + 's'

RESOURCE_ATTRIBUTE_MAP = {
    SPEAKER_TYPES: {
        'id': {'allow_post': True, 'allow_put': False,
               'validate': {'type:uuid_or_none': None}, 'is_visible': True,
               'default': None, 'primary_key': True},
        'name': {'allow_post': True, 'allow_put': True,
                 'validate': {'type:string': None}, 'is_visible': True,
                 'default': ''},
        'description': {'allow_post': True, 'allow_put': True,
                        'validate': {'type:string_or_none': None},
                        'is_visible': True, 'default': None},
        'tenant_id': {'allow_post': True, 'allow_put': False,
                      'required_by_policy': True, 'is_visible': True},
        'template_id': {'allow_post': True, 'allow_put': False,
                        'required_by_policy': True,
                        'validate': {'type:uuid': None}, 'is_visible': True},
        # 'ha_enabled_by_default': {'allow_post': True, 'allow_put': True,
        #                           'convert_to': attr.convert_to_boolean,
        #                           'validate': {'type:boolean': None},
        #                           'default': False, 'is_visible': True},
        # 'shared': {'allow_post': True, 'allow_put': False,
        #            'convert_to': attr.convert_to_boolean,
        #            'validate': {'type:boolean': None}, 'default': True,
        #            'is_visible': True},
        #TODO(bobmel): add HA attribute: One of None, 'GPLB', 'VRRP', or 'HSRP'
        'slot_need': {'allow_post': True, 'allow_put': True,
                      'validate': {'type:non_negative': None},
                      'convert_to': attr.convert_to_int,
                      'default': 0, 'is_visible': True},
        'scheduler': {'allow_post': True, 'allow_put': False,
                      'required_by_policy': True,
                      'convert_to': utils.convert_validate_driver_class,
                      'is_visible': True},
        'driver': {'allow_post': True, 'allow_put': False,
                   'required_by_policy': True,
                   'convert_to': utils.convert_validate_driver_class,
                   'is_visible': True},
        'cfg_agent_service_helper': {
            'allow_post': True, 'allow_put': False,
            'required_by_policy': True,
            'convert_to': utils.convert_validate_driver_class,
            'is_visible': True},
        'cfg_agent_driver': {'allow_post': True, 'allow_put': False,
                             'required_by_policy': True,
                             'convert_to': utils.convert_validate_driver_class,
                             'is_visible': True},
        # 'local_as': {'allow_post': True, 'allow_put': True,
        #               'validate': {'type:non_negative': None},
        #               'convert_to': attr.convert_to_int,
        #               'default': 0, 'is_visible': True},
        # 'ip_version': {'allow_post': True, 'allow_put': True,
        #               'validate': {'type:non_negative': None},
        #               'convert_to': attr.convert_to_int,
        #               'default': 0, 'is_visible': True}
    }
}

EXTENDED_ATTRIBUTES_2_0 = {
    'speakers': {
        TYPE_ATTR: {'allow_post': True, 'allow_put': True,
                    'validate': {'type:string': None},
                    'default': attr.ATTR_NOT_SPECIFIED,
                    'is_visible': True},
    }
}

class Speakertype(extensions.ExtensionDescriptor):
    """Extension class to define different types of Neutron speakers.
    This class is used by Neutron's extension framework to support
    definition of different types of Neutron BGP Speakers.
    Attribute 'speaker_type:id' is the uuid or name of a certain speaker type.
    It can be set during creation of Neutron speaker. If a Neutron speaker is
    moved (by admin user) to a hosting device of a different hosting device
    type, the speaker type of the Neutron speaker will also change. Non-admin
    users can request that a Neutron speaker's type is changed.
    To create a speaker of speaker type <name>:
       (shell) speaker-create <speaker_name> --speaker_type:id <uuid_or_name>
    """

    @classmethod
    def get_name(cls):
        return "Speaker types for bgp service"

    @classmethod
    def get_alias(cls):
        return SPEAKERTYPE_ALIAS

    @classmethod
    def get_description(cls):
        return "Introduces speaker types for Neutron Speakers"

    @classmethod
    def get_namespace(cls):
        return "http://docs.openstack.org/ext/" + SPEAKERTYPE + "/api/v2.0"

    @classmethod
    def get_updated(cls):
        return "2014-02-07T10:00:00-00:00"

    @classmethod
    def get_resources(cls):
        """Returns Ext Resources."""
        plural_mappings = resource_helper.build_plural_mappings(
            {}, RESOURCE_ATTRIBUTE_MAP)
        attr.PLURALS.update(plural_mappings)
        # need to change L3_ROUTER_NAT in last argument
        # probably BGP? Because setup.cfg is where svc plugins come from
        return resource_helper.build_resource_info(plural_mappings,
                                                   RESOURCE_ATTRIBUTE_MAP,
                                                   bgp_consts.BGP_PLUGIN)

    def get_extended_resources(self, version):
        if version == "2.0":
            return EXTENDED_ATTRIBUTES_2_0
        else:
            return {}


# speaker_type exceptions
class SpeakerTypeInUse(exceptions.InUse):
    message = _("Speaker type %(id)s in use.")


class SpeakerTypeNotFound(exceptions.NotFound):
    message = _("Speaker type %(id)s does not exist")

class MultipleSpeakerTypes(exceptions.NeutronException):
    message = _("Multiple speaker type with same name %(name)s exist. Id "
                "must be used to specify speaker type.")


class SchedulerNotFound(exceptions.NetworkNotFound):
    message = _("Scheduler %(scheduler)s does not exist")


class SpeakerTypeAlreadyDefined(exceptions.NeutronException):
    message = _("Speaker type %(type) already exists")


class NoSuchHostingDeviceTemplateForSpeakerType(exceptions.NeutronException):
    message = _("No hosting device template with id %(type) exists")


class HostingDeviceTemplateUsedBySpeakerType(exceptions.NeutronException):
    message = _("Speaker type %(type) already defined for Hosting device "
                "template with id %(type)")


class SpeakerTypeHasSpeakers(exceptions.NeutronException):
    message = _("Speaker type %(type) cannot be deleted since speakers "
                "of that type exists")


class SpeakertypePluginBase(object):
    """REST API to manage speaker types.
    All methods except listing require admin context.
    """
    @abc.abstractmethod
    def create_speakertype(self, context, speakertype):
        """Creates a speaker type.
         Also binds it to the specified hosting device template.
         """
        pass

    @abc.abstractmethod
    def update_speakertype(self, context, id, speakertype):
        """Updates a speaker type."""
        pass

    @abc.abstractmethod
    def delete_speakertype(self, context, id):
        """Deletes a speaker type."""
        pass

    @abc.abstractmethod
    def get_speakertype(self, context, id, fields=None):
        """Lists defined speaker type."""
        pass

    @abc.abstractmethod
    def get_speakertypes(self, context, filters=None, fields=None,
                        sorts=None, limit=None, marker=None,
                        page_reverse=False):
        """Lists defined speaker types."""
        pass











