import pyeapi
import config

def parsevlans(vlans):
    parsedvlans = []

    if vlans == 'none':
        return parsedvlans

    # split by comma
    vlanslist = vlans.split(',')

    # check for ranges
    for vlan in vlanslist:
        vlanrange = vlan.split('-')
        if len(vlanrange) > 1:
            x = range(int(vlanrange[0]), int(vlanrange[1]) + 1)
            for n in x:
                parsedvlans.append(n)
        else:
            parsedvlans.append(int(vlan))

    return parsedvlans

def createvlan(vlans, vlan):
    existingvlan = vlans.get(vlan)
    if not existingvlan:
        print ('Vlan %s does not exists, so adding it' % vlan)
        return vlans.create(vlan)

    return False

def deletevlan(vlans, switchports, vlan):
    existingvlan = vlans.get(vlan)
    if existingvlan:
        for host in config.SWITCHPORTS_MAPPINGS:
            switchport = config.SWITCHPORTS_MAPPINGS[host]
            interface = switchports.get(switchport)
            allowedvlans = parsevlans(interface.get('trunk_allowed_vlans'))
            if vlan in allowedvlans:
                return False

        print ('Vlan %s exists and it is not used, so removing it' % vlan)
        return vlans.delete(vlan)

    return False

def manageswitch(switchconfig, switchport, vlan, action):
    if not isinstance(vlan, int) or vlan == 0:
        print ('ERROR: Invalid vlan id %s' % vlan)

    print ('Connecting to %s' % switchconfig['host'])
    node = pyeapi.connect(host=switchconfig['host'], transport=switchconfig['transport'],
                          username=switchconfig['username'],
                          password=switchconfig['password'], return_node=True)

    switchports = node.api('switchports')
    vlans = node.api('vlans')
    configchanged = False

    interface = switchports.get(switchport)
    allowedvlans = parsevlans(interface.get('trunk_allowed_vlans'))

    if action == 'clean':
        if vlan in allowedvlans:
            print ('Removing VLAN %s from switchport %s' % (vlan, switchport))
            node.config(['interface %s' % switchport, 'switchport trunk allowed vlan remove %s' % vlan])
            configchanged = True
        else:
            print ('VLAN %s is already removed from port %s' % (vlan, switchport))

        if deletevlan(vlans, switchports, vlan):
            configchanged = True
    else:
        if createvlan(vlans, vlan):
            configchanged = True

        if vlan not in allowedvlans:
            print ('Allowing VLAN %s on switchport %s' % (vlan, switchport))
            node.config(['interface %s' % switchport, 'switchport trunk allowed vlan add %s' % vlan])
            configchanged = True
        else:
            print ('VLAN %s is already allowed on port %s' % (vlan, switchport))

    if configchanged:
        print ('Switch config changed, saving configuration')
        node.config('write')
