# Copyright 2015 Spotify AB. All rights reserved.
#
# The contents of this file are licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the
# License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.

from base import NetworkDriver
from utils import string_parsers

from pyIOSXR import IOSXR
from pyIOSXR.exceptions import InvalidInputError, XMLCLIError

from exceptions import MergeConfigException, ReplaceConfigException
import xml.etree.ElementTree as ET


class IOSXRDriver(NetworkDriver):
    def __init__(self, hostname, username, password, timeout=60):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.timeout = timeout
        self.device = IOSXR(hostname, username, password, timeout=timeout)
        self.pending_changes = False
        self.replace = False

    def open(self):
        self.device.open()

    def close(self):
        self.device.close()

    def load_replace_candidate(self, filename=None, config=None):
        self.pending_changes = True
        self.replace = True

        try:
            self.device.load_candidate_config(filename=filename, config=config)
        except InvalidInputError as e:
            self.pending_changes = False
            self.replace = False
            raise ReplaceConfigException(e.message)

    def load_merge_candidate(self, filename=None, config=None):
        self.pending_changes = True
        self.replace = False

        try:
            self.device.load_candidate_config(filename=filename, config=config)
        except InvalidInputError as e:
            self.pending_changes = False
            self.replace = False
            raise MergeConfigException(e.message)

    def compare_config(self):
        if not self.pending_changes:
            return ''
        elif self.replace:
            return self.device.compare_replace_config().strip()
        else:
            return self.device.compare_config().strip()

    def commit_config(self):
        if self.replace:
            self.device.commit_replace_config()
        else:
            self.device.commit_config()
        self.pending_changes = False

    def discard_config(self):
        self.device.discard_config()
        self.pending_changes = False

    def rollback(self):
        self.device.rollback()

    def get_facts(self):

        sh_ver = self.device.show_version()

        for line in sh_ver.splitlines():
            if 'Cisco IOS XR Software' in line:
                os_version = line.split()[-1]
            elif 'uptime' in line:
                uptime = string_parsers.convert_uptime_string_seconds(line)
                hostname = line.split()[0]
                fqdn = line.split()[0]
            elif 'Series' in line:
                model = ' '.join(line.split()[1:3])

        interface_list = list()

        for x in self.device.show_interface_description().splitlines()[3:-1]:
            if '.' not in x:
                interface_list.append(x.split()[0])

        result = {
            'vendor': u'Cisco',
            'os_version': unicode(os_version),
            'hostname': unicode(hostname),
            'uptime': uptime,
            'model': unicode(model),
            'serial_number': u'',
            'fqdn': unicode(fqdn),
            'interface_list': interface_list,
        }

        return result

    def get_interfaces(self):

        # init result dict
        result = {}

        # fetch show interface output
        sh_int = self.device.show_interfaces()
        # split per interface, eg by empty line
        interface_list = sh_int.rstrip().split('\n\n')
        # for each interface...
        for interface in interface_list:

            # splitting this and matching each line avoids issues with order
            # sorry...
            interface_lines = interface.split('\n')

            # init variables to match for
            interface_name = None
            is_enabled = None
            is_up = None
            mac_address = None
            description = None
            speed = None

            # loop though and match each line
            for line in interface_lines:
                description = ''
                if 'line protocol' in line:
                    lp = line.split()
                    interface_name = lp[0]
                    is_enabled = lp[2] == 'up,'
                    is_up = lp[6] == 'up'
                elif 'bia' in line:
                    mac_address = line.split()[-1].replace(')', '')
                elif 'Description' in line:
                    description = ' '.join(line.split()[1:])
                elif 'BW' in line:
                    speed = int(line.split()[4]) / 1000
            result[interface_name] = {
                'is_enabled': is_enabled,
                'is_up': is_up,
                'mac_address': unicode(mac_address),
                'description': unicode(description),
                'speed': speed,
                'last_flapped': -1.0,
            }

        return result

    def get_interfaces_counters(self):
        rpc_command = "<Get><Operational><Interfaces><InterfaceTable></InterfaceTable></Interfaces></Operational></Get>"
        result_tree = ET.fromstring(self.device.make_rpc_call(rpc_command))

        interface_counters = dict()

        for interface in result_tree.iter('Interface'):

            interface_name = interface.find('InterfaceHandle').text

            interface_stats = dict()

            if not interface.find('InterfaceStatistics'):
                continue
            else:
                interface_stats = dict()
                interface_stats['tx_multicast_packets'] = int(interface.find(
                    'InterfaceStatistics/FullInterfaceStats/MulticastPacketsSent').text)
                interface_stats['tx_discards'] = int(interface.find(
                    'InterfaceStatistics/FullInterfaceStats/OutputDrops').text)
                interface_stats['tx_octets'] = int(interface.find(
                    'InterfaceStatistics/FullInterfaceStats/BytesSent').text)
                interface_stats['tx_errors'] = int(interface.find(
                    'InterfaceStatistics/FullInterfaceStats/OutputErrors').text)
                interface_stats['rx_octets'] = int(interface.find(
                    'InterfaceStatistics/FullInterfaceStats/BytesReceived').text)
                interface_stats['tx_unicast_packets'] = int(interface.find(
                    'InterfaceStatistics/FullInterfaceStats/PacketsSent').text)
                interface_stats['rx_errors'] = int(interface.find(
                    'InterfaceStatistics/FullInterfaceStats/InputErrors').text)
                interface_stats['tx_broadcast_packets'] = int(interface.find(
                    'InterfaceStatistics/FullInterfaceStats/BroadcastPacketsSent').text)
                interface_stats['rx_multicast_packets'] = int(interface.find(
                    'InterfaceStatistics/FullInterfaceStats/MulticastPacketsReceived').text)
                interface_stats['rx_broadcast_packets'] = int(interface.find(
                    'InterfaceStatistics/FullInterfaceStats/BroadcastPacketsReceived').text)
                interface_stats['rx_discards'] = int(interface.find(
                    'InterfaceStatistics/FullInterfaceStats/InputDrops').text)
                interface_stats['rx_unicast_packets'] = int(interface.find(
                    'InterfaceStatistics/FullInterfaceStats/PacketsReceived').text)

            interface_counters[interface_name] = interface_stats

        return interface_counters

    def get_bgp_neighbors(self):
        def generate_vrf_query(vrf_name):
            """
            Helper to provide XML-query for the VRF-type we're interested in.
            """
            if vrf_name == "global":
                rpc_command = """<Get>
                        <Operational>
                            <BGP>
                                <InstanceTable>
                                    <Instance>
                                        <Naming>
                                            <InstanceName>
                                                default
                                            </InstanceName>
                                        </Naming>
                                        <InstanceActive>
                                            <DefaultVRF>
                                                <GlobalProcessInfo>
                                                </GlobalProcessInfo>
                                                <NeighborTable>
                                                </NeighborTable>
                                            </DefaultVRF>
                                        </InstanceActive>
                                    </Instance>
                                </InstanceTable>
                            </BGP>
                        </Operational>
                    </Get>"""

            else:
                rpc_command = """<Get>
                        <Operational>
                            <BGP>
                                <InstanceTable>
                                    <Instance>
                                        <Naming>
                                            <InstanceName>
                                                default
                                            </InstanceName>
                                        </Naming>
                                        <InstanceActive>
                                            <VRFTable>
                                                <VRF>
                                                    <Naming>
                                                        %s
                                                    </Naming>
                                                    <GlobalProcessInfo>
                                                    </GlobalProcessInfo>
                                                    <NeighborTable>
                                                    </NeighborTable>
                                                </VRF>
                                            </VRFTable>
                                         </InstanceActive>
                                    </Instance>
                                </InstanceTable>
                            </BGP>
                        </Operational>
                    </Get>""" % vrf_name
            return rpc_command

        """
        Initial run to figure out what VRF's are available
        Decided to get this one from Configured-section because bulk-getting all instance-data to do the same could get ridiculously heavy
        Assuming we're always interested in the DefaultVRF
        """

        active_vrfs = ["global"]

        rpc_command = """<Get>
                            <Operational>
                                <BGP>
                                    <ConfigInstanceTable>
                                        <ConfigInstance>
                                            <Naming>
                                                <InstanceName>
                                                    default
                                                </InstanceName>
                                            </Naming>
                                            <ConfigInstanceVRFTable>
                                            </ConfigInstanceVRFTable>
                                        </ConfigInstance>
                                    </ConfigInstanceTable>
                                </BGP>
                            </Operational>
                        </Get>"""

        result_tree = ET.fromstring(self.device.make_rpc_call(rpc_command))

        #for node in result_tree.iter('ConfigVRF'):
        #    active_vrfs.append(str(node.find('Naming/VRFName').text))

        result = dict()

        for vrf in active_vrfs:
            rpc_command = generate_vrf_query(vrf)
            result_tree = ET.fromstring(self.device.make_rpc_call(rpc_command))

            this_vrf = dict()
            this_vrf['router_id'] = int()
            this_vrf['peers'] = dict()

            if vrf == "global":
                this_vrf['router_id'] = result_tree.find(
                    'Get/Operational/BGP/InstanceTable/Instance/InstanceActive/DefaultVRF/GlobalProcessInfo/VRF/RouterID').text
            else:
                this_vrf['router_id'] = result_tree.find(
                    'Get/Operational/BGP/InstanceTable/Instance/InstanceActive/VRFTable/VRF/GlobalProcessInfo/VRF/RouterID').text

            neighbors = dict()

            for neighbor in result_tree.iter('Neighbor'):

                this_neighbor = dict()
                this_neighbor['local_as'] = int(neighbor.find('LocalAS').text)
                this_neighbor['remote_as'] = int(neighbor.find(
                    'RemoteAS').text)
                this_neighbor['remote_id'] = str(neighbor.find(
                    'RouterID').text)

                if neighbor.find('ConnectionAdminStatus').text is "1":
                    this_neighbor['is_enabled'] = True
                try:
                    this_neighbor['description'] = str(neighbor.find(
                        'Description').text)
                except:
                    pass

                if str(neighbor.find(
                        'ConnectionState').text) == "BGP_ST_ESTAB":
                    this_neighbor['is_up'] = True
                    this_neighbor['uptime'] = int(neighbor.find(
                        'ConnectionEstablishedTime').text)
                else:
                    this_neighbor['is_up'] = False
                    this_neighbor['uptime'] = -1

                this_neighbor['address_family'] = dict()

                for entry in neighbor.iter('AFData'):
                    if entry.find('Entry/AFName').text == "IPv4":
                        this_afi = "ipv4"
                    elif entry.find('Entry/AFName').text == "IPv6":
                        this_afi = "ipv6"
                    else:
                        this_afi = entry.find('Entry/AFName').text

                    this_neighbor['address_family'][this_afi] = dict()
                    this_neighbor['address_family'][this_afi][
                        "received_prefixes"] = int(entry.find(
                            'Entry/PrefixesAccepted').text) + int(entry.find(
                                'Entry/PrefixesDenied').text)
                    this_neighbor['address_family'][this_afi][
                        "accepted_prefixes"] = int(entry.find(
                            'Entry/PrefixesAccepted').text)
                    this_neighbor['address_family'][this_afi][
                        "sent_prefixes"] = int(entry.find(
                            'Entry/PrefixesAdvertised').text)

                try:
                    neighbor_ip = str(neighbor.find(
                        'Naming/NeighborAddress/IPV4Address').text)
                except:
                    neighbor_ip = str(neighbor.find(
                        'Naming/NeighborAddress/IPV6Address').text)

                neighbors[neighbor_ip] = this_neighbor

            this_vrf['peers'] = neighbors
            result[vrf] = this_vrf

        return result

    def get_lldp_neighbors(self):

        # init result dict
        lldp = {}

        # fetch sh ip bgp output
        sh_lldp = self.device.show_lldp_neighbors().splitlines()[5:-3]

        for n in sh_lldp:
            local_interface = n.split()[1]
            if local_interface not in lldp.keys():
                lldp[local_interface] = list()

            lldp[local_interface].append({
                'hostname': unicode(n.split()[0]),
                'port': unicode(n.split()[4]),
            })

        return lldp
