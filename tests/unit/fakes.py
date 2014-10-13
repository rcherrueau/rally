# Copyright 2013: Mirantis Inc.
# All Rights Reserved.
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

import multiprocessing
import random
import re
import string
import uuid

from ceilometerclient import exc as ceilometer_exc
from glanceclient import exc
import mock
from neutronclient.common import exceptions as neutron_exceptions
from novaclient import exceptions as nova_exceptions

from rally.benchmark.context import base as base_ctx
from rally.benchmark.scenarios import base
from rally.objects import endpoint
from rally import utils as rally_utils


def generate_uuid():
    return str(uuid.uuid4())


def generate_name(prefix="", length=12, choices=string.lowercase):
    """Generate pseudo-random name.

    :param prefix: str, custom prefix for genertated name
    :param length: int, length of autogenerated part of result name
    :param choices: str, chars that accurs in generated name
    :returns: str, pseudo-random name
    """
    return prefix + ''.join(random.choice(choices) for i in range(length))


def generate_mac():
    """Generate pseudo-random MAC address.

    :returns: str, MAC address
    """
    rand_str = generate_name(choices="0123456789abcdef", length=12)
    return ":".join(re.findall("..", rand_str))


def setup_dict(data, required=None, defaults=None):
    """Setup and validate dict scenario_base. on mandatory keys and default data.

    This function reduces code that constructs dict objects
    with specific schema (e.g. for API data).

    :param data: dict, input data
    :param required: list, mandatory keys to check
    :param defaults: dict, default data
    :returns: dict, with all keys set
    :raises: IndexError, ValueError
    """
    required = required or []
    for i in set(required) - set(data.keys()):
        raise IndexError("Missed: %s" % i)

    defaults = defaults or {}
    for i in set(data.keys()) - set(required + defaults.keys()):
        raise ValueError("Unexpected: %s" % i)

    defaults.update(data)
    return defaults


class FakeResource(object):

    def __init__(self, manager=None, name=None, status="ACTIVE", items=None,
                 deployment_uuid=None, id=None):
        self.name = name or generate_uuid()
        self.status = status
        self.manager = manager
        self.uuid = generate_uuid()
        self.id = id or self.uuid
        self.items = items or {}
        self.deployment_uuid = deployment_uuid or generate_uuid()

    def __getattr__(self, name):
        # NOTE(msdubov): e.g. server.delete() -> manager.delete(server)
        def manager_func(*args, **kwargs):
            getattr(self.manager, name)(self, *args, **kwargs)
        return manager_func

    def __getitem__(self, key):
        return self.items[key]


class FakeServer(FakeResource):

    def suspend(self):
        self.status = "SUSPENDED"


class FakeFailedServer(FakeResource):

    def __init__(self, manager=None):
        super(FakeFailedServer, self).__init__(manager, status="ERROR")


class FakeImage(FakeResource):

    def __init__(self, manager=None, id="image-id-0", min_ram=0,
                 size=0, min_disk=0, name=None):
        super(FakeImage, self).__init__(manager, id=id, name=name)
        self.min_ram = min_ram
        self.size = size
        self.min_disk = min_disk
        self.update = mock.MagicMock()


class FakeFailedImage(FakeResource):

    def __init__(self, manager=None):
        super(FakeFailedImage, self).__init__(manager, status="error")


class FakeFloatingIP(FakeResource):
    pass


class FakeFloatingIPPool(FakeResource):
    pass


class FakeTenant(FakeResource):

    def __init__(self, manager, name):
        super(FakeTenant, self).__init__(manager, name=name)


class FakeUser(FakeResource):
    pass


class FakeNetwork(FakeResource):
    pass


class FakeFlavor(FakeResource):

    def __init__(self, id="flavor-id-0", manager=None, ram=0, disk=0):
        super(FakeFlavor, self).__init__(manager, id=id)
        self.ram = ram
        self.disk = disk


class FakeKeypair(FakeResource):
    pass


class FakeStack(FakeResource):
    pass


class FakeDomain(FakeResource):
    pass


class FakeQuotas(FakeResource):
    pass


class FakeSecurityGroup(FakeResource):

    def __init__(self, manager=None, rule_manager=None):
        super(FakeSecurityGroup, self).__init__(manager)
        self.rule_manager = rule_manager

    @property
    def rules(self):
        return [rule for rule in self.rule_manager.list()
                if rule.parent_group_id == self.id]


class FakeSecurityGroupRule(FakeResource):
    def __init__(self, name, **kwargs):
        super(FakeSecurityGroupRule, self).__init__(name)
        if 'cidr' in kwargs:
            kwargs['ip_range'] = {'cidr': kwargs['cidr']}
            del kwargs['cidr']
        for key, value in kwargs.items():
            self.items[key] = value
            setattr(self, key, value)


class FakeAlarm(FakeResource):
    def __init__(self, manager=None, **kwargs):
        super(FakeAlarm, self).__init__(manager)
        self.meter_name = kwargs.get('meter_name')
        self.threshold = kwargs.get('threshold')
        self.alarm_id = kwargs.get('alarm_id', 'fake-alarm-id')
        self.optional_args = kwargs.get('optional_args', {})


class FakeSample(FakeResource):
    def __init__(self, manager=None, **kwargs):
        super(FakeSample, self).__init__(manager)
        self.counter_name = kwargs.get('counter_name', 'fake-counter-name')
        self.counter_type = kwargs.get('counter_type', 'fake-counter-type')
        self.counter_unit = kwargs.get('counter_unit', 'fake-counter-unit')
        self.counter_volume = kwargs.get('counter_volume', 100)
        self.resource_id = kwargs.get('resource_id', 'fake-resource-id')


class FakeVolume(FakeResource):
    pass


class FakeVolumeType(FakeResource):
    pass


class FakeVolumeTransfer(FakeResource):
    pass


class FakeVolumeSnapshot(FakeResource):
    pass


class FakeVolumeBackup(FakeResource):
    pass


class FakeRole(FakeResource):
    pass


class FakeQueue(FakeResource):
    def __init__(self, manager=None, name='myqueue'):
        super(FakeQueue, self).__init__(manager, name)
        self.queue_name = name
        self.messages = FakeMessagesManager(name)

    def post_message(self, messages):
        for msg in messages:
            self.messages.create(**msg)


class FakeMessage(FakeResource):
    def __init__(self, manager=None, **kwargs):
        super(FakeMessage, self).__init__(manager)
        self.body = kwargs.get('body', 'fake-body')
        self.ttl = kwargs.get('ttl', 100)


class FakeManager(object):

    def __init__(self):
        super(FakeManager, self).__init__()
        self.cache = {}
        self.resources_order = []

    def get(self, resource_uuid):
        return self.cache.get(resource_uuid, None)

    def delete(self, resource_uuid):
        cached = self.get(resource_uuid)
        if cached is not None:
            cached.status = "DELETED"
            del self.cache[resource_uuid]
            self.resources_order.remove(resource_uuid)

    def _cache(self, resource):
        self.resources_order.append(resource.uuid)
        self.cache[resource.uuid] = resource
        return resource

    def list(self, **kwargs):
        return [self.cache[key] for key in self.resources_order]

    def find(self, **kwargs):
        for resource in self.cache.values():
            match = True
            for key, value in kwargs.items():
                if getattr(resource, key, None) != value:
                    match = False
                    break
            if match:
                return resource


class FakeServerManager(FakeManager):

    def __init__(self, image_mgr=None):
        super(FakeServerManager, self).__init__()
        self.images = image_mgr or FakeImageManager()

    def get(self, resource_uuid):
        server = self.cache.get(resource_uuid, None)
        if server is not None:
            return server
        raise nova_exceptions.NotFound("Server %s not found" % (resource_uuid))

    def _create(self, server_class=FakeServer, name=None):
        server = self._cache(server_class(self))
        if name is not None:
            server.name = name
        return server

    def create(self, name, image_id, flavor_id, **kwargs):
        return self._create(name=name)

    def create_image(self, server, name):
        image = self.images._create()
        return image.uuid

    def add_floating_ip(self, server, fip):
        pass

    def remove_floating_ip(self, server, fip):
        pass

    def delete(self, resource):
        if not isinstance(resource, basestring):
            resource = resource.id

        cached = self.get(resource)
        if cached is not None:
            cached.status = "DELETED"
            del self.cache[resource]
            self.resources_order.remove(resource)


class FakeFailedServerManager(FakeServerManager):

    def create(self, name, image_id, flavor_id, **kwargs):
        return self._create(FakeFailedServer, name)


class FakeImageManager(FakeManager):

    def __init__(self):
        super(FakeImageManager, self).__init__()

    def get(self, resource_uuid):
        image = self.cache.get(resource_uuid, None)
        if image is not None:
            return image
        raise exc.HTTPNotFound("Image %s not found" % (resource_uuid))

    def _create(self, image_class=FakeImage, name=None, id=None):
        image = self._cache(image_class(self))
        image.owner = "dummy"
        image.id = image.uuid
        if name is not None:
            image.name = name
        return image

    def create(self, name, copy_from, container_format, disk_format):
        return self._create(name=name)

    def delete(self, resource):
        if not isinstance(resource, basestring):
            resource = resource.id

        cached = self.get(resource)
        if cached is not None:
            cached.status = "DELETED"
            del self.cache[resource]
            self.resources_order.remove(resource)


class FakeFailedImageManager(FakeImageManager):

    def create(self, name, copy_from, container_format, disk_format):
        return self._create(FakeFailedImage, name)


class FakeFloatingIPsManager(FakeManager):

    def create(self):
        return FakeFloatingIP(self)


class FakeFloatingIPPoolsManager(FakeManager):

    def create(self):
        return FakeFloatingIPPool(self)


class FakeTenantsManager(FakeManager):

    def create(self, name):
        return self._cache(FakeTenant(self, name))


class FakeNetworkManager(FakeManager):

    def create(self, net_id):
        net = FakeNetwork(self)
        net.id = net_id
        return self._cache(net)


class FakeFlavorManager(FakeManager):

    def create(self):
        flv = FakeFlavor(self)
        return self._cache(flv)


class FakeKeypairManager(FakeManager):

    def create(self, name, public_key=None):
        kp = FakeKeypair(self)
        kp.name = name or kp.name
        return self._cache(kp)

    def delete(self, resource):
        if not isinstance(resource, basestring):
            resource = resource.id

        cached = self.get(resource)
        if cached is not None:
            cached.status = "DELETED"
            del self.cache[resource]
            self.resources_order.remove(resource)


class FakeStackManager(FakeManager):

    def create(self, name):
        stack = FakeStack(self)
        stack.name = name or stack.name
        return self._cache(stack)

    def delete(self, resource):
        if not isinstance(resource, basestring):
            resource = resource.id

        cached = self.get(resource)
        if cached is not None:
            cached.status = "DELETE_COMPLETE"
            del self.cache[resource]
            self.resources_order.remove(resource)


class FakeDomainManager(FakeManager):

    def create(self, name):
        domain = FakeDomain(self)
        domain.name = name or domain.name
        return self._cache(domain)

    def delete(self, resource):
        if not isinstance(resource, basestring):
            resource = resource.id

        cached = self.get(resource)
        if cached is not None:
            cached.status = "DELETE_COMPLETE"
            del self.cache[resource]
            self.resources_order.remove(resource)


class FakeNovaQuotasManager(FakeManager):

    def update(self, tenant_id, **kwargs):
        fq = FakeQuotas(self)
        return self._cache(fq)

    def delete(self, tenant_id):
        pass


class FakeCinderQuotasManager(FakeManager):

    def update(self, tenant_id, **kwargs):
        fq = FakeQuotas(self)
        return self._cache(fq)

    def delete(self, tenant_id):
        pass


class FakeSecurityGroupManager(FakeManager):
    def __init__(self, rule_manager=None):
        super(FakeSecurityGroupManager, self).__init__()
        self.rule_manager = rule_manager
        self.create('default')

    def create(self, name, description=""):
        sg = FakeSecurityGroup(
            manager=self,
            rule_manager=self.rule_manager)
        sg.name = name or sg.name
        sg.description = description
        return self._cache(sg)

    def find(self, name, **kwargs):
        kwargs['name'] = name
        for resource in self.cache.values():
            match = True
            for key, value in kwargs.items():
                if getattr(resource, key, None) != value:
                    match = False
                    break
            if match:
                return resource
        raise nova_exceptions.NotFound('Security Group not found')

    def delete(self, resource):
        if not isinstance(resource, basestring):
            resource = resource.id

        cached = self.get(resource)
        if cached is not None:
            cached.status = "DELETED"
            del self.cache[resource]
            self.resources_order.remove(resource)


class FakeSecurityGroupRuleManager(FakeManager):
    def __init__(self):
        super(FakeSecurityGroupRuleManager, self).__init__()

    def create(self, parent_group_id, **kwargs):
        kwargs['parent_group_id'] = parent_group_id
        sgr = FakeSecurityGroupRule(self, **kwargs)
        return self._cache(sgr)


class FakeUsersManager(FakeManager):

    def create(self, username, password, email, tenant_id):
        user = FakeUser(manager=self, name=username)
        user.name = username or user.name
        return self._cache(user)


class FakeServicesManager(FakeManager):

    def list(self):
        return []


class FakeVolumeManager(FakeManager):
    def __init__(self):
        super(FakeVolumeManager, self).__init__()
        self.__volumes = {}
        self.__tenant_id = generate_uuid()

    def create(self, size=None, **kwargs):
        volume = FakeVolume(self)
        volume.size = size or 1
        volume.name = kwargs.get('display_name', volume.name)
        volume.status = "available"
        volume.tenant_id = self.__tenant_id
        self.__volumes[volume.id] = volume
        return self._cache(volume)

    def list(self):
        return self.__volumes.values()

    def delete(self, resource):
        super(FakeVolumeManager, self).delete(resource.id)
        del self.__volumes[resource.id]


class FakeVolumeTypeManager(FakeManager):

    def create(self, name):
        vol_type = FakeVolumeType(self)
        vol_type.name = name or vol_type.name
        return self._cache(vol_type)


class FakeVolumeTransferManager(FakeManager):
    def __init__(self):
        super(FakeVolumeTransferManager, self).__init__()
        self.__volume_transfers = {}

    def list(self):
        return self.__volume_transfers.values()

    def create(self, name):
        transfer = FakeVolumeTransfer(self)
        transfer.name = name or transfer.name
        self.__volume_transfers[transfer.id] = transfer
        return self._cache(transfer)

    def delete(self, resource):
        super(FakeVolumeTransferManager, self).delete(resource.id)
        del self.__volume_transfers[resource.id]


class FakeVolumeSnapshotManager(FakeManager):
    def __init__(self):
        super(FakeVolumeSnapshotManager, self).__init__()
        self.__snapshots = {}
        self.__tenant_id = generate_uuid()

    def create(self, name, force=False, display_name=None):
        snapshot = FakeVolumeSnapshot(self)
        snapshot.name = name or snapshot.name
        snapshot.status = "available"
        snapshot.tenant_id = self.__tenant_id
        self.__snapshots[snapshot.id] = snapshot
        return self._cache(snapshot)

    def list(self):
        return self.__snapshots.values()

    def delete(self, resource):
        super(FakeVolumeSnapshotManager, self).delete(resource.id)
        del self.__snapshots[resource.id]


class FakeVolumeBackupManager(FakeManager):
    def __init__(self):
        super(FakeVolumeBackupManager, self).__init__()
        self.__backups = {}
        self.__tenant_id = generate_uuid()

    def create(self, name):
        backup = FakeVolumeBackup(self)
        backup.name = name or backup.name
        self.__backups[backup.id] = backup
        return self._cache(backup)

    def list(self):
        return self.__backups.values()

    def delete(self, resource):
        super(FakeVolumeBackupManager, self).delete(resource.id)
        del self.__backups[resource.id]


class FakeRolesManager(FakeManager):

    def create(self, role_id, name):
        role = FakeRole(self)
        role.name = name
        role.id = role_id
        return self._cache(role)

    def roles_for_user(self, user, tenant):
        role = FakeRole(self)
        role.name = 'admin'
        return [role, ]


class FakeAlarmManager(FakeManager):

    def get(self, alarm_id):
        alarm = self.find(alarm_id=alarm_id)
        if alarm:
            return [alarm]
        raise ceilometer_exc.HTTPNotFound(
            "Alarm with %s not found" % (alarm_id))

    def update(self, alarm_id, **fake_alarm_dict_diff):
        alarm = self.get(alarm_id)[0]
        for attr, value in fake_alarm_dict_diff.iteritems():
            setattr(alarm, attr, value)
        return alarm

    def create(self, **kwargs):
        alarm = FakeAlarm(self, **kwargs)
        return self._cache(alarm)

    def delete(self, alarm_id):
        alarm = self.find(alarm_id=alarm_id)
        if alarm is not None:
            alarm.status = "DELETED"
            del self.cache[alarm.id]
            self.resources_order.remove(alarm.id)


class FakeSampleManager(FakeManager):

    def create(self, **kwargs):
        sample = FakeSample(self, **kwargs)
        return [self._cache(sample)]


class FakeMeterManager(FakeManager):

    def list(self):
        return ['fake-meter']


class FakeCeilometerResourceManager(FakeManager):

    def list(self):
        return ['fake-resource']


class FakeStatisticsManager(FakeManager):

    def list(self, meter):
        return ['%s-statistics' % meter]


class FakeQueryManager(FakeManager):

    def query(self, filter, orderby, limit):
        return ['fake-query-result']


class FakeQueuesManager(FakeManager):
    def __init__(self):
        super(FakeQueuesManager, self).__init__()
        self.__queues = {}

    def create(self, name):
        queue = FakeQueue(self, name)
        self.__queues[queue.name] = queue
        return self._cache(queue)

    def list(self):
        return self.__queues.values()

    def delete(self, queue):
        super(FakeQueuesManager, self).delete(queue.name)
        del self.__queues[queue.name]


class FakeMessagesManager(FakeManager):
    def __init__(self, queue='myqueue'):
        super(FakeMessagesManager, self).__init__()
        self.__queue = queue
        self.__messages = {}

    def create(self, **kwargs):
        message = FakeMessage(self, **kwargs)
        self.__messages[message.id] = message
        return self._cache(message)

    def list(self):
        return self.__messages.values()

    def delete(self, message):
        super(FakeMessagesManager, self).delete(message.id)
        del self.__messages[message.id]


class FakeServiceCatalog(object):
    def get_endpoints(self):
        return {'image': [{'publicURL': 'http://fake.to'}],
                'metering': [{'publicURL': 'http://fake.to'}]}

    def url_for(self, **kwargs):
        return 'http://fake.to'


class FakeGlanceClient(object):

    def __init__(self, failed_image_manager=False):
        if failed_image_manager:
            self.images = FakeFailedImageManager()
        else:
            self.images = FakeImageManager()


class FakeCinderClient(object):

    def __init__(self):
        self.volumes = FakeVolumeManager()
        self.volume_types = FakeVolumeTypeManager()
        self.transfers = FakeVolumeTransferManager()
        self.volume_snapshots = FakeVolumeSnapshotManager()
        self.backups = FakeVolumeBackupManager()
        self.quotas = FakeCinderQuotasManager()


class FakeNovaClient(object):

    def __init__(self, failed_server_manager=False):
        self.images = FakeImageManager()
        if failed_server_manager:
            self.servers = FakeFailedServerManager(self.images)
        else:
            self.servers = FakeServerManager(self.images)
        self.floating_ips = FakeFloatingIPsManager()
        self.floating_ip_pools = FakeFloatingIPPoolsManager()
        self.networks = FakeNetworkManager()
        self.flavors = FakeFlavorManager()
        self.keypairs = FakeKeypairManager()
        self.security_group_rules = FakeSecurityGroupRuleManager()
        self.security_groups = FakeSecurityGroupManager(
            rule_manager=self.security_group_rules)
        self.quotas = FakeNovaQuotasManager()
        self.set_management_url = mock.MagicMock()


class FakeHeatClient(object):

    def __init__(self):
        self.stacks = FakeStackManager()


class FakeDesignateClient(object):

    def __init__(self):
        self.domains = FakeDomainManager()


class FakeKeystoneClient(object):

    def __init__(self):
        self.tenants = FakeTenantsManager()
        self.users = FakeUsersManager()
        self.roles = FakeRolesManager()
        self.project_id = 'abc123'
        self.auth_url = 'http://example.com:5000/v2.0/'
        self.auth_token = 'fake'
        self.auth_user_id = generate_uuid()
        self.auth_tenant_id = generate_uuid()
        self.service_catalog = FakeServiceCatalog()
        self.services = FakeServicesManager()
        self.region_name = 'RegionOne'
        self.auth_ref = mock.Mock()
        self.auth_ref.role_names = ['admin']
        self.version = 'v2.0'
        self.session = mock.Mock()
        self.authenticate = mock.MagicMock()

    def authenticate(self):
        return True

    def list_users(self):
        return self.users.list()

    def list_projects(self):
        return self.tenants.list()

    def list_services(self):
        return self.services.list()

    def list_roles(self):
        return self.roles.list()

    def delete_user(self, uuid):
        return self.users.delete(uuid)


class FakeCeilometerClient(object):

    def __init__(self):
        self.alarms = FakeAlarmManager()
        self.meters = FakeMeterManager()
        self.resources = FakeCeilometerResourceManager()
        self.statistics = FakeStatisticsManager()
        self.samples = FakeSampleManager()
        self.query_alarms = FakeQueryManager()
        self.query_samples = FakeQueryManager()
        self.query_alarm_history = FakeQueryManager()


class FakeNeutronClient(object):

    def __init__(self, **kwargs):
        self.__networks = {}
        self.__subnets = {}
        self.__routers = {}
        self.__ports = {}
        self.__tenant_id = kwargs.get("tenant_id", generate_uuid())

        self.format = "json"
        self.version = "2.0"

    @staticmethod
    def _filter(resource_list, search_opts):
        return [res for res in resource_list
                if all(res[field] == value
                       for field, value in search_opts.items())]

    def add_interface_router(self, router_id, data):
        subnet_id = data["subnet_id"]

        if (router_id not in self.__routers or
                subnet_id not in self.__subnets):
            raise neutron_exceptions.NeutronClientException

        subnet = self.__subnets[subnet_id]

        port = self.create_port(
            {"port": {"network_id": subnet["network_id"]}})["port"]
        port["device_id"] = router_id
        port["fixed_ips"].append({"subnet_id": subnet_id,
                                  "ip_address": subnet["gateway_ip"]})

        return {"subnet_id": subnet_id,
                "tenant_id": port["tenant_id"],
                "port_id": port["id"],
                "id": router_id}

    def create_network(self, data):
        network = setup_dict(data["network"],
                             defaults={"name": generate_name("net_"),
                                       "admin_state_up": True})
        network_id = generate_uuid()
        network.update({"id": network_id,
                        "status": "ACTIVE",
                        "subnets": [],
                        "provider:physical_network": None,
                        "tenant_id": self.__tenant_id,
                        "provider:network_type": "local",
                        "router:external": True,
                        "shared": False,
                        "provider:segmentation_id": None})
        self.__networks[network_id] = network
        return {"network": network}

    def create_port(self, data):
        port = setup_dict(data["port"],
                          required=["network_id"],
                          defaults={"name": generate_name("port_"),
                                    "admin_state_up": True})
        if port["network_id"] not in self.__networks:
            raise neutron_exceptions.NeutronClientException

        port_id = generate_uuid()
        port.update({"id": port_id,
                     "status": "ACTIVE",
                     "binding:host_id": "fakehost",
                     "extra_dhcp_opts": [],
                     "binding:vnic_type": "normal",
                     "binding:vif_type": "ovs",
                     "device_owner": "",
                     "mac_address": generate_mac(),
                     "binding:profile": {},
                     "binding:vif_details": {u'port_filter': True},
                     "security_groups": [],
                     "fixed_ips": [],
                     "device_id": "",
                     "tenant_id": self.__tenant_id,
                     "allowed_address_pairs": []})
        self.__ports[port_id] = port
        return {"port": port}

    def create_router(self, data):
        router = setup_dict(data["router"],
                            defaults={"name": generate_name("router_"),
                                      "admin_state_up": True})
        router_id = generate_uuid()
        router.update({"id": router_id,
                       "status": "ACTIVE",
                       "external_gateway_info": None,
                       "tenant_id": self.__tenant_id})
        self.__routers[router_id] = router
        return {"router": router}

    def create_subnet(self, data):
        subnet = setup_dict(data["subnet"],
                            required=["network_id", "cidr", "ip_version"],
                            defaults={"name": generate_name("subnet_")})
        if subnet["network_id"] not in self.__networks:
            raise neutron_exceptions.NeutronClientException

        subnet_id = generate_uuid()
        subnet.update({"id": subnet_id,
                       "enable_dhcp": True,
                       "tenant_id": self.__tenant_id,
                       "dns_nameservers": [],
                       "ipv6_ra_mode": None,
                       "allocation_pools": [],
                       "gateway_ip": re.sub('./.*$', '1', subnet["cidr"]),
                       "ipv6_address_mode": None,
                       "ip_version": 4,
                       "host_routes": []})
        self.__subnets[subnet_id] = subnet
        return {"subnet": subnet}

    def update_network(self, network_id, data):
        if network_id not in self.__networks:
            raise neutron_exceptions.NeutronClientException
        self.__networks[network_id].update(data)

    def update_subnet(self, subnet_id, data):
        if subnet_id not in self.__subnets:
            raise neutron_exceptions.NeutronClientException
        self.__subnets[subnet_id].update(data)

    def update_port(self, port_id, data):
        if port_id not in self.__ports:
            raise neutron_exceptions.NeutronClientException
        self.__ports[port_id].update(data)

    def update_router(self, router_id, data):
        if router_id not in self.__routers:
            raise neutron_exceptions.NeutronClientException
        self.__routers[router_id].update(data)

    def delete_network(self, network_id):
        if network_id not in self.__networks:
            raise neutron_exceptions.NeutronClientException
        for port in self.__ports.values():
            if port["network_id"] == network_id:
                # Network is in use by port
                raise neutron_exceptions.NeutronClientException
        del self.__networks[network_id]
        return ""

    def delete_port(self, port_id):
        if port_id not in self.__ports:
            raise neutron_exceptions.PortNotFoundClient
        if self.__ports[port_id]["device_owner"]:
            # Port is owned by some device
            raise neutron_exceptions.NeutronClientException
        del self.__ports[port_id]
        return ""

    def delete_router(self, router_id):
        if router_id not in self.__routers:
            raise neutron_exceptions.NeutronClientException
        for port in self.__ports.values():
            if port["device_id"] == router_id:
                # Router has active port
                raise neutron_exceptions.NeutronClientException
        del self.__routers[router_id]
        return ""

    def delete_subnet(self, subnet_id):
        if subnet_id not in self.__subnets:
            raise neutron_exceptions.NeutronClientException
        for port in self.__ports.values():
            for fip in port["fixed_ips"]:
                if fip["subnet_id"] == subnet_id:
                    # Subnet has IP allocation from some port
                    raise neutron_exceptions.NeutronClientException
        del self.__subnets[subnet_id]
        return ""

    def list_networks(self, **search_opts):
        nets = self._filter(self.__networks.values(), search_opts)
        return {"networks": nets}

    def list_ports(self, **search_opts):
        ports = self._filter(self.__ports.values(), search_opts)
        return {"ports": ports}

    def list_routers(self, **search_opts):
        routers = self._filter(self.__routers.values(), search_opts)
        return {"routers": routers}

    def list_subnets(self, **search_opts):
        subnets = self._filter(self.__subnets.values(), search_opts)
        return {"subnets": subnets}

    def remove_interface_router(self, router_id, data):
        subnet_id = data["subnet_id"]

        if (router_id not in self.__routers
                or subnet_id not in self.__subnets):
            raise neutron_exceptions.NeutronClientException

        subnet = self.__subnets[subnet_id]

        for port_id, port in self.__ports.items():
            if port["device_id"] == router_id:
                for fip in port["fixed_ips"]:
                    if fip["subnet_id"] == subnet_id:
                        del self.__ports[port_id]
                        return {"subnet_id": subnet_id,
                                "tenant_id": subnet["tenant_id"],
                                "port_id": port_id,
                                "id": router_id}

        raise neutron_exceptions.NeutronClientException


class FakeIronicClient(object):

    def __init__(self):
        # TODO(romcheg):Fake Manager subclasses to manage BM nodes.
        pass


class FakeSaharaClient(object):

    def __init__(self):
        self.job_executions = mock.MagicMock()
        self.jobs = mock.MagicMock()
        self.job_binary_internals = mock.MagicMock()
        self.job_binaries = mock.MagicMock()
        self.data_sources = mock.MagicMock()

        self.clusters = mock.MagicMock()
        self.cluster_templates = mock.MagicMock()
        self.node_group_templates = mock.MagicMock()

        self.setup_list_methods()

    def setup_list_methods(self):
        mock_with_id = mock.MagicMock()
        mock_with_id.id = 42

        # First call of list returns a list with one object, the next should
        # empty after delete.
        self.job_executions.list.side_effect = [[mock_with_id], []]
        self.jobs.list.side_effect = [[mock_with_id], []]
        self.job_binary_internals.list.side_effect = [[mock_with_id], []]
        self.job_binaries.list.side_effect = [[mock_with_id], []]
        self.data_sources.list.side_effect = [[mock_with_id], []]

        self.clusters.list.side_effect = [[mock_with_id], []]
        self.cluster_templates.list.side_effect = [[mock_with_id], []]
        self.node_group_templates.list.side_effect = [[mock_with_id], []]


class FakeZaqarClient(object):

    def __init__(self):
        self.queues = FakeQueuesManager()

    def create_queue(self):
        return self.queues.create("fizbit")


class FakeClients(object):

    def __init__(self, endpoint_=None):
        self._nova = None
        self._glance = None
        self._keystone = None
        self._cinder = None
        self._neutron = None
        self._sahara = None
        self._heat = None
        self._designate = None
        self._ceilometer = None
        self._zaqar = None
        self._endpoint = endpoint_ or endpoint.Endpoint(
            "http://fake.example.org:5000/v2.0/",
            "fake_username",
            "fake_password",
            "fake_tenant_name")

    def keystone(self):
        if not self._keystone:
            self._keystone = FakeKeystoneClient()
        return self._keystone

    def verified_keystone(self):
        return self.keystone()

    def nova(self):
        if not self._nova:
            self._nova = FakeNovaClient()
        return self._nova

    def glance(self):
        if not self._glance:
            self._glance = FakeGlanceClient()
        return self._glance

    def cinder(self):
        if not self._cinder:
            self._cinder = FakeCinderClient()
        return self._cinder

    def neutron(self):
        if not self._neutron:
            self._neutron = FakeNeutronClient()
        return self._neutron

    def sahara(self):
        if not self._sahara:
            self._sahara = FakeSaharaClient()
        return self._sahara

    def heat(self):
        if not self._heat:
            self._heat = FakeHeatClient()
        return self._heat

    def designate(self):
        if not self._designate:
            self._designate = FakeDesignateClient()
        return self._designate

    def ceilometer(self):
        if not self._ceilometer:
            self._ceilometer = FakeCeilometerClient()
        return self._ceilometer

    def zaqar(self):
        if not self._zaqar:
            self._zaqar = FakeZaqarClient()
        return self._zaqar


class FakeRunner(object):

    CONFIG_SCHEMA = {
        "type": "object",
        "$schema": rally_utils.JSON_SCHEMA,
        "properties": {
            "type": {
                "type": "string",
                "enum": ["fake"]
            },

            "a": {
                "type": "string"
            },

            "b": {
                "type": "number"
            }
        },
        "required": ["type", "a"]
    }


class FakeScenario(base.Scenario):

    def idle_time(self):
        return 0

    def do_it(self, **kwargs):
        pass

    def with_output(self, **kwargs):
        return {"data": {"a": 1}, "error": None}

    def too_long(self, **kwargs):
        pass

    def something_went_wrong(self, **kwargs):
        raise Exception("Something went wrong")

    def raise_timeout(self, **kwargs):
        raise multiprocessing.TimeoutError()


class FakeTimer(rally_utils.Timer):

    def duration(self):
        return 10


class FakeContext(base_ctx.Context):

    __ctx_name__ = "fake"
    __ctx_order__ = 1

    CONFIG_SCHEMA = {
        "type": "object",
        "$schema": rally_utils.JSON_SCHEMA,
        "properties": {
            "test": {
                "type": "integer"
            },
        },
        "additionalProperties": False
    }

    def setup(self):
        pass

    def cleanup(self):
        pass


class FakeUserContext(FakeContext):

    admin = {
        "id": "adminuuid",
        "endpoint": endpoint.Endpoint("aurl", "aname", "apwd", "atenant")
    }
    user = {
        "id": "uuid",
        "endpoint": endpoint.Endpoint("url", "name", "pwd", "tenant")
    }
    tenant = {"id": "uuid", "nema": "tenant"}

    def __init__(self, context):
        context.setdefault("task", mock.MagicMock())
        super(FakeUserContext, self).__init__(context)

        context.setdefault("admin", FakeUserContext.admin)
        context.setdefault("users", [FakeUserContext.user])
        context.setdefault("tenants", [FakeUserContext.tenant])
        context.setdefault("scenario_name",
                           'NovaServers.boot_server_from_volume_and_delete')


class FakeDeployment(dict):
    update_status = mock.Mock()