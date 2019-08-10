# -------------------------------------------------------------------------- #
# Copyright 2002-2019, OpenNebula Project, OpenNebula Systems                #
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

require 'vnmmad'

################################################################################
# This driver tag VM traffic with a VLAN_ID using 802.1Q protocol. Features:
#   - Creates a bridge and bind phisycal device if not present
#   - Creates a tagged interface for the VM dev.vlan_id
#
# Once activated the VM will be attached to this bridge
################################################################################
class VLANTagDriver < VNMMAD::VLANDriver

    # DRIVER name and XPATH for relevant NICs
    DRIVER       = "802.1Q"
    XPATH_FILTER = "TEMPLATE/NIC[VN_MAD='802.1Q_dynamic']"

    # Creates a new VNMDriver using:
    #   @param vm_64 [String] Base64 encoded XML String from oned
    #   @param deploy_id [String]
    def self.from_base64(vm_64, xpath_filter = nil, deploy_id = nil, host = nil)
        vm_xml = Base64::decode64(vm_64)

        self.new(vm_xml, xpath_filter, deploy_id, host)
    end

    ############################################################################
    # Create driver device operations are locked
    ############################################################################
    def initialize(vm, xpath_filter = nil, deploy_id = nil, host = nil)
        @locking = true
        @host = host

        xpath_filter ||= XPATH_FILTER
        super(vm, xpath_filter, deploy_id)
    end

    ############################################################################
    # This function creates and activate a VLAN device
    ############################################################################
    def create_vlan_dev
        mtu = @nic[:mtu] ? "mtu #{@nic[:mtu]}" : "mtu #{CONF[:vlan_mtu]}"

        ip_link_conf = ""

        @nic[:ip_link_conf].each do |option, value|
            case value
            when true
                value = "on"
            when false
                value = "off"
            end

            ip_link_conf << "#{option} #{value} "
        end

        OpenNebula.exec_and_log("#{command(:ip)} link add link"\
            " #{@nic[:phydev]} name #{@nic[:vlan_dev]} #{mtu} type vlan id"\
            " #{@nic[:vlan_id]} #{ip_link_conf}")

        OpenNebula.exec_and_log("#{command(:ip)} link set #{@nic[:vlan_dev]} up")

        OpenNebula.exec_and_log("PYTHONHTTPSVERIFY=0 /var/tmp/one/vnm/802.1Q_dynamic/one-arista.py pre #{@nic[:vlan_id]} #{@host}")
    end
    
    def delete_vlan_dev
		OpenNebula.exec_and_log("#{command(:ip)} link delete"\
            " #{@nic[:vlan_dev]}") if @nic[:vlan_dev] != @nic[:phydev]

        OpenNebula.exec_and_log("PYTHONHTTPSVERIFY=0 /var/tmp/one/vnm/802.1Q_dynamic/one-arista.py clean #{@nic[:vlan_id]} #{@host}")
    end

    def get_interface_vlan(name)
        text = %x(#{command(:ip)} -d link show #{name})
        return nil if $?.exitstatus != 0

        text.each_line do |line|
            m = line.match(/vlan protocol 802.1Q id (\d+)/)

            return m[1] if m
        end

        nil
    end
end
