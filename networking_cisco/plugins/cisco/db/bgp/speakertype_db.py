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


from oslo_db import exception as db_exc
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import uuidutils
from sqlalchemy import exc as sql_exc
from sqlalchemy.orm import exc

from networking_cisco._i18n import _LE

from networking_cisco.plugins.cisco.db.bgp import bgp_models
# need a speakertype file in extensions
import networking_cisco.plugins.cisco.extensions.speakertype as speakertype

LOG = logging.getLogger(__name__)

class SpeakertypeDbMixin(speakertype.SpeakertypePluginBase):
    """Mixin class for Speaker types."""

    def create_speakertype(self, context, speakertype):
        """Creates a speaker type.

        Also binds it to the specified hosting device template.
        """
        LOG.debug("create_speakertype() called. Contents %s", speakertype)
        st = speakertype['speakertype']
        with context.session.begin(subtransactions=True):
            speakertype_db = bgp_models.SpeakerType(
                id=self._get_id(rt),
                tenant_id=st['tenant_id'],
                name=st['name'],
                description=st['description'],
                template_id=st['template_id'],
                # ha_enabled_by_default=st['ha_enabled_by_default'],
                shared=st['shared'],
                slot_need=st['slot_need'],
                scheduler=st['scheduler'],
                driver=st['driver'],
                cfg_agent_service_helper=st['cfg_agent_service_helper'],
                cfg_agent_driver=st['cfg_agent_driver'])
            context.session.add(speakertype_db)
        return self._make_speakertype_dict(speakertype_db)

    def update_speakertype(self, context, id, speakertype):
        LOG.debug("update_speakertype() called")
        st = speakertype['speakertype']
        with context.session.begin(subtransactions=True):
            st_query = context.session.query(bgp_models.SpeakerType)
            if not st_query.filter_by(id=id).update(st):
                raise speakertype.SpeakerTypeNotFound(id=id)
        return self.get_speakertype(context, id)


    def delete_speakertype(self, context, id):
        LOG.debug("delete_speakertype() called")
        try:
            with context.session.begin(subtransactions=True):
                speakertype_query = context.session.query(bgp_models.SpeakerType)
                if not speakertype_query.filter_by(id=id).delete():
                    raise speakertype.SpeakerTypeNotFound(id=id)
        except db_exc.DBError as e:
            with excutils.save_and_reraise_exception() as ctxt:
                if isinstance(e.inner_exception, sql_exc.IntegrityError):
                    ctxt.reraise = False
                    raise speakertype.SpeakerTypeInUse(id=id)

    def get_speakertype(self, context, id, fields=None):
        LOG.debug("get_speakertype() called")
        st_db = self._get_speakertype(context, id)
        return self._make_speakertype_dict(st_db, fields)

    def get_speakertypes(self, context, filters=None, fields=None,
                        sorts=None, limit=None, marker=None,
                        page_reverse=False):
        LOG.debug("get_speakertypes() called")
        return self._get_collection(context, bgp_models.speakerType,
                                    self._make_speakertype_dict,
                                    filters=filters, fields=fields,
                                    sorts=sorts, limit=limit,
                                    marker_obj=marker,
                                    page_reverse=page_reverse)

    def get_speakertype_by_id_name(self, context, id_or_name):
        return self._make_speakertype_dict(
            self.get_speakertype_db_by_id_name(context, id_or_name))

    def get_speakertype_db_by_id_name(self, context, id_or_name):
        query = context.session.query(bgp_models.SpeakerType)
        query = query.filter(bgp_models.SpeakerType.id == id_or_name)
        try:
            return query.one()
        except exc.MultipleResultsFound:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Database inconsistency: Multiple speaker types '
                              'with same id %s'), id_or_name)
                raise speakertype.SpeakerTypeNotFound(speaker_type=id_or_name)
        except exc.NoResultFound:
            query = context.session.query(bgp_models.SpeakerType)
            query = query.filter(bgp_models.SpeakerType.name == id_or_name)
            try:
                return query.one()
            except exc.MultipleResultsFound:
                with excutils.save_and_reraise_exception():
                    LOG.debug('Multiple router types with name %s found. '
                              'Id must be specified to allow arbitration.',
                              id_or_name)
                    raise speakertype.MultipleSpeakerTypes(name=id_or_name)
            except exc.NoResultFound:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('No speaker type with name %s found.'),
                              id_or_name)
                    raise speakertype.SpeakerTypeNotFound(id=id_or_name)

    def _get_speakertype(self, context, id):
        try:
            return self._get_by_id(context, bgp_models.SpeakerType, id)
        except exc.NoResultFound:
            raise speakertype.SpeakerTypeNotFound(id=id)

    def _make_speakertype_dict(self, speakertype, fields=None):
        res = {'id': speakertype['id'],
               'tenant_id': speakertype['tenant_id'],
               'name': speakertype['name'],
               'description': speakertype['description'],
               'template_id': speakertype['template_id'],
               'shared': speakertype['shared'],
               'slot_need': speakertype['slot_need'],
               'scheduler': speakertype['scheduler'],
               'driver': speakertype['driver'],
               'cfg_agent_service_helper': speakertype[
                   'cfg_agent_service_helper'],
               'cfg_agent_driver': speakertype['cfg_agent_driver']}
        return self._fields(res, fields)

    def _get_id(self, res):
        uuid = res.get('id')
        if uuid:
            return uuid
        return uuidutils.generate_uuid()






