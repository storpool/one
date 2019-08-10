#!/usr/bin/env python

import sys
import config
import functions

actions = ['pre', 'post', 'clean']
action = sys.argv[1]
if action not in actions:
    exit(0)

vlan = int(sys.argv[2])
host = sys.argv[3]

if host not in config.SWITCHPORTS_MAPPINGS:
    print 'ERROR: Unknown host %s!' % (host)
    exit(1)

if not config.VALID_VLANS_RANGE[0] <= vlan <= config.VALID_VLANS_RANGE[1]:
    print 'ERROR: Vlan %s is not allowed by policy!' % (vlan)
    print 'Valid vlans are withing range from %s to %s' % (config.VALID_VLANS_RANGE[0], config.VALID_VLANS_RANGE[1])
    exit(0)

switchport = config.SWITCHPORTS_MAPPINGS[host]

for switch in config.SWITCHES:
    print 'Manage switch %s' % (switch)
    functions.manageswitch(config.SWITCHES[switch], switchport, vlan, action)
