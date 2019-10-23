"""Module provider for RcodeZero"""
from __future__ import absolute_import
import json
import logging

import requests
from lexicon.providers.base import Provider as BaseProvider


LOGGER = logging.getLogger(__name__)

NAMESERVER_DOMAINS = ['rcode0.net']


def provider_parser(subparser):
    """Return the parser for this provider"""
    subparser.add_argument(
        "--auth-token", help="specify token for authentication")


class Provider(BaseProvider):
    """Provider class for Cloudflare"""
    def __init__(self, config):
        super(Provider, self).__init__(config)
        self.domain_id = None
        self._zone_data = None
        self.api_endpoint = 'https://my.rcodezero.at/api/v1'

    def _authenticate(self):
        if self._zone_data is None:
            self._zone_data = self._get('/zones/' +self.domain)

        self.domain_id = self.domain

    # Create record.

    def _create_record(self, rtype, name, content):
        rname = self._fqdn_name(name)
        newcontent = self._clean_content(rtype, content)

        updated_data = {
            'name': rname,
            'type': rtype,
            'records': [],
            'ttl': self._get_lexicon_option('ttl') or 600,
            'changetype': 'ADD'
        }

        updated_data['records'].append({'content': newcontent, 'disabled': False})

        payload = self._get(
            '/zones/{0}/rrsets?page_size=-1'.format(self.domain_id))

        for rrset in payload['data']:
            if rrset['name'] == rname and rrset['type'] == rtype:
                updated_data['ttl'] = rrset['ttl']

                for record in rrset['records']:
                    if record['content'] != newcontent:
                        updated_data['records'].append(
                            {
                                'content': record['content'],
                                'disabled': record['disabled']
                            })
                    updated_data['changetype'] = 'UPDATE'
                break

        request = [updated_data]
        LOGGER.debug('request: %s', request)

        self._patch('/zones/' + self.domain + '/rrsets', data=request)
        return True

    # List all records. Return an empty list if no records found
    # type, name and content are used to filter records.
    # If possible filter during the query, otherwise filter after response is received.
    def _list_records(self, rtype=None, name=None, content=None):
        filter_obj = {'per_page': 100}
        if rtype:
            filter_obj['type'] = rtype
        if name:
            filter_obj['name'] = self._full_name(name)
        if content:
            filter_obj['content'] = content

        payload = self._get(
            '/zones/{0}/rrsets?page_size=-1'.format(self.domain_id))

        records = []
        for rrset in payload['data']:
            if (name is None or self._fqdn_name(rrset['name']) == self._fqdn_name(
                    name)) and (rtype is None or rrset['type'] == rtype):
                for record in rrset['records']:
                    if content is None or record['content'] == self._clean_content(rtype, content):
                    # rcode0 does not have a record id, so lets create one
                        processed_record = {
                            'type': rrset['type'],
                            'name': self._full_name(rrset['name']),
                            'ttl': rrset['ttl'],
                            'content': self._unclean_content(rrset['type'], record['content']),
                            'id': self._make_identifier(rrset['type'],
                                                        rrset['name'], record['content'])
                        }
                        records.append(processed_record)

        LOGGER.debug('list_records: %s', records)
        return records

    def _update_record(self, identifier, rtype=None, name=None, content=None):
        self._delete_record(identifier, rtype, name, None)
        return self._create_record(rtype, name, content)

    # Delete an existing record.
    # If record does not exist, do nothing.
    def _delete_record(self, identifier=None, rtype=None, name=None, content=None):

        if identifier is not None:
            rtype, name, content = self._parse_identifier(identifier)

        LOGGER.debug("delete %s %s %s", rtype, name, content)
        if rtype is None or name is None:
            raise Exception("Must specify at least both rtype and name")

        payload = self._get(
            '/zones/{0}/rrsets?page_size=-1'.format(self.domain_id))

        for rrset in payload['data']:
            if rrset['type'] == rtype and self._fqdn_name(rrset['name']) == self._fqdn_name(name):
                update_data = rrset

                if content is None:
                    update_data['records'] = []
                    update_data['changetype'] = 'DELETE'
                else:
                    new_record_list = []
                    for record in update_data['records']:
                        if self._clean_content(rrset['type'], content) != record['content']:
                            new_record_list.append(record)

                    update_data['records'] = new_record_list
                    update_data['changetype'] = 'UPDATE'
                break

        request = [update_data]
        LOGGER.debug('request: %s', request)

        self._patch('/zones/' + self.domain + '/rrsets', data=request)
        return True

    # Helpers
    def _request(self, action='GET', url='/', data=None, query_params=None):
        if data is None:
            data = {}
        if query_params is None:
            query_params = {}
        response = requests.request(action, self.api_endpoint + url, params=query_params,
                                    data=json.dumps(data),
                                    headers={
                                        'Authorization': 'Bearer ' +
                                                         self._get_provider_option('auth_token'),
                                        'Content-Type': 'application/json'
                                    })
        # if the request fails for any reason, throw an error.
        if response.status_code >= 400:
            LOGGER.error('Bad Request: %s', response.text)
        response.raise_for_status()
        return response.json()

    # generate a unique id for a give record
    def _make_identifier(self, rtype, name, content):  # pylint: disable=no-self-use
        return "{}/{}={}".format(rtype, name, content)

    def _parse_identifier(self, identifier):  # pylint: disable=no-self-use
        parts = identifier.split('/')
        rtype = parts[0]
        parts = parts[1].split('=')
        name = parts[0]
        content = "=".join(parts[1:])
        return rtype, name, content

    def _clean_content(self, rtype, content):
        if rtype in ("TXT", "LOC"):
            if content[0] != '"':
                content = '"' + content
            if content[-1] != '"':
                content += '"'
        elif rtype == "CNAME":
            content = self._fqdn_name(content)
        return content

    def _unclean_content(self, rtype, content):
        if rtype in ("TXT", "LOC"):
            content = content.strip('"')
        elif rtype == "CNAME":
            content = self._full_name(content)
        return content
