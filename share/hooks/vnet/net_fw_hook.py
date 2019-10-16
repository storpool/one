#!/usr/bin/env python
'''
# -------------------------------------------------------------------------- #
# Copyright 2015-2019, StorPool (storpool.com)                               #
#                                                                            #
# Licensed under the Apache License, Version 2.0 (the "License"); you may    #
# not use this file except in compliance with the License. You may obtain    #
# a copy of the License at                                                   #
#                                                                            #
# http://www.apache.org/licenses/LICENSE-2.0                                 #
#                                                                            #
# Unless required by applicable law or agreed to in writing, software        #
# distributed under the License is distributed on an "AS IS" BASIS,          #
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.   #
# See the License for the specific language governing permissions and        #
# limitations under the License.                                             #
#--------------------------------------------------------------------------- #

configure in /etc/one/oned.conf

VM_HOOK = [
    name      = "net_fw_hook",
    on        = "CUSTOM",
    state     = "ACTIVE",
    lcm_state = "HOTPLUG_NIC",
    command   = "vnet/net_fw_hook.py",
    remote    = "YES",
    arguments = "-i $TEMPLATE" ]
'''

from __future__ import print_function

import os
from sys import stdin, stderr, argv
from re import match
from base64 import decodestring
from xml.etree import ElementTree as ET
import subprocess
import tempfile
import syslog

def parse_alias_nic_data(vm_root):
    ''' Parse NIC_ALIAS values from VM Template XML

    Parameters:
    vm_root (ElementTree): VM Template

    Returns:
    dict: parsed NIC_ALIAS related data
    '''

    xpath = './/TEMPLATE/NIC_ALIAS[ATTACH="YES"]'
    a_entry = vm_root.find(xpath)
    if a_entry is None:
        raise KeyError(xpath)
    alias_data = {}
    for e in ['ALIAS_ID', 'PARENT_ID', 'IP', 'NAME', 'IP6']:
        try:
            if e[-3:] == '_ID':
                alias_data[e] = int(a_entry.find('./{e}'.format(e=e)).text)
            else:
                alias_data[e] = a_entry.find('./{e}'.format(e=e)).text
        except Exception:
            pass
    if not alias_data:
        msg = "Can't parse NIC_ALIAS"
        raise Exception(msg)
    return alias_data

def parse_nic_data(vm_root, vm):
    ''' Parse NIC_ALIAS values from VM Template XML

    Parameters:
    vm_root (ElementTree): VM Template
    vm (dict): VM data

    Returns:
    dict: parsed NIC related data
    '''

    xpath = './/TEMPLATE/NIC[NIC_ID="{n}"]'.format(n=vm['a']['PARENT_ID'])
    n_entry = vm_root.find(xpath)
    if n_entry is None:
        raise KeyError(xpath)
    nic_data = {}
    for e in ['IP', 'VN_MAD', 'ALIAS_IDS', 'FILTER_IP_SPOOFING', 'FILTER',
              'NIC_ID', 'FILTER_ARP_SPOOFING']:
        try:
            if e[-3:] == '_ID':
                nic_data[e] = int(n_entry.find('./{e}'.format(e=e)).text)
            else:
                nic_data[e] = n_entry.find('./{e}'.format(e=e)).text
        except Exception:
            pass
    if 'ALIAS_IDS' not in nic_data:
        msg = "Can't find NIC/ALIAS_IDS".format(d=vm['domain'])
        raise KeyError(msg)
    return nic_data

def toggle_ebtables_filter(vm):
    syslog.syslog(syslog.LOG_DEBUG, 'toggle_ebtables_filter')
    if 'IP' in vm['a']:
        action = '-D'
        if vm['action'] == 'add':
            action = '-A'
        for d in ['i','o']:
            rule = 'src'
            if d == 'o':
                rule = 'dst'
            chain = "{n}-{d}-arp4".format(n=vm['nicdev'],d=d)
            cmd = ['sudo', 'ebtables', '-t', 'nat', action, chain,
              '-p', 'ARP', '--arp-ip-{r}'.format(r=rule), vm['a']['IP'],
              '-j', 'RETURN']
            msg = ' '.join(cmd)
            syslog.syslog(syslog.LOG_INFO, msg)
            subprocess.call(cmd)

def toggle_ipset_filter(vm):
    ''' add/del ipset rule for the given ALIAS IP

    Parameters:
    vm (dict): VM Related data

    Returns:
    '''

    for addr in ['IP', 'IP6']:
        if addr in vm['a']:
            chain = "{n}-{a}-spoofing".format(n=vm['nicdev'],a=addr.lower())
            cmd = ['sudo', 'ipset', '-exist', vm['action'], chain, vm['a'][addr]]
            msg = ' '.join(cmd)
            syslog.syslog(syslog.LOG_INFO, msg)
            subprocess.call(cmd)

def toggle_libvirt_filter(vm):
    ''' add/del filterref parameter with the  ALIAS IP
        in VM's domain XML

    Parameters:
    vm (dict): VM Related data

    Returns:
    '''

    domain_xml = subprocess.check_output(['virsh',
                                          '--connect',
                                          'qemu:///system',
                                          'dumpxml',
                                          vm['domain']]
                                        )
    dom = ET.fromstring(domain_xml)

    xpath = './devices/interface'
    for interface_e in dom.findall(xpath):
        target_e = interface_e.find('./target')
        if target_e.attrib['dev'] != vm['nicdev']:
            continue
        do_update = False
        for fref in interface_e.findall('./filterref'):
            if fref.attrib['filter'] != vm['n']['FILTER']:
                msg = "{d} skipping {n} filterref {f}<>{vf}".format(
                    d=vm['domain'], n=vm['nicdev'], f=fref.attrib['filter'],
                    vf=vm['n']['FILTER'])
                syslog.syslog(msg)
                continue
            do_add = True
            for p in fref.findall('./parameter'):
#                msg = '{} parameter {}'.format(vm['nicdev'], p.attrib)
#                syslog.syslog(msg)
                fref_ip = p.attrib['value']
                if fref_ip != vm['a']['IP']:
                    continue
                if vm['action'] == 'del':
                    fref.remove(p)
                    msg = "{n} delete filterref/parameter {i}".format(
                        n=vm['nicdev'], i=vm['a']['IP'])
                    do_update = True
                else:
                    msg = "{n} exists filterref/parameter {i}".format(
                        n=vm['nicdev'], i=vm['a']['IP'])
                    do_add = False
                syslog.syslog(msg)
            if do_add is True and vm['action'] == 'add':
                ET.SubElement(fref, 'parameter',
                              {'name': 'IP', 'value': vm['a']['IP']})
                msg = "{n} add filterref/parameter {i}".format(
                    n=vm['nicdev'], i=vm['a']['IP'])
                syslog.syslog(msg)
                do_update = True

        if do_update is False:
            continue
        interface_xml = ET.tostring(interface_e,
                                    encoding='utf8', method='xml')
        t_fd, t_name = tempfile.mkstemp()
        with open(t_name, 'w') as fd:
            fd.write(interface_xml)
        os.close(t_fd)
        cmd = ['virsh', '--connect', 'qemu:///system',
               'update-device', vm['domain'],
               '--live', '--file', t_name]
        subprocess.call(cmd)
        os.remove(t_name)
        syslog.syslog(syslog.LOG_INFO,
                      "{n} updated (domain {d})".format(n=vm['nicdev'], d=vm['domain']))

def main(vm_base):
    ''' Main function


    Parameters:
    vm (dict): VM Related data
    '''

    vm = {}
    try:
        vm_root = ET.fromstring(decodestring(vm_base))
        vm['id'] = int(vm_root.find('./ID').text)
        vm['domain'] = "one-{v}".format(v=vm['id'])
    except Exception as ex:
        msg = 'Error processing VM TEMPLATE XML: {e}'.format(e=ex)
        print(msg, file=stderr)
        syslog.syslog(syslog.LOG_ERR, msg)
        exit(1)

    try:
        vm['a'] = parse_alias_nic_data(vm_root)
        vm['n'] = parse_nic_data(vm_root, vm)
    except KeyError as ex:
        msg = "{d} KeyError:{e}".format(d=vm['domain'], e=ex)
        print(msg, file=stderr)
        syslog.syslog(syslog.LOG_ERR, msg)
        exit(1)
    except Exception as ex:
        msg = "{d} Error:{e}".format(d=vm['domain'], e=ex)
        syslog.syslog(syslog.LOG_INFO, msg)
        exit(0)

    try:
        vm['nicdev'] = "{d}-{p}".format(d=vm['domain'], p=vm['a']['PARENT_ID'])
        vm['a']['idx'] = int(match(r'.*_ALIAS(\d+)', vm['a']['NAME']).group(1))
    except Exception as ex:
        msg = "{d} Error:{e}".format(d=vm['domain'], e=ex)
        print(msg, file=stderr)
        syslog.syslog(syslog.LOG_ERR, msg)
        exit(1)

    # attaching or detaching?
    vm['action'] = 'del'
    if 'ALIAS_IDS' in vm['n'] and vm['n']['ALIAS_IDS'] is not None:
        for idx in vm['n']['ALIAS_IDS'].split(','):
            if int(idx) == vm['a']['idx']:
                vm['action'] = 'add'
    #syslog.syslog("{n} action:{a} /{v}".format(n=vm['nicdev'], a=action, v=vm))

    try:
        fltr = 'FILTER_IP_SPOOFING'
        if fltr in vm['n'] and vm['n'][fltr] == 'YES':
            toggle_ipset_filter(vm)
        else:
            msg = "{n} has no {f}:{v}".format(n=vm['nicdev'], f=fltr, v=vm['n'])
            syslog.syslog(syslog.LOG_DEBUG, msg)

        fltr = 'FILTER'
        if fltr in vm['n'] and vm['n'][fltr] == 'clean-traffic':
            toggle_libvirt_filter(vm)
        else:
            msg = "{n} has no {f}:{v}".format(n=vm['nicdev'], f=fltr, v=vm['n'])
            syslog.syslog(syslog.LOG_DEBUG, msg)

        fltr = 'FILTER_ARP_SPOOFING'
        if fltr in vm['n'] and vm['n'][fltr] == 'YES':
            toggle_ebtables_filter(vm)
        else:
            msg = "{n} has no {f}:{v}".format(n=vm['nicdev'], f=fltr, v=vm['n'])
            syslog.syslog(syslog.LOG_DEBUG, msg)
    except Exception as ex:
        msg = "{d} Error: {e}".format(d=vm['domain'], e=ex)
        print(msg, file=stderr)
        syslog.syslog(syslog.LOG_ERR, msg)
        exit(1)

if __name__ == '__main__':

    syslog.openlog(logoption=syslog.LOG_PID, facility=syslog.LOG_USER)

    NAME_SPACE = {'qemu': 'http://libvirt.org/schemas/domain/qemu/1.0'}
    for prefix, uri in NAME_SPACE.items():
        ET.register_namespace(prefix, uri)

    if len(argv) == 2:
        VM_BASE = argv[1]
    else:
        VM_BASE = stdin.read()

    main(VM_BASE)
